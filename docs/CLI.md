# HSM command-line tool

The installer creates `/usr/local/bin/hsm`.

## Commands

`hsm version` prints the installed version.

`hsm status` prints a compact status of Telegraf, InfluxDB, Grafana, and the Grafana datasource.

`hsm doctor` checks the installation, required commands, services, Grafana datasource, dashboards, and a live collector run. It exits with code 1 when a required check fails.

`hsm self-test` runs all bundled Python regression tests.

`hsm report` creates a compressed diagnostic archive in the current directory. Configuration keys containing PASSWORD, TOKEN, SECRET, API_KEY, or AUTH are redacted. Use `--output /path/file.tar.gz` to select the destination.

## hsm verify

Checks live service state, fresh InfluxDB measurements, expected Grafana dashboards, and recent HSM-specific Telegraf collector failures.

```bash
hsm verify
hsm verify --json
```

The journal check only considers lines that reference `hsm-collect`; unrelated Telegraf input errors are ignored.
