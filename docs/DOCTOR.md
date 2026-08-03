# HSM Doctor

Run:

```bash
hsm doctor
```

Doctor checks the installed files, required commands, enabled integrations, services, Grafana provisioning, and a real collector execution.

## Telegraf configuration discovery

Doctor does not require one fixed filename. It searches:

- `/etc/telegraf/telegraf.conf`
- every `*.conf` file below `/etc/telegraf/telegraf.d/`

A check passes when an active configuration file contains the Home Server Monitor collector command. This avoids false failures when the configuration was renamed or merged into another file.

## Exit codes

- `0`: no failed checks
- `1`: at least one failed check

Warnings do not change the exit code to failure.
