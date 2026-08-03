# Home Server Monitor v7.2.1

- Load `/etc/default/home-server-monitor` directly from the collector configuration.
- Fix SMART permission settings when Telegraf calls `collector.py` directly.
- Grafana zero-count cards show `0` instead of `No data`.
- Compact Storage table columns and headings.
- Hide redundant columns from the direct-disk table.
- Rename Unknown to SMART unavailable for clearer diagnostics.
