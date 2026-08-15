#!/usr/bin/env python3
"""Home Server Monitor administration CLI."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
import tempfile
from pathlib import Path

INSTALL_DIR = Path(os.environ.get("HSM_INSTALL_DIR", "/opt/home-server-monitor"))
DEFAULTS_FILE = Path(os.environ.get("HSM_ENV_FILE", "/etc/default/home-server-monitor"))
TELEGRAF_CONF = Path("/etc/telegraf/telegraf.d/home-server-monitor.conf")
TELEGRAF_ROOT = Path(os.environ.get("HSM_TELEGRAF_ROOT", "/etc/telegraf"))
GRAFANA_DB = Path("/var/lib/grafana/grafana.db")
GRAFANA_DASHBOARD_DIR = Path("/var/lib/grafana/dashboards/home-server-monitor")
EXPECTED_DASHBOARDS = ("Home.json", "Storage.json", "RAID.json", "UPS.json", "Proxmox.json", "Cooling.json")
MANAGED_TELEGRAF_CONF = Path("/etc/telegraf/telegraf.d/90-home-server-monitor.conf")
INFLUX_DATABASE_FALLBACK = os.environ.get("HSM_INFLUX_DATABASE", "raid")
HEALTH_ENGINE_VERSION = "1.0"
CLI_VERSION = "2.2"
JSON_API_VERSION = "1.0"
CORE_VERSION = "2.0"

COLLECTOR_MANIFESTS = {
    "storage": {"interval": 60, "timeout": 20, "measurements": ("storage_inventory", "storage_health", "storage_status")},
    "raid": {"interval": 30, "timeout": 15, "measurements": ("raid_controller_status", "raid_array_status", "raid_drive_status")},
    "ups": {"interval": 10, "timeout": 5, "measurements": ("ups_status",)},
    "proxmox": {"interval": 30, "timeout": 10, "measurements": ("proxmox_host_info", "proxmox_host_status", "proxmox_storage")},
    "cooling": {"interval": 10, "timeout": 8, "measurements": ("cooling_status", "cooling_fan")},
}
SENSITIVE_MARKERS = ("PASSWORD", "TOKEN", "SECRET", "API_KEY", "AUTH")


MEASUREMENT_FRESHNESS = {
    "storage_status": {"module": "storage", "max_age": 180},
    "raid_controller_status": {"module": "raid", "max_age": 90},
    "ups_status": {"module": "ups", "max_age": 30},
    "proxmox_host_status": {"module": "proxmox", "max_age": 90},
    "proxmox_storage": {"module": "proxmox", "max_age": 90},
}

DASHBOARD_LABELS = {
    "Home.json": "Overview",
    "Storage.json": "Storage",
    "RAID.json": "RAID",
    "UPS.json": "UPS",
    "Proxmox.json": "Proxmox",
}


def version() -> str:
    try:
        return (INSTALL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def run(command: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def service_active(name: str) -> bool:
    result = run(["systemctl", "is-active", "--quiet", name], timeout=10)
    return result.returncode == 0


def print_check(level: str, message: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    print(f"[{level}] {message}{suffix}")


def read_defaults() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = DEFAULTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def redact_defaults() -> str:
    try:
        lines = DEFAULTS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return f"Unable to read {DEFAULTS_FILE}: {exc}\n"
    output: list[str] = []
    for raw in lines:
        if "=" not in raw or raw.lstrip().startswith("#"):
            output.append(raw)
            continue
        key, _ = raw.split("=", 1)
        if any(marker in key.upper() for marker in SENSITIVE_MARKERS):
            output.append(f"{key}=<redacted>")
        else:
            output.append(raw)
    return "\n".join(output) + "\n"


def grafana_datasource_uid() -> str | None:
    if not GRAFANA_DB.is_file():
        return None
    try:
        connection = sqlite3.connect(f"file:{GRAFANA_DB}?mode=ro", uri=True)
        row = connection.execute(
            "SELECT uid FROM data_source WHERE type = 'influxdb' ORDER BY id LIMIT 1"
        ).fetchone()
        connection.close()
    except sqlite3.Error:
        return None
    return str(row[0]) if row and row[0] else None


def grafana_influx_database() -> str:
    """Return the configured Grafana InfluxDB database, with a safe fallback."""
    if GRAFANA_DB.is_file():
        try:
            connection = sqlite3.connect(f"file:{GRAFANA_DB}?mode=ro", uri=True)
            row = connection.execute(
                "SELECT database FROM data_source WHERE type = 'influxdb' ORDER BY id LIMIT 1"
            ).fetchone()
            connection.close()
            if row and row[0]:
                return str(row[0])
        except sqlite3.Error:
            pass
    return INFLUX_DATABASE_FALLBACK


def parse_rfc3339(value: str) -> dt.datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def measurement_last_update(measurement: str, database: str | None = None) -> dict[str, object]:
    """Return the newest point timestamp and age for one measurement."""
    database = database or grafana_influx_database()
    command = [
        "influx", "-database", database, "-format", "csv",
        "-precision", "rfc3339", "-execute",
        f'SELECT * FROM "{measurement}" ORDER BY time DESC LIMIT 1',
    ]
    try:
        result = run(command, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"measurement": measurement, "database": database, "available": False, "detail": str(exc)}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"influx exited with {result.returncode}"
        return {"measurement": measurement, "database": database, "available": False, "detail": detail}
    try:
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
    except csv.Error as exc:
        return {"measurement": measurement, "database": database, "available": False, "detail": str(exc)}
    row = next((item for item in rows if item.get("time")), None)
    if row is None:
        return {"measurement": measurement, "database": database, "available": False, "detail": "no points found"}
    try:
        timestamp = parse_rfc3339(str(row["time"]))
    except (ValueError, TypeError) as exc:
        return {"measurement": measurement, "database": database, "available": False, "detail": f"invalid timestamp: {exc}"}
    now = dt.datetime.now(dt.timezone.utc)
    age = max(0.0, (now - timestamp).total_seconds())
    return {
        "measurement": measurement, "database": database, "available": True,
        "timestamp": timestamp.isoformat(), "age_seconds": round(age, 1), "detail": "",
    }


def measurement_freshness() -> list[dict[str, object]]:
    database = grafana_influx_database()
    results: list[dict[str, object]] = []
    for measurement, policy in MEASUREMENT_FRESHNESS.items():
        item = measurement_last_update(measurement, database)
        item["module"] = policy["module"]
        item["max_age_seconds"] = policy["max_age"]
        item["fresh"] = bool(item.get("available")) and float(item.get("age_seconds", 1e12)) <= float(policy["max_age"])
        results.append(item)
    return results


def recent_hsm_telegraf_errors(since: str = "24 hours ago") -> dict[str, object]:
    """Inspect a bounded Telegraf journal window for HSM modular collector errors."""
    try:
        result = run(
            [
                "journalctl",
                "-u",
                "telegraf",
                "--since",
                since,
                "-n",
                "500",
                "--no-pager",
            ],
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "errors": [], "detail": str(exc)}

    if result.returncode != 0:
        return {
            "available": False,
            "errors": [],
            "detail": (result.stderr or result.stdout).strip(),
        }

    errors = []

    for line in result.stdout.splitlines():
        lowered = line.lower()

        if "hsm-collect" not in lowered:
            continue

        if (
            "timed out" in lowered
            or "error in plugin" in lowered
            or "failed" in lowered
        ):
            errors.append(line.strip())

    return {"available": True, "errors": errors, "detail": ""}


def dashboard_checks() -> list[dict[str, object]]:
    return [
        {
            "file": filename,
            "name": DASHBOARD_LABELS.get(filename, filename.removesuffix(".json")),
            "present": (GRAFANA_DASHBOARD_DIR / filename).is_file(),
        }
        for filename in EXPECTED_DASHBOARDS
    ]



def find_telegraf_collector_configs(root: Path | None = None) -> list[Path]:
    """Return readable Telegraf config files that invoke the HSM collector."""
    root = root or TELEGRAF_ROOT
    candidates: list[Path] = []
    main = root / "telegraf.conf"
    if main.is_file():
        candidates.append(main)
    config_dir = root / "telegraf.d"
    if config_dir.is_dir():
        candidates.extend(sorted(config_dir.rglob("*.conf")))

    matches: list[Path] = []
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        normalized = text.replace("\\", "/")
        if "collector.py" in normalized and (
            "home-server-monitor" in normalized or str(INSTALL_DIR) in normalized
        ):
            matches.append(path)
    return matches


def telegraf_config_detail(paths: list[Path]) -> str:
    if not paths:
        return "collector command not found"
    if len(paths) == 1:
        return str(paths[0])
    return f"{len(paths)} files: " + ", ".join(str(path) for path in paths)

def collector_command() -> list[str]:
    return [sys.executable, str(INSTALL_DIR / "collector.py")]


def modular_collector_command(module: str) -> list[str]:
    return [str(Path("/usr/local/bin/hsm-collect")), module]


def benchmark_collectors() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for module, manifest in COLLECTOR_MANIFESTS.items():
        started = time.monotonic()
        try:
            completed = run(modular_collector_command(module), timeout=int(manifest["timeout"]))
            elapsed = time.monotonic() - started
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            results.append({
                "module": module,
                "status": "PASS" if completed.returncode == 0 and lines else "FAIL",
                "runtime_seconds": round(elapsed, 3),
                "metrics": len(lines),
                "returncode": completed.returncode,
                "detail": (completed.stderr.strip().splitlines() or [""])[-1],
                "timeout_seconds": manifest["timeout"],
                "interval_seconds": manifest["interval"],
                "metrics_per_second": round(len(lines) / elapsed, 2) if elapsed > 0 else 0.0,
                "slow": elapsed >= float(manifest["timeout"]) * 0.7,
            })
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append({
                "module": module, "status": "FAIL", "runtime_seconds": round(time.monotonic()-started, 3),
                "metrics": 0, "returncode": 124, "detail": str(exc),
                "timeout_seconds": manifest["timeout"], "interval_seconds": manifest["interval"],
                "metrics_per_second": 0.0, "slow": False,
            })
    return results


def inspect_managed_telegraf_config() -> dict[str, object]:
    data = {"path": str(MANAGED_TELEGRAF_CONF), "exists": MANAGED_TELEGRAF_CONF.is_file(), "modules": {}, "duplicates": [], "legacy_blocks": []}
    if not MANAGED_TELEGRAF_CONF.is_file():
        return data
    text = MANAGED_TELEGRAF_CONF.read_text(encoding="utf-8", errors="replace")
    for module, manifest in COLLECTOR_MANIFESTS.items():
        count = text.count(f"hsm-collect {module}")
        data["modules"][module] = {"count": count, "interval": manifest["interval"], "timeout": manifest["timeout"]}
        if count != 1:
            data["duplicates"].append(module)
    candidates = [TELEGRAF_ROOT / "telegraf.conf"]
    config_dir = TELEGRAF_ROOT / "telegraf.d"
    if config_dir.is_dir():
        candidates.extend(sorted(config_dir.glob("*.conf")))
    for path in candidates:
        try:
            t = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "collector.py" in t and "home-server-monitor" in t:
            data["legacy_blocks"].append(str(path))
    return data


def benchmark(as_json: bool = False) -> int:
    results = benchmark_collectors()
    total_runtime = sum(float(item["runtime_seconds"]) for item in results)
    total_metrics = sum(int(item["metrics"]) for item in results)
    payload = {
        "version": version(),
        "collectors": results,
        "summary": {
            "runtime_seconds": round(total_runtime, 3),
            "metrics": total_metrics,
            "metrics_per_second": round(total_metrics / total_runtime, 2) if total_runtime > 0 else 0.0,
        },
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Home Server Monitor Benchmark v{version()}")
        print("=" * 52)
        for item in results:
            status = "WARN" if item["status"] == "PASS" and item.get("slow") else item["status"]
            print(
                f"{str(item['module']).capitalize():<10} {status:<5} "
                f"{item['runtime_seconds']:>6.3f}s  {item['metrics']:>2} metrics  "
                f"{item['metrics_per_second']:>6.2f} metrics/s"
            )
        print("-" * 52)
        print(
            f"Total: {total_runtime:.3f}s, {total_metrics} metrics, "
            f"{payload['summary']['metrics_per_second']:.2f} metrics/s"
        )
    return 1 if any(item["status"] != "PASS" for item in results) else 0


def doctor(quiet: bool = False, as_json: bool = False) -> int:
    checks: list[dict[str, object]] = []
    def add(ok: bool, name: str, detail: str = "", warning: bool = False, section: str = "General") -> None:
        checks.append({"level": "PASS" if ok else ("WARN" if warning else "FAIL"), "name": name, "detail": detail, "section": section})

    add(sys.version_info >= (3, 10), "Python version", sys.version.split()[0])
    add(INSTALL_DIR.is_dir(), "Installation directory", str(INSTALL_DIR))
    add(DEFAULTS_FILE.is_file(), "Configuration file", str(DEFAULTS_FILE))
    add((INSTALL_DIR / "hsm_collect.py").is_file(), "Modular collector entry point")
    add(shutil.which("hsm-collect") is not None, "hsm-collect command")

    config = inspect_managed_telegraf_config()
    add(bool(config["exists"]), "Managed Telegraf configuration", str(config["path"]), section="Telegraf")
    add(not config["duplicates"], "Exactly one exec block per module", ", ".join(config["duplicates"]) if config["duplicates"] else f"{len(COLLECTOR_MANIFESTS)} modules", section="Telegraf")
    add(not config["legacy_blocks"], "Legacy monolithic collector disabled", ", ".join(config["legacy_blocks"]), section="Telegraf")

    defaults = read_defaults()
    ssacli_enabled = defaults.get("HSM_RAID_SSACLI_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }
    ssacli_helper = Path(
        defaults.get("HSM_SSACLI_HELPER", "/usr/local/libexec/hsm-hp-smartarray-helper")
    )

    if ssacli_enabled:
        helper_present = ssacli_helper.is_file()
        add(helper_present, "HP Smart Array helper", str(ssacli_helper), section="RAID")
        ssacli_present = Path("/usr/sbin/ssacli").is_file()
        add(ssacli_present, "HP ssacli", "/usr/sbin/ssacli", section="RAID")
        if helper_present and ssacli_present:
            try:
                hp_result = run(
                    ["sudo", "-u", "telegraf", "sudo", "-n", str(ssacli_helper)],
                    timeout=10,
                )
                hp_ok = hp_result.returncode == 0 and "Smart Array" in hp_result.stdout
                hp_detail = (
                    "telegraf read-only access OK"
                    if hp_ok
                    else (hp_result.stderr or hp_result.stdout).strip()
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                hp_ok = False
                hp_detail = str(exc)
            add(hp_ok, "HP Smart Array access", hp_detail, section="RAID")
    for item in benchmark_collectors():
        detail = f"{item['runtime_seconds']:.3f}s, {item['metrics']} metrics, timeout {item['timeout_seconds']}s"
        if item["detail"] and item["status"] != "PASS":
            detail += f" - {item['detail']}"
        add(item["status"] == "PASS", f"Collector: {item['module']}", detail, section="Collectors")

    for service in ("telegraf", "influxdb", "grafana-server"):
        add(service_active(service), f"Service active: {service}", section="Services")
    freshness = measurement_freshness()
    for item in freshness:
        if item.get("fresh"):
            detail = f"updated {float(item['age_seconds']):.0f}s ago (max {item['max_age_seconds']}s)"
            add(True, str(item["measurement"]), detail, section="Influx Measurements")
        else:
            detail = str(item.get("detail") or f"stale: {item.get('age_seconds', 'unknown')}s")
            add(False, str(item["measurement"]), detail, section="Influx Measurements")

    uid = grafana_datasource_uid()
    add(uid is not None, "Grafana InfluxDB datasource", uid or "not found", section="Grafana")
    for dashboard in dashboard_checks():
        add(bool(dashboard["present"]), f"Dashboard: {dashboard['name']}", str(GRAFANA_DASHBOARD_DIR / str(dashboard["file"])), section="Grafana Dashboards")

    failures = sum(item["level"] == "FAIL" for item in checks)
    warnings = sum(item["level"] == "WARN" for item in checks)
    payload = {"version": version(), "checks": checks, "summary": {"pass": sum(item["level"] == "PASS" for item in checks), "warn": warnings, "fail": failures}, "overall": "UNHEALTHY" if failures else ("HEALTHY_WITH_WARNINGS" if warnings else "HEALTHY")}
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif not quiet:
        print(f"Home Server Monitor Doctor v{version()}")
        print("=" * 34)
        current = None
        for item in checks:
            if item["section"] != current:
                if current is not None:
                    print()
                print(item["section"])
                print("-" * len(str(item["section"])))
                current = item["section"]
            print_check(str(item["level"]), str(item["name"]), str(item["detail"]))
        print("\nSummary\n-------")
        print(f"PASS: {payload['summary']['pass']}")
        print(f"WARN: {warnings}")
        print(f"FAIL: {failures}\n")
        print(f"Overall: {payload['overall']}")
    return 1 if failures else 0

def _collector_snapshot() -> tuple[list, int, int]:
    runs = _runtime_registry().manager().collect()
    metric_count = sum(len(run.result.metrics) for run in runs if run.result)
    capability_count = sum(
        1
        for run in runs
        for capability in run.discovery.capabilities
        if capability.available and run.discovery.ready
    )
    return runs, metric_count, capability_count


def _dashboard_count() -> int:
    return sum((GRAFANA_DASHBOARD_DIR / name).is_file() for name in EXPECTED_DASHBOARDS)


def status(as_json: bool = False) -> int:
    from core.health import Severity, summarize_health

    runs, metric_count, capability_count = _collector_snapshot()
    health = summarize_health(runs)
    services = {
        name: service_active(name)
        for name in ("telegraf", "influxdb", "grafana-server")
    }
    data = {
        "version": version(),
        "health": health.as_dict(),
        "collectors": len(runs),
        "metrics": metric_count,
        "capabilities": capability_count,
        "dashboards": _dashboard_count(),
        "dashboards_expected": len(EXPECTED_DASHBOARDS),
        "grafana_datasource_uid": grafana_datasource_uid(),
        "services": services,
    }
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0 if health.severity in {Severity.OK, Severity.WARNING} else 1

    print(f"Home Server Monitor v{data['version']}")
    print("=" * 40)
    print(f"Overall: {health.status.upper()} ({health.score}/100)")
    if health.primary_finding is not None:
        finding = health.primary_finding
        subject = f"{finding.subject}: " if finding.subject else ""
        print(f"Primary: {finding.domain.upper()} - {subject}{finding.reason} (impact {finding.impact})")
    print(
        "Findings: "
        f"CRITICAL {health.critical_count} | HIGH {health.high_count} | "
        f"WARNING {health.warning_count} | UNKNOWN {health.unknown_count}"
    )
    print()
    display_names = {"storage": "Storage", "raid": "RAID", "ups": "UPS", "proxmox": "Proxmox"}
    for domain in health.domains:
        name = display_names.get(domain.name, domain.name.capitalize())
        print(f"{name:<10} {domain.severity.label:<8} {domain.score:>3}/100")
        if domain.findings:
            for finding in domain.findings:
                subject = f"{finding.subject}: " if finding.subject else ""
                print(f"  - [{finding.severity.label}] {subject}{finding.reason} (impact {finding.impact})")
        else:
            print("  - No health issues detected")
        print()

    print(f"Collectors: {data['collectors']} | Metrics: {metric_count} | Capabilities: {capability_count}")
    inactive = [name for name, active in services.items() if not active]
    if inactive:
        print("Inactive services: " + ", ".join(inactive))
    return 0 if health.severity in {Severity.OK, Severity.WARNING} and not inactive else 1



def verify(as_json: bool = False) -> int:
    freshness = measurement_freshness()
    journal = recent_hsm_telegraf_errors()
    services = {name: service_active(name) for name in ("telegraf", "influxdb", "grafana-server")}
    dashboards = dashboard_checks()
    checks: list[dict[str, object]] = []
    for item in freshness:
        checks.append({
            "name": str(item["module"]).capitalize(),
            "measurement": item["measurement"],
            "status": "PASS" if item.get("fresh") else "FAIL",
            "age_seconds": item.get("age_seconds"),
            "max_age_seconds": item["max_age_seconds"],
            "detail": item.get("detail", ""),
        })
    failures = [item for item in checks if item["status"] != "PASS"]
    service_failures = [name for name, active in services.items() if not active]
    dashboard_failures = [item["name"] for item in dashboards if not item["present"]]
    journal_errors = list(journal.get("errors", []))
    overall = "PASS"
    if failures or service_failures or dashboard_failures or journal_errors:
        overall = "FAIL"
    elif not journal.get("available"):
        overall = "WARN"
    payload = {
        "version": version(), "overall": overall, "measurements": checks,
        "services": services, "dashboards": dashboards, "journal": journal,
    }
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Home Server Monitor Verify v{version()}")
        print("=" * 40)
        print("Measurements")
        print("------------")
        for item in checks:
            age = "unknown" if item["age_seconds"] is None else f"{float(item['age_seconds']):.0f}s ago"
            print(f"{item['name']:<10} {item['status']:<5} {str(item['measurement']):<24} {age}")
        print("\nServices\n--------")
        for name, active in services.items():
            print(f"{name:<16} {'PASS' if active else 'FAIL'}")
        print("\nGrafana dashboards\n------------------")
        for item in dashboards:
            print(f"{str(item['name']):<16} {'PASS' if item['present'] else 'FAIL'}")
        print("\nRecent HSM collector errors\n---------------------------")
        if journal_errors:
            print("FAIL")
            for line in journal_errors[-10:]:
                print(f"  {line}")
        elif journal.get("available"):
            print("PASS - no HSM collector timeouts or plugin failures in the last 24 hours")
        else:
            print(f"WARN - journal unavailable: {journal.get('detail', '')}")
        print(f"\nOverall: {overall}")
    return 1 if overall == "FAIL" else 0

def info(as_json: bool = False) -> int:
    runs = _runtime_registry().manager().discover()
    domains = sorted({run.discovery.domain for run in runs})
    capability_count = sum(
        1 for run in runs for capability in run.discovery.capabilities
        if capability.available and run.discovery.ready
    )
    measurements = sorted({name for manifest in COLLECTOR_MANIFESTS.values() for name in manifest["measurements"]})
    data = {
        "name": "Home Server Monitor",
        "version": version(),
        "core_version": CORE_VERSION,
        "health_engine_version": HEALTH_ENGINE_VERSION,
        "cli_version": CLI_VERSION,
        "json_api_version": JSON_API_VERSION,
        "collector_api": "1.0",
        "metrics_api": "1.0",
        "python": sys.version.split()[0],
        "install_directory": str(INSTALL_DIR),
        "configuration_file": str(DEFAULTS_FILE),
        "telegraf_configuration": str(MANAGED_TELEGRAF_CONF),
        "collectors": len(runs),
        "capabilities": capability_count,
        "measurements": len(measurements),
        "measurement_names": measurements,
        "dashboards": _dashboard_count(),
        "domains": domains,
        "plugins": 0,
    }
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0

    print(data["name"])
    print("=" * len(data["name"]))
    print(f"Version:          {data['version']}")
    print(f"Core:             {data['core_version']}")
    print(f"Health Engine:    {data['health_engine_version']}")
    print(f"CLI:              {data['cli_version']}")
    print(f"JSON API:         {data['json_api_version']}")
    print(f"Python:           {data['python']}")
    print(f"Collectors:       {data['collectors']}")
    print(f"Capabilities:     {data['capabilities']}")
    print(f"Measurements:     {data['measurements']}")
    print(f"Dashboards:       {data['dashboards']}/{len(EXPECTED_DASHBOARDS)}")
    print(f"Domains:          {', '.join(domains) if domains else 'none'}")
    print("\nInstallation\n------------")
    print(data["install_directory"])
    print("\nConfiguration\n-------------")
    print(data["configuration_file"])
    print(data["telegraf_configuration"])
    return 0

def self_test() -> int:
    tests_dir = INSTALL_DIR / "tests"
    if not tests_dir.is_dir():
        print(f"Tests directory not found: {tests_dir}", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(tests_dir), "-p", "test_*.py", "-v"],
        cwd=str(INSTALL_DIR),
        check=False,
    )
    return result.returncode


def write_command_output(path: Path, command: list[str], timeout: int = 30) -> None:
    try:
        result = run(command, timeout=timeout)
        content = "$ " + " ".join(command) + "\n\n" + result.stdout
        if result.stderr:
            content += "\n--- stderr ---\n" + result.stderr
        content += f"\n--- exit code: {result.returncode} ---\n"
    except (OSError, subprocess.TimeoutExpired) as exc:
        content = f"Command failed: {exc}\n"
    path.write_text(content, encoding="utf-8")


def report(output: str | None) -> int:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = Path(output or f"hsm-report-{timestamp}.tar.gz").expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="hsm-report-") as temp_name:
        root = Path(temp_name) / f"hsm-report-{timestamp}"
        root.mkdir()
        (root / "version.txt").write_text(version() + "\n", encoding="utf-8")
        (root / "configuration-redacted.txt").write_text(redact_defaults(), encoding="utf-8")
        write_command_output(root / "system.txt", ["uname", "-a"])
        write_command_output(root / "services.txt", ["systemctl", "--no-pager", "--full", "status", "telegraf", "influxdb", "grafana-server"])
        write_command_output(root / "telegraf-version.txt", ["telegraf", "--version"])
        write_command_output(root / "grafana-version.txt", ["grafana-server", "-v"])
        write_command_output(root / "python-version.txt", [sys.executable, "--version"])
        write_command_output(root / "journal-telegraf.txt", ["journalctl", "-u", "telegraf", "-n", "200", "--no-pager"])
        write_command_output(root / "collector.txt", collector_command(), timeout=45)
        write_command_output(root / "lsblk.txt", ["lsblk", "-d", "-o", "NAME,MODEL,SERIAL,TRAN,RM,HOTPLUG,ROTA,TYPE,SIZE"])
        configs = find_telegraf_collector_configs()
        (root / "telegraf-config-locations.txt").write_text("\n".join(str(path) for path in configs) + ("\n" if configs else "collector command not found\n"), encoding="utf-8")
        for index, config_path in enumerate(configs, start=1):
            try:
                shutil.copy2(config_path, root / f"telegraf-config-{index}.conf")
            except OSError:
                pass
        defaults = read_defaults()
        storcli = defaults.get("HSM_STORCLI_BINARY", "storcli")
        if shutil.which(storcli) or Path(storcli).is_file():
            write_command_output(root / "storcli.txt", [storcli, "/call", "show", "all", "J"], timeout=60)
        doctor_path = root / "doctor.txt"
        previous = sys.stdout
        try:
            with doctor_path.open("w", encoding="utf-8") as handle:
                sys.stdout = handle
                doctor()
        finally:
            sys.stdout = previous
        with tarfile.open(destination, "w:gz") as archive:
            archive.add(root, arcname=root.name)
    print(f"Report created: {destination}")
    print("Sensitive configuration values were redacted.")
    return 0



def _runtime_registry():
    from collector import build_provider_registry
    return build_provider_registry()


def collectors(verbose: bool = False, as_json: bool = False) -> int:
    runs = _runtime_registry().manager().discover()
    data = []
    for run in runs:
        data.append({
            "name": run.provider.name,
            "version": str(run.provider.version),
            "domain": run.discovery.domain,
            "status": run.discovery.availability.value,
            "detail": run.discovery.detail,
            "dependencies": list(run.provider.dependencies),
            "capabilities": [
                {
                    "name": capability.name,
                    "available": capability.available and run.discovery.ready,
                    "detail": capability.detail,
                }
                for capability in run.discovery.capabilities
            ],
        })
    if as_json:
        print(json.dumps({"collectors": data}, indent=2, sort_keys=True))
        return 0

    print("Loaded Collectors")
    print("-----------------")
    domain_order = {"hardware": 0, "platform": 1, "virtualization": 2, "services": 3}
    collector_order = {"storage": 0, "raid": 1, "ups": 2, "proxmox": 0}
    data.sort(key=lambda item: (domain_order.get(item["domain"], 99), collector_order.get(item["name"], 99), item["name"]))
    current = None
    for item in data:
        domain = item["domain"].title()
        if domain != current:
            if current is not None:
                print()
            print(domain)
            current = domain
        detail = f" - {item['detail']}" if item["detail"] else ""
        print(f"  {item['name']:<16} {item['status'].upper()}{detail}")
        if verbose:
            print(f"    Version:      {item['version']}")
            dependencies = ", ".join(item["dependencies"]) or "none"
            print(f"    Dependencies: {dependencies}")
            names = ", ".join(cap["name"] for cap in item["capabilities"]) or "none"
            print(f"    Capabilities: {names}")
    return 0


def capabilities(verbose: bool = False, as_json: bool = False) -> int:
    runs = _runtime_registry().manager().discover()
    items = []
    for run in runs:
        for capability in run.discovery.capabilities:
            items.append({
                "name": capability.name,
                "domain": run.discovery.domain,
                "collector": run.provider.name,
                "available": capability.available and run.discovery.ready,
                "detail": capability.detail,
            })
    if as_json:
        print(json.dumps({"capabilities": items}, indent=2, sort_keys=True))
        return 0

    print("Detected Capabilities")
    print("---------------------")
    current = None
    for item in items:
        domain = item["domain"].title()
        if domain != current:
            print()
            print(domain)
            current = domain
        marker = "+" if item["available"] else "-"
        suffix = f" - {item['detail']}" if item["detail"] else ""
        print(f"  [{marker}] {item['name']}{suffix}")
        if verbose:
            print(f"      Collector: {item['collector']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="hsm", description="Home Server Monitor administration tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version", help="Show installed version")

    status_parser = subparsers.add_parser("status", help="Show overall runtime status")
    status_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    info_parser = subparsers.add_parser("info", help="Show HSM build and runtime information")
    info_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    doctor_parser = subparsers.add_parser("doctor", help="Run installation and runtime diagnostics")
    doctor_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    benchmark_parser = subparsers.add_parser("benchmark", help="Measure each modular collector")
    benchmark_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    verify_parser = subparsers.add_parser("verify", help="Verify live metric delivery and HSM runtime health")
    verify_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    subparsers.add_parser("self-test", help="Run the bundled regression tests")

    collectors_parser = subparsers.add_parser("collectors", help="Show loaded collectors and runtime availability")
    collectors_parser.add_argument("--verbose", action="store_true", help="Show versions, dependencies, and capabilities")
    collectors_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    capabilities_parser = subparsers.add_parser("capabilities", help="Show detected capabilities grouped by domain")
    capabilities_parser.add_argument("--verbose", action="store_true", help="Show the collector responsible for each capability")
    capabilities_parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    report_parser = subparsers.add_parser("report", help="Create a redacted diagnostic archive")
    report_parser.add_argument("--output", help="Output archive path")
    args = parser.parse_args()
    if args.command == "version":
        print(version())
        return 0
    if args.command == "status":
        return status(args.json)
    if args.command == "info":
        return info(args.json)
    if args.command == "doctor":
        return doctor(as_json=args.json)
    if args.command == "benchmark":
        return benchmark(args.json)
    if args.command == "verify":
        return verify(args.json)
    if args.command == "self-test":
        return self_test()
    if args.command == "collectors":
        return collectors(args.verbose, args.json)
    if args.command == "capabilities":
        return capabilities(args.verbose, args.json)
    if args.command == "report":
        return report(args.output)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
