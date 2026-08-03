# Architecture

Home Server Monitor uses a collector pipeline:

1. `collector.py` loads configuration and inventory.
2. Storage, SMART, MegaRAID, and UPS components collect data.
3. Metrics are emitted in Influx line protocol.
4. Telegraf runs the collector through `inputs.exec`.
5. InfluxDB stores the measurements.
6. Provisioned Grafana dashboards display the data.

## Main components

- `collector.py`: orchestration and metric output
- `config.py`: environment configuration
- `services/`: inventory, SMART, RAID, classification, and shared helpers
- `collectors/`: subsystem collectors
- `hsm.py`: administration CLI and diagnostics
- `dashboard/`: Grafana dashboard templates
- `tests/`: regression tests and hardware-output fixtures

## Design rules

- A failed Doctor check must represent a real operational problem.
- Device identity must not depend on `/dev/sdX` names.
- Providers should not silently invent missing data.
- Every fixed regression should receive a test.
- Health colors are reserved for health state.


## Provider runtime (7.5.0)

The collector builds an ordered `ProviderRegistry`. Storage, UPS, and RAID providers return `ProviderResult` objects containing metrics and diagnostics. Providers do not serialize or write metrics. The collector is the single Line Protocol output boundary. This preserves Telegraf compatibility while making future Proxmox and network providers independent of the current storage code.
