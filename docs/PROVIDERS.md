# Providers

A provider is an independent source of metrics. It collects data and returns a `ProviderResult`; it does not print Influx Line Protocol and does not write to InfluxDB directly.

Built-in providers in 7.5.0:

- `storage`: inventory, SMART, SATA, NVMe, and USB flash filtering;
- `raid`: MegaRAID controller, array, and physical-drive state through StorCLI;
- `ups`: UPS state through NUT.

Each provider defines a stable name, a provider API version, capabilities, and a `collect()` method. The `ProviderRegistry` preserves registration order, rejects duplicate names, and gives the collector one common collection path.

## Failure behavior

The storage provider is required because storage is the foundation of the current dashboards. A storage or global SMART startup failure returns a collector error.

RAID and UPS follow their existing `HSM_RAID_REQUIRED` and `HSM_UPS_REQUIRED` settings. Optional provider failures are logged as warnings and do not suppress metrics from healthy providers.

## Adding a provider

1. Create a class derived from `core.provider.Provider`.
2. Return `core.result.ProviderResult` from `collect()`.
3. Register the provider in `build_provider_registry()`.
4. Add provider unit tests and one collector regression test.

Providers must return `Metric` objects and must not write to stdout. Only the collector output boundary serializes metrics.
