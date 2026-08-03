# Modular collectors (7.8.0 alpha)

This alpha introduces the command interface for independent provider runs while preserving all existing measurements, tags, fields, and status codes.

Commands:

```text
hsm-collect storage
hsm-collect raid
hsm-collect ups
hsm-collect proxmox
hsm-collect all
```

`collector.py` remains the active Telegraf entry point in this alpha. The next milestone will create a managed Telegraf configuration with four independent `inputs.exec` blocks after production validation of each command.
