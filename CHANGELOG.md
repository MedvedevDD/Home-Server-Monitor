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
