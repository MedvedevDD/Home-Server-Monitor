# Beta diagnostics

Version 7.8.1-beta.2 validates the modular collector architecture before the stable 7.8.1 release.

## Commands

- `hsm doctor` runs installation, Telegraf, service, Grafana, and per-module execution checks.
- `hsm doctor --json` emits the same checks as structured JSON.
- `hsm benchmark` measures runtime and metric count for storage, RAID, UPS, and Proxmox collectors.
- `hsm benchmark --json` emits benchmark results as JSON.

Doctor checks operability only. Infrastructure health findings remain in `hsm status`.
