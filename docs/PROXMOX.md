# Proxmox Host Collector

Version 7.7.0 adds the first read-only Proxmox collector.

## Measurements

### proxmox_host_info

Tags: `host`, `node`.

Fields: `present`, `pve_version`, `kernel_version`, `cpu_model`, `cpu_count`.

### proxmox_host_status

Tags: `host`, `node`.

Fields include uptime, CPU usage, load averages, RAM usage, and swap usage.

## Data sources

The collector reads `/proc/stat`, `/proc/loadavg`, `/proc/meminfo`, `/proc/uptime`, `/proc/cpuinfo`, and runs `pveversion`. It does not modify the Proxmox host.

## Configuration

- `HSM_PROXMOX_ENABLED=true`
- `HSM_PROXMOX_REQUIRED=false`
- `HSM_PVEVERSION_BINARY=pveversion`
- `HSM_PROXMOX_CPU_SAMPLE_SECONDS=0.10`
