# Home Server Monitor 7.10.0-alpha.8

- Hides Grafana dashboard variable controls from the top bar on all HSM pages while keeping their saved values active internally, stabilizing the page-navigation button position.
- Improves Home readability for Proxmox Storage Attention and RAID mode with short aliases and explicit text sizes.
- Updates RAID unit-test fixtures for the new serial-based SMART enrichment lookup.
- Adds direct SMART diagnostics to OS-visible MegaRAID JBOD disks using stable serial-number matching rather than /dev/sdX identity.
- RAID physical drives now expose reallocated, pending, offline-uncorrectable and CRC counters alongside StorCLI Media/Other/Predictive counters.
- RAID drive health follows the same SMART warning/critical rules used by direct Storage disks.
- RAID dashboard physical-drive tables show both MegaRAID controller counters and physical-disk SMART counters.
# Home Server Monitor 7.10.0-alpha.7

- Detects partial X8DTN+-F SMBus/BMC sensor collapse and escalates Cooling hardware failure to CRITICAL when System Temp and the active fan channels disappear.
- Exposes stale Cooling status while preserving sparse/event-driven hardware polling.
- Makes Current Fans usable in short Grafana windows with a 15-minute real-sample lookback; Fan RPM history still uses only real hardware samples.
- Improves Home readability for Proxmox Storage Attention and RAID mode.
# Home Server Monitor 7.10.0-alpha.6

- Renamed the RAID drive-count Home card so it is distinct from RAID physical health.
- Increased the two bottom Home tables to use the remaining 1080p viewport height; additional rows continue to use in-panel scrolling.
- Home `Proxmox Storage Health` now reflects the worst current storage state from the latest samples instead of the historical maximum over the selected Grafana time range.
- Home `Proxmox Storage Attention` also uses fresh current samples, so a resolved storage-capacity incident clears immediately.
- Compacted Home dashboard panel heights and row spacing for a denser 1080p layout.
- Added a compact Cooling summary to Home: mode, control source, PWM2, CPU Tmax, System Temp, and HDD Tmax.
- Added a Home RAID physical-drive table with current health, temperature, media errors, other errors, and predictive failures.
- Corrected the RAID physical-health / drive-count summary labels when their query semantics were reversed.
# Home Server Monitor 7.10.0-alpha.5

- Storage/RAID ownership now uses physical serial identity rather than Linux /dev/sdX names or the MegaRAID control-device path, so disk add/remove/reordering and sdX renames do not change module ownership.

- Storage no longer treats the legacy `HSM_MEGARAID_CONTROL_DEVICE` path as RAID-owned when MegaRAID SMART is disabled, preventing a real direct disk such as `/dev/sda` from losing SMART data.
- When StorCLI reports `Drive Temperature = N/A`, RAID may use a temperature-only `smartctl -j -A` fallback on the matching OS-visible disk by serial; the disk still remains owned exclusively by RAID.

- Storage now excludes MegaRAID-owned JBOD disks by StorCLI serial before ATA SMART collection and no longer runs `smartctl -d megaraid` from the Storage module.
- RAID retries a per-slot StorCLI detail query only when the bulk drive detail omits temperature, preserving HDD temperature coverage for Cooling without using Storage SMART as a fallback.

- Added direct-attached MegaRAID JBOD support for passive backplanes that expose `:slot` without an enclosure ID.
- Storage MegaRAID discovery now falls back to direct-attached slots too, preventing RAID-owned JBOD disks from being SMART-polled twice as ordinary Storage disks.
- StorCLI now falls back from `/call /eall /sall show all` to per-controller `/cX /sall show all` only when enclosure detail is unavailable.
- Direct-attached MegaRAID drives now retain slot, DID, model, serial number and temperature in RAID metrics.
- Media, other-error and predictive-failure counters now fall back to detailed StorCLI drive data when absent from the PD list.
- Enclosure-backed MegaRAID behavior remains unchanged and does not gain extra StorCLI polling.
# Home Server Monitor 7.10.0-alpha.4

- Raised HDD Cooling thresholds to 40/45/50/55/60 C with release thresholds 37/42/47/52/57 C.
- Added a Cooling policy version so the first alpha.4 cycle re-synchronizes x8fan and releases stale low-speed states from the previous 35 C policy.
- Fixed Storage `Warning` stat to display 0 when there are no warning disks.
- Fixed `Current disk temperature` and `Current health score` to use only fresh storage_status samples from the last 2 minutes, preventing disks that have moved behind RAID from lingering in Storage gauges.
# Home Server Monitor 7.10.0-alpha.3

- Reworked Cooling around event-driven x8fan access to minimize SMBus/W83795 traffic.
- Cooling now runs every 60 seconds but does not touch x8fan during ordinary stable-temperature cycles.
- `x8fan auto` is invoked only on initial synchronization, HDD hysteresis-boundary crossings, or CPU emergency transitions at 85 C / release below 80 C.
- Removed periodic/safety `x8fan auto` writes.
- Added a read-only x8fan status poll every 10 minutes and immediately after a control event.
- Added retry backoff after hardware-access failures: 1 minute, 5 minutes, then 15 minutes.
- A CPU emergency transition may bypass backoff once to attempt emergency fan escalation.
- Added direct CPU temperature sampling from Linux `coretemp`, avoiding W83795/BMC in the 60-second decision loop.
- Added Cooling Health Engine rules: x8fan/W83795 loss is WARNING; simultaneous W83795 loss plus all BMC sensors N/A is CRITICAL.
- HSM never performs an automatic BMC reset.
- Corrected Grafana mappings for real x8fan modes and sources.
- Cooling remains optional during install/update unless `HSM_COOLING_REQUIRED=true`.
# Home Server Monitor 7.10.0-alpha.2

- Made Cooling non-fatal during install/update when `HSM_COOLING_REQUIRED=false`; temporary x8fan/BMC hardware unavailability now produces a warning instead of aborting the update.
- Reduced x8fan control writes: `x8fan auto <HDD_MAX>` is now sent only when HDD Tmax changes, when no prior control state exists, or after a configurable safety refresh (default 300 seconds).
- Added persistent Cooling control state under `/var/cache/home-server-monitor/cooling-control.json`.
- A failed x8fan `auto` operation no longer prevents HSM from attempting a read-only `status` collection.
- Fixed Grafana `Mode` and `Control Source` cards using numeric code fields with value mappings, avoiding InfluxQL string-field limitations in Stat panels.
- Added filtering for invalid x8fan temperature sentinel values such as `-124 C`; these are now treated as unavailable rather than real temperatures.
- Split the Cooling temperature graph into independent CPU/System/HDD queries and filtered legacy invalid System temperature points from the graph.
- Fixed `Mode` and `Control Source` Grafana stat panels by returning string fields as table results.
- Simplified Cooling stat cards to display values without the generic `cooling_status.last` field label.
- Added a `Cooling` quick-navigation button to all six HSM dashboards.
- Added `cooling_status` and `cooling_fan` freshness checks to `hsm doctor` / `hsm verify`.
- Renamed exact Cooling timestamp fields to last_change_unix and last_update_unix so existing alpha.1 float fields do not cause InfluxDB field type conflicts during upgrade.
- Changed managed Telegraf config validation to syntax-only TOML validation; collectors are validated sequentially later, avoiding artificial Storage/RAID contention during updates.
- Increased the Storage collector timeout from 20s to 30s after real runtime testing showed ~18s collection time on the current disk set.
- Added the first Grafana Cooling dashboard.
- Added current Mode, PWM2, CPU Tmax, System Temp, HDD Tmax, and control source panels.
- Added temperature, PWM2, and FAN1-FAN8 RPM history.
- Added a current fan table that preserves unavailable fan channels separately from numeric RPM.
- Registered Cooling as the sixth managed Grafana dashboard.
- Added `mode_name` and `source_name` fields to `cooling_status` for direct Grafana display.
- Fixed x8fan `last_change` and `last_update` precision by storing exact integer Unix timestamps instead of low-precision float line protocol values.
- Health Engine rules for Cooling remain deferred until dashboard/runtime behavior is validated.
# Home Server Monitor 7.10.0-alpha.1

- Added the first Cooling module backed by x8fan.
- Cooling reads the maximum recent disk temperature from existing `storage_status` and `raid_drive_status` InfluxDB metrics.
- When a valid disk temperature exists, HSM calls `x8fan auto <HDD_MAX_TEMP>`.
- If disk temperature data is unavailable, HSM does not call `x8fan auto` and never substitutes a fake 0 C.
- Added `cooling_status` metrics for mode, PWM2, CPU Tmax, System Temp, HDD Tmax, control source, and timestamps.
- Added `cooling_fan` metrics for FAN1 through FAN8 while preserving the distinction between 0 RPM and unavailable/null channels.
- Added a narrow privileged x8fan helper that permits only `status` and validated `auto <1..100>` operations.
- Added the Cooling collector to managed Telegraf execution at a 10 second interval.
- Grafana Cooling dashboard and Health Engine rules are intentionally deferred until the runtime collector is validated on the server.
# Home Server Monitor 7.9.0-alpha.2

- Automated installation of the HP Smart Array read-only ssacli helper and sudoers policy.
- Added upgrade-safe HP Smart Array defaults to `/etc/default/home-server-monitor`.
- Added `hsm doctor` checks for the helper, ssacli binary, and Telegraf read-only access.
- Added runtime RAID capabilities `hp-smartarray` and `ssacli`.
- Backend-specific RAID capabilities now reflect actual runtime availability.
- Added HP Smart Array settings to the example configuration.
- Existing MegaRAID, Storage, UPS, Proxmox, InfluxDB schema, and Grafana queries are unchanged.
# Home Server Monitor 7.9.0-alpha.1

- Added the first HP Smart Array RAID backend.
- Added controller-only monitoring through a narrow privileged ssacli helper.
- Added P410 model, slot, serial, firmware, controller status, cache status, and battery status collection.
- A controller with no logical or physical drives is reported normally with zero drive counts.
- `Cache Status: Not Configured` does not by itself change controller health.
- Existing MegaRAID/StorCLI and 3ware backends remain unchanged.
- Physical-drive and logical-drive parsing for HP Smart Array will be added after drives are connected.
# Home Server Monitor 7.8.1

First stable release.

Highlights

- Modular collector architecture.
- Independent Storage, RAID, UPS and Proxmox collectors.
- Health Engine with rule-based scoring.
- Doctor / Verify / Benchmark CLI.
- Five integrated Grafana dashboards.
- Stable modular Telegraf architecture.
- Improved Verify diagnostics.
- Stable Proxmox dashboard including short time ranges.
- GitHub CI improvements.
- Fully compatible with all 7.8.1 beta releases.

No database migration required.

# Home Server Monitor 7.8.1-beta.3

- Added `hsm verify` and `hsm verify --json` for live delivery-path validation.
- Added InfluxDB freshness checks for Storage, RAID, UPS, Proxmox host, and Proxmox storage measurements.
- Added per-dashboard checks for Overview, Storage, RAID, UPS, and Proxmox.
- Filtered Telegraf journal inspection to HSM modular commands so unrelated plugin failures are not reported as HSM collector failures.
- Added metrics-per-second and summary throughput to `hsm benchmark`.
- Expanded `hsm info` with Core, Health Engine, CLI, JSON API, capability, measurement, dashboard, and managed-configuration details.
- Updated README and CLI documentation for the release-candidate workflow.
- Preserved collector metrics, Health Engine rules, InfluxDB schema, and Grafana queries from beta.2.

# Home Server Monitor 7.8.1-beta.2

- Fixed the Proxmox dashboard for short time ranges such as 5m, 15m, 30m, 1h, and 3h.
- Proxmox stat panels now use a recent 10-minute lookup window so current values remain visible.
- Proxmox history panels now aggregate at a stable 30-second interval.
- Added 30-second dashboard refresh and explicit short-range time-picker options.
- No collector, measurement, tag, field, or health-rule changes.

# 7.8.1-alpha.3

- Expanded Health Engine rules for Storage, RAID, UPS, and Proxmox.
- Added UNKNOWN handling for unavailable SMART data and unknown RAID states.
- Added RAID media, predictive-failure, other-error, and temperature checks.
- Added UPS replacement-battery, charge, load, and internal-temperature checks.
- Added Proxmox CPU, load-average, memory, swap, inactive-storage, and capacity checks.
- Kept all collector measurements, tags, fields, and Telegraf configuration unchanged.

# 7.8.1-alpha.2

- Added per-finding impact values to the Health Engine.
- Overall and domain scores are now calculated from finding impacts.
- Added stable domain order: Storage, RAID, UPS, Proxmox.
- Added primary finding and severity counts to text and JSON status output.
- Findings are sorted by impact and severity.
- Preserved collector metrics and Telegraf configuration.

# 7.8.0-alpha.2

- Replaced the legacy monolithic Telegraf input with four independent `hsm-collect` inputs.
- Added managed `/etc/telegraf/telegraf.d/90-home-server-monitor.conf`.
- Added safe removal and backup of legacy `collector.py` exec blocks.
- Added per-module intervals and timeouts validated against production timings.
- Installer and updater validate every module before restarting Telegraf.

# Changelog

## 7.7.3

- Replaced the UTF-8-dependent Telegraf configuration patcher with a byte-safe shell and awk implementation.
- Added atomic temporary-file handling and per-file backups before changing collector timeout.
- Preserved support for both the main Telegraf configuration and drop-in files.

## 7.7.2

- Fixed Telegraf `inputs.exec` timeout during upgrades by enforcing `timeout = "30s"` for the HSM collector block.
- The updater patches the existing Telegraf configuration in place and creates a one-time backup.
- Removed infrastructure-state warnings from collector stderr; Proxmox storage health remains available through metric fields.
- Restored automatic writes for RAID, direct-disk, and Proxmox storage metrics when collection takes longer than five seconds.

## 7.7.1

- Fixed Proxmox storage collection under the unprivileged telegraf account.
- Added a root-owned fixed-command helper with a narrowly scoped sudoers rule.
- Critical storage usage no longer makes collector execution fail.
- Health remains CRITICAL through metric-based health evaluation.

## 7.7.0

- Added Proxmox storage collection through `pvesh`.
- Added `proxmox_storage` metrics with capacity and health fields.
- Added storage health thresholds and overall provider health impact.
- Added Proxmox storage panels to Storage and Home dashboards.
- Added Proxmox navigation link to all dashboards.
- Added Doctor checks for `pvesm`, `qm`, and `pct`.
- Grouped CLI collectors consistently by domain.

## 7.8.0-alpha.1

- Added `hsm-collect storage|raid|ups|proxmox|all`.
- Added independent provider selection without changing existing metrics.
- Kept `collector.py` as the production-compatible all-provider entry point.
- Installer and updater now install `/usr/local/bin/hsm-collect`.
- Added modular collector selection regression tests.

## 7.8.1-alpha.1

- Added a rule-based Health Engine with explicit OK, WARNING, HIGH, CRITICAL, and UNKNOWN severities.
- Added domain health evaluation for Storage, RAID, UPS, and Proxmox.
- Reworked `hsm status` to show actionable reasons per subsystem.
- Expanded `hsm status --json` with structured domain findings.
- Preserved all existing InfluxDB measurements, tags, fields, and Telegraf collector configuration.

## 7.8.1-beta.1

- Added modular collector execution checks to `hsm doctor`.
- Added structured `hsm doctor --json` output.
- Added `hsm benchmark` and `hsm benchmark --json`.
- Added validation of the managed Telegraf file and duplicate/legacy collector detection.
- Preserved all existing measurements, tags, fields, dashboards, and health rules.
