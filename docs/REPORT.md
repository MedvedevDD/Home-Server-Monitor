# Diagnostic Report

Create a report with:

```bash
hsm report
```

Choose a destination with:

```bash
hsm report --output /root/hsm-report.tar.gz
```

The archive includes service state, Telegraf logs, collector output, disk inventory, Doctor output, software versions, detected Telegraf configuration locations, and StorCLI output when available.

Configuration keys containing password, token, secret, API key, or authentication markers are redacted. Review any diagnostic archive before sharing it outside your trusted environment.
