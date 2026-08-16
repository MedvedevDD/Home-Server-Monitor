#!/bin/sh
set -eu

INSTALL_DIR="/opt/home-server-monitor"
CACHE_DIR="/var/cache/home-server-monitor"
DEFAULTS_FILE="/etc/default/home-server-monitor"
TELEGRAF_MAIN_CONF="/etc/telegraf/telegraf.conf"
TELEGRAF_CONF_DIR="/etc/telegraf/telegraf.d"
TELEGRAF_MANAGED_CONF="$TELEGRAF_CONF_DIR/90-home-server-monitor.conf"
HSM_PREVIOUS_VERSION="fresh-install"
GRAFANA_DASHBOARD_DIR="/var/lib/grafana/dashboards/home-server-monitor"
GRAFANA_PROVISIONING_FILE="/etc/grafana/provisioning/dashboards/home-server-monitor.yaml"
GRAFANA_DB="/var/lib/grafana/grafana.db"
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROXMOX_HELPER="/usr/local/libexec/hsm-proxmox-storage-helper"
PROXMOX_SUDOERS="/etc/sudoers.d/home-server-monitor-proxmox"
HP_SMARTARRAY_HELPER="/usr/local/libexec/hsm-hp-smartarray-helper"
HP_SMARTARRAY_SUDOERS="/etc/sudoers.d/home-server-monitor-hp-smartarray"
COOLING_HELPER="/usr/local/libexec/hsm-x8fan-helper"
COOLING_SUDOERS="/etc/sudoers.d/home-server-monitor-cooling"

log() {
    printf '%s\n' "$1"
}

fail() {
    printf 'ERROR: %s\n' "$1" >&2
    exit 1
}

check_command() {
    command -v "$1" >/dev/null 2>&1 || fail "Required command was not found: $1"
    log "[PASS] $1"
}


ensure_defaults_file() {
    if [ ! -e "$DEFAULTS_FILE" ]; then
        mkdir -p "$(dirname "$DEFAULTS_FILE")"
        cp "$INSTALL_DIR/docs/home-server-monitor.conf.example" "$DEFAULTS_FILE"
        chmod 0644 "$DEFAULTS_FILE"
        log "[PASS] Created $DEFAULTS_FILE"
        return
    fi

    for setting in HSM_STORAGE_HIDE_USB_FLASH HSM_STORAGE_EXCLUDE_SERIALS HSM_STORAGE_EXCLUDE_MODELS HSM_RAID_SSACLI_ENABLED HSM_SSACLI_HELPER HSM_SSACLI_USE_SUDO HSM_PROXMOX_ENABLED HSM_PROXMOX_REQUIRED HSM_PVEVERSION_BINARY HSM_PROXMOX_CPU_SAMPLE_SECONDS HSM_COOLING_ENABLED HSM_COOLING_REQUIRED HSM_COOLING_X8FAN_HELPER HSM_COOLING_X8FAN_USE_SUDO HSM_COOLING_INFLUX_URL HSM_COOLING_INFLUX_DATABASE HSM_COOLING_DISK_MAX_AGE_SECONDS HSM_COOLING_CONTROL_STATE_FILE HSM_COOLING_AUTO_REFRESH_SECONDS; do
        if ! grep -q "^${setting}=" "$DEFAULTS_FILE"; then
            case "$setting" in
                HSM_STORAGE_HIDE_USB_FLASH|HSM_RAID_SSACLI_ENABLED|HSM_SSACLI_USE_SUDO|HSM_PROXMOX_ENABLED|HSM_COOLING_ENABLED|HSM_COOLING_X8FAN_USE_SUDO) value=true ;;
                HSM_SSACLI_HELPER) value=/usr/local/libexec/hsm-hp-smartarray-helper ;;
                HSM_PROXMOX_REQUIRED|HSM_COOLING_REQUIRED) value=false ;;
                HSM_COOLING_X8FAN_HELPER) value=/usr/local/libexec/hsm-x8fan-helper ;;
                HSM_COOLING_INFLUX_URL) value=http://127.0.0.1:8086/query ;;
                HSM_COOLING_INFLUX_DATABASE) value=raid ;;
                HSM_COOLING_DISK_MAX_AGE_SECONDS) value=120 ;;
                HSM_COOLING_CONTROL_STATE_FILE) value=/var/cache/home-server-monitor/cooling-control.json ;;
                HSM_COOLING_AUTO_REFRESH_SECONDS) value=300 ;;
                HSM_PVEVERSION_BINARY) value=pveversion ;;
                HSM_PROXMOX_CPU_SAMPLE_SECONDS) value=0.10 ;;
                *) value= ;;
            esac
            printf '\n%s=%s\n' "$setting" "$value" >> "$DEFAULTS_FILE"
        fi
    done
}

load_defaults() {
    if [ -r "$DEFAULTS_FILE" ]; then
        # shellcheck disable=SC1090
        . "$DEFAULTS_FILE"
    fi
}

detect_influxdb_uid() {
    if [ -n "${HSM_GRAFANA_DATASOURCE_UID:-}" ]; then
        printf '%s' "$HSM_GRAFANA_DATASOURCE_UID"
        return 0
    fi

    if [ ! -r "$GRAFANA_DB" ]; then
        return 1
    fi

    python3 - "$GRAFANA_DB" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
try:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    row = connection.execute(
        "SELECT uid FROM data_source WHERE type = 'influxdb' ORDER BY id LIMIT 1"
    ).fetchone()
except (sqlite3.Error, OSError):
    row = None

if row and row[0]:
    print(row[0], end="")
    raise SystemExit(0)
raise SystemExit(1)
PY
}

render_dashboards() {
    datasource_uid=$1
    source_dir="$INSTALL_DIR/dashboard"
    target_dir="$GRAFANA_DASHBOARD_DIR"

    mkdir -p "$target_dir"

    python3 - "$source_dir" "$target_dir" "$datasource_uid" <<'PY'
import json
import os
import sys

source_dir, target_dir, datasource_uid = sys.argv[1:4]
expected = ("Home.json", "Storage.json", "RAID.json", "UPS.json", "Proxmox.json", "Cooling.json")


def replace(value):
    if isinstance(value, dict):
        return {key: replace(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace(item) for item in value]
    if isinstance(value, str):
        return value.replace("${DS_INFLUXDB}", datasource_uid)
    return value

for filename in expected:
    source = os.path.join(source_dir, filename)
    if not os.path.isfile(source):
        raise SystemExit(f"Missing dashboard template: {source}")
    with open(source, "r", encoding="utf-8") as handle:
        dashboard = replace(json.load(handle))
    dashboard.pop("__inputs", None)
    target = os.path.join(target_dir, filename)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(dashboard, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
PY

    chown -R grafana:grafana "$target_dir"
    find "$target_dir" -type d -exec chmod 0755 {} +
    find "$target_dir" -type f -name '*.json' -exec chmod 0644 {} +
}

install_telegraf_config() {
    mkdir -p "$TELEGRAF_CONF_DIR"
    temp_file=$(mktemp "$TELEGRAF_CONF_DIR/.90-home-server-monitor.conf.XXXXXX") || fail "Cannot create temporary Telegraf configuration."
    cat > "$temp_file" <<'EOF_TELEGRAF'
# Managed by Home Server Monitor. Local changes will be replaced by updates.

[[inputs.exec]]
  commands = ["/usr/local/bin/hsm-collect storage"]
  interval = "60s"
  timeout = "30s"
  data_format = "influx"

[[inputs.exec]]
  commands = ["/usr/local/bin/hsm-collect raid"]
  interval = "30s"
  timeout = "15s"
  data_format = "influx"

[[inputs.exec]]
  commands = ["/usr/local/bin/hsm-collect ups"]
  interval = "10s"
  timeout = "5s"
  data_format = "influx"

[[inputs.exec]]
  commands = ["/usr/local/bin/hsm-collect proxmox"]
  interval = "30s"
  timeout = "10s"
  data_format = "influx"

[[inputs.exec]]
  commands = ["/usr/local/bin/hsm-collect cooling"]
  interval = "10s"
  timeout = "8s"
  data_format = "influx"
EOF_TELEGRAF
    chmod 0644 "$temp_file"

    # Validate TOML syntax without executing all HSM collectors concurrently.
    # Runtime collector validation is performed sequentially later in this script.
    if ! python3 - "$temp_file" <<'PY'
import sys
import tomllib

path = sys.argv[1]
try:
    with open(path, "rb") as handle:
        config = tomllib.load(handle)
except (OSError, tomllib.TOMLDecodeError) as exc:
    print(f"Invalid managed Telegraf configuration: {exc}", file=sys.stderr)
    raise SystemExit(1)

inputs = config.get("inputs", {})
blocks = inputs.get("exec", []) if isinstance(inputs, dict) else []
if len(blocks) != 5:
    print(f"Expected 5 HSM exec blocks, found {len(blocks)}", file=sys.stderr)
    raise SystemExit(1)

raise SystemExit(0)
PY
    then
        rm -f "$temp_file"
        fail "Managed Telegraf configuration validation failed."
    fi

    if [ -f "$TELEGRAF_MANAGED_CONF" ]; then
        cp -p "$TELEGRAF_MANAGED_CONF" "${TELEGRAF_MANAGED_CONF}.hsm-${HSM_PREVIOUS_VERSION:-unknown}.bak"
    fi
    mv "$temp_file" "$TELEGRAF_MANAGED_CONF"
    chmod 0644 "$TELEGRAF_MANAGED_CONF"
}

remove_legacy_telegraf_blocks() {
    remove_from_file() {
        config_file=$1
        [ -f "$config_file" ] || return 0
        [ "$config_file" = "$TELEGRAF_MANAGED_CONF" ] && return 0

        temp_file=$(mktemp "${config_file}.hsm.XXXXXX") || fail "Cannot create temporary Telegraf file."
        if ! LC_ALL=C awk '
            function flush(    i, legacy) {
                if (!in_exec) return
                legacy = 0
                for (i = 1; i <= count; i++) {
                    if (block[i] !~ /^[[:space:]]*#/ && block[i] ~ /\/opt\/home-server-monitor\/collector[.]py/) legacy = 1
                }
                if (!legacy) {
                    for (i = 1; i <= count; i++) print block[i]
                } else {
                    removed = 1
                }
                for (i = 1; i <= count; i++) delete block[i]
                count = 0
                in_exec = 0
            }
            /^[[:space:]]*\[\[inputs[.]exec\]\][[:space:]]*$/ {
                flush(); in_exec = 1; block[++count] = $0; next
            }
            /^[[:space:]]*\[\[/ {
                flush(); print; next
            }
            {
                if (in_exec) block[++count] = $0
                else print
            }
            END {
                flush()
                if (removed) print "REMOVED=1" > "/dev/stderr"
            }
        ' "$config_file" > "$temp_file" 2> "${temp_file}.status"; then
            rm -f "$temp_file" "${temp_file}.status"
            fail "Cannot process Telegraf configuration: $config_file"
        fi

        if grep -q '^REMOVED=1$' "${temp_file}.status"; then
            backup="${config_file}.hsm-${HSM_PREVIOUS_VERSION:-unknown}.bak"
            [ -e "$backup" ] || cp -p "$config_file" "$backup"
            cat "$temp_file" > "$config_file"
            printf 'Removed legacy HSM collector block from: %s
' "$config_file"
        fi
        rm -f "$temp_file" "${temp_file}.status"
    }

    remove_from_file "$TELEGRAF_MAIN_CONF"
    if [ -d "$TELEGRAF_CONF_DIR" ]; then
        for config_file in "$TELEGRAF_CONF_DIR"/*.conf; do
            [ -e "$config_file" ] || continue
            remove_from_file "$config_file"
        done
    fi
}
install_cooling_helper() {
    mkdir -p "$(dirname "$COOLING_HELPER")"
    install -o root -g root -m 0755 "$INSTALL_DIR/scripts/hsm-x8fan-helper" "$COOLING_HELPER"
    cat > "$COOLING_SUDOERS" <<EOF_SUDOERS
telegraf ALL=(root) NOPASSWD: $COOLING_HELPER
EOF_SUDOERS
    chmod 0440 "$COOLING_SUDOERS"
    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$COOLING_SUDOERS" >/dev/null || fail "Invalid Cooling helper sudoers file."
    fi
}
install_hp_smartarray_helper() {
    mkdir -p "$(dirname "$HP_SMARTARRAY_HELPER")"
    install -o root -g root -m 0755 "$INSTALL_DIR/scripts/hsm-hp-smartarray-helper" "$HP_SMARTARRAY_HELPER"
    cat > "$HP_SMARTARRAY_SUDOERS" <<EOF_SUDOERS
telegraf ALL=(root) NOPASSWD: $HP_SMARTARRAY_HELPER
EOF_SUDOERS
    chmod 0440 "$HP_SMARTARRAY_SUDOERS"
    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$HP_SMARTARRAY_SUDOERS" >/dev/null || fail "Invalid HP Smart Array helper sudoers file."
    fi
}
install_proxmox_helper() {
    mkdir -p "$(dirname "$PROXMOX_HELPER")"
    install -o root -g root -m 0755 "$INSTALL_DIR/scripts/hsm-proxmox-storage-helper" "$PROXMOX_HELPER"
    cat > "$PROXMOX_SUDOERS" <<EOF_SUDOERS
telegraf ALL=(root) NOPASSWD: $PROXMOX_HELPER
EOF_SUDOERS
    chmod 0440 "$PROXMOX_SUDOERS"
    if command -v visudo >/dev/null 2>&1; then
        visudo -cf "$PROXMOX_SUDOERS" >/dev/null || fail "Invalid Proxmox helper sudoers file."
    fi
}

if [ "$(id -u)" -ne 0 ]; then
    fail "This installer must be run as root."
fi

log "Checking requirements..."
check_command python3
check_command smartctl
check_command systemctl
check_command getent
check_command runuser

getent passwd telegraf >/dev/null 2>&1 || fail "The telegraf user does not exist."
getent group telegraf >/dev/null 2>&1 || fail "The telegraf group does not exist."
getent passwd grafana >/dev/null 2>&1 || fail "The grafana user does not exist."
getent group grafana >/dev/null 2>&1 || fail "The grafana group does not exist."
log "[PASS] telegraf user and group"
log "[PASS] grafana user and group"

load_defaults

log "Installing collector..."
mkdir -p "$INSTALL_DIR"
if [ "$SCRIPT_DIR" != "$INSTALL_DIR" ]; then
    cp -a "$SCRIPT_DIR"/. "$INSTALL_DIR"/
fi
rm -rf "$INSTALL_DIR/.git" "$INSTALL_DIR/__pycache__"
find "$INSTALL_DIR" -type d -name __pycache__ -prune -exec rm -rf -- {} +
find "$INSTALL_DIR" -type f -name '*.pyc' -delete
chmod 0755 "$INSTALL_DIR/collector.py" "$INSTALL_DIR/hsm.py" "$INSTALL_DIR/hsm_collect.py" "$INSTALL_DIR/install.sh" "$INSTALL_DIR/update.sh"
ln -sf "$INSTALL_DIR/hsm.py" /usr/local/bin/hsm
ln -sf "$INSTALL_DIR/hsm_collect.py" /usr/local/bin/hsm-collect
install_proxmox_helper
install_hp_smartarray_helper
install_cooling_helper

ensure_defaults_file
load_defaults

mkdir -p "$CACHE_DIR"
chown telegraf:telegraf "$CACHE_DIR"
chmod 0750 "$CACHE_DIR"

log "Installing Telegraf configuration..."
remove_legacy_telegraf_blocks
install_telegraf_config

log "Detecting Grafana InfluxDB datasource..."
DATASOURCE_UID=$(detect_influxdb_uid) || fail "No InfluxDB datasource was found. Set HSM_GRAFANA_DATASOURCE_UID in $DEFAULTS_FILE and run install.sh again."
log "[PASS] InfluxDB datasource UID: $DATASOURCE_UID"

log "Installing Grafana dashboards..."
mkdir -p "$(dirname "$GRAFANA_PROVISIONING_FILE")"
cp "$INSTALL_DIR/grafana/provisioning/dashboards/home-server-monitor.yaml" "$GRAFANA_PROVISIONING_FILE"
chmod 0644 "$GRAFANA_PROVISIONING_FILE"
render_dashboards "$DATASOURCE_UID"

log "Validating collector..."
for module in storage raid ups proxmox cooling; do
    collector_rc=0
    runuser -u telegraf -- /usr/local/bin/hsm-collect "$module" >"/tmp/home-server-monitor-${module}.metrics" 2>"/tmp/home-server-monitor-${module}.log" || collector_rc=$?

    if [ "$module" = "cooling" ]; then
        case "${HSM_COOLING_REQUIRED:-false}" in
            1|true|TRUE|yes|YES|on|ON) cooling_required=true ;;
            *) cooling_required=false ;;
        esac
        if [ "$cooling_required" = false ] && { [ "$collector_rc" -ne 0 ] || [ ! -s "/tmp/home-server-monitor-${module}.metrics" ]; }; then
            cat "/tmp/home-server-monitor-${module}.log" >&2 || true
            log "[WARN] Optional Cooling collector is currently unavailable; installation will continue."
            continue
        fi
    fi

    if [ "$collector_rc" -ne 0 ]; then
        cat "/tmp/home-server-monitor-${module}.log" >&2 || true
        fail "Collector validation failed for module: $module"
    fi
    [ -s "/tmp/home-server-monitor-${module}.metrics" ] || fail "Collector returned no metrics for module: $module"
done
log "[PASS] Modular collector output"

log "Restarting services..."
systemctl restart telegraf
systemctl restart grafana-server
systemctl is-active --quiet telegraf || fail "Telegraf did not start."
systemctl is-active --quiet grafana-server || fail "Grafana did not start."
log "[PASS] Telegraf"
log "[PASS] Grafana"

cat <<EOF_DONE

Installation complete.

Grafana folder: Home Server Monitor
Dashboards: Home, Storage, RAID, UPS, Proxmox, Cooling
Datasource UID: $DATASOURCE_UID
Collectors: /usr/local/bin/hsm-collect storage|raid|ups|proxmox|cooling
Telegraf config: $TELEGRAF_MANAGED_CONF

Open Grafana and select Dashboards -> Home Server Monitor.
EOF_DONE
