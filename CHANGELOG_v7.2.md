# Home Server Monitor v7.2.0

## Collector

- Excludes MegaRAID physical drives from all `storage_*` measurements.
- Uses StorCLI OS-device/serial identity when available.
- Uses MegaRAID SMART serial identity when StorCLI omits JBOD identity fields.
- Keeps direct OS-visible disks in Storage.
- Keeps RAID controller, virtual-drive, and physical-drive metrics in RAID only.
- Preserves inventory output when smartctl is globally unavailable.

## Grafana

- Adds separate Home, Storage, RAID, and UPS dashboards.
- Adds native top dashboard links between all four pages.
- Keeps time range and variables while navigating.
- Adds filesystem usage panels based on standard Telegraf `disk` metrics.
- Keeps direct-disk SMART panels on the Storage page.
- Uses current-state freshness filters to prevent historical snapshots from looking like duplicate devices.

## Validation

- 120 unit tests pass.
- Python compile validation passes.
- All Grafana JSON files parse successfully.
