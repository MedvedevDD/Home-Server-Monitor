# Home Server Monitor 7.8.1

Home Server Monitor (HSM) collects hardware and Proxmox metrics, writes Influx Line Protocol through Telegraf, and installs a Grafana dashboard set.

## Current modules

- Storage inventory and SMART health
- MegaRAID controller and physical-drive health
- HP Smart Array controller health through ssacli
- NUT UPS status
- Proxmox host and Proxmox storage status
- Rule-based Health Engine

## Architecture

Telegraf runs four independent commands from the managed file:

```text
/etc/telegraf/telegraf.d/90-home-server-monitor.conf
```

The commands are:

```bash
hsm-collect storage
hsm-collect raid
hsm-collect ups
hsm-collect proxmox
```

The legacy `collector.py` remains as a compatibility entry point but is not used by the managed Telegraf configuration.

## Requirements

- Debian or Proxmox VE
- Python 3.10 or newer
- Telegraf
- InfluxDB 1.x command-line client
- Grafana with an existing InfluxDB datasource
- smartmontools
- StorCLI when MegaRAID monitoring is enabled
- NUT client tools when UPS monitoring is enabled

## Install

```bash
cd Home_Server_Monitor-7.8.1
sudo ./install.sh
```

## Update

```bash
cd Home_Server_Monitor-7.8.1
sudo ./update.sh
```

The updater preserves the HSM environment file, inventory cache, and existing InfluxDB data.

## Main commands

```bash
hsm version
hsm info
hsm collectors --verbose
hsm capabilities --verbose
hsm doctor
hsm verify
hsm benchmark
hsm status
```

Machine-readable output is available for the main diagnostic commands:

```bash
hsm info --json
hsm doctor --json
hsm verify --json
hsm benchmark --json
hsm status --json
```

### Doctor

`hsm doctor` checks installation structure, Telegraf configuration, collector execution, service state, measurement freshness, Grafana datasource detection, and every expected dashboard file.

### Verify

`hsm verify` checks the live delivery path:

- current service state;
- fresh timestamps for key InfluxDB measurements;
- presence of all five Grafana dashboards;
- HSM-specific Telegraf timeouts and plugin failures from the last 24 hours.

Unrelated Telegraf plugin errors, such as a temporary `inputs.upsd` connection error, are not treated as an HSM collector failure.

### Benchmark

`hsm benchmark` runs each modular collector independently and reports runtime, metric count, and metrics per second.

### Status

`hsm status` evaluates Storage, RAID, UPS, and Proxmox health. Doctor health and infrastructure health are intentionally separate: a full Proxmox storage may make `hsm status` CRITICAL while `hsm doctor` remains HEALTHY.

## Grafana dashboards

- Overview
- Storage
- RAID
- UPS
- Proxmox

The Proxmox dashboard supports short ranges including 5m, 15m, 30m, 1h, and 3h.

## Installed paths

```text
/opt/home-server-monitor
/etc/default/home-server-monitor
/etc/telegraf/telegraf.d/90-home-server-monitor.conf
/etc/grafana/provisioning/dashboards/home-server-monitor.yaml
/var/lib/grafana/dashboards/home-server-monitor
/var/cache/home-server-monitor
/usr/local/bin/hsm
/usr/local/bin/hsm-collect
```

## Documentation

See the `docs/` directory for architecture, configuration, CLI, Doctor, Grafana, Health Engine, Proxmox, and migration details.
