# Grafana provisioning

Home Server Monitor installs all dashboards through Grafana file provisioning.

Installed dashboard directory:

```text
/var/lib/grafana/dashboards/home-server-monitor
```

Provisioning file:

```text
/etc/grafana/provisioning/dashboards/home-server-monitor.yaml
```

The installer resolves the InfluxDB datasource UID in this order:

1. `HSM_GRAFANA_DATASOURCE_UID` from `/etc/default/home-server-monitor` or the process environment.
2. The first InfluxDB datasource found in `/var/lib/grafana/grafana.db`.
3. A clear installation error if no datasource can be found.

Example override:

```text
HSM_GRAFANA_DATASOURCE_UID=my-influxdb-uid
```

After installation, Grafana shows one folder named `Home Server Monitor` containing Home, Storage, RAID, and UPS.
