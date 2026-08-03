# Health Engine

HSM evaluates the existing collector metrics without changing their InfluxDB schema.

## Domains

- Storage: SMART availability, health result, sector counters, temperatures, and smartctl status bits.
- RAID: normalized state, media errors, predictive failures, other errors, and drive temperature.
- UPS: online/battery state, low battery, overload, replacement battery, charge, load, and temperature.
- Proxmox: storage availability/capacity, memory, swap, CPU usage, and normalized 15-minute load.

Findings use OK, WARNING, HIGH, CRITICAL, or UNKNOWN severity and carry an impact value used for the score.
