# Core Services

Version 7.5.1 introduces the common collector lifecycle used by current and future integrations.

## Lifecycle

1. Discovery
2. Dependency validation
3. Collection
4. Metrics pipeline export
5. Health and event processing

Existing providers remain compatible because `discover()` has a safe default implementation.

## Commands

`hsm collectors` displays loaded collectors, domains, and runtime availability.

`hsm capabilities` displays capabilities grouped by domain.

## Services

- `CollectorManager` runs discovery and collection.
- `MetricsPipeline` separates providers from Influx serialization.
- `HealthSummary` derives a common status from warnings and errors.
- `EventBus` is a synchronous internal bus ready for future notification backends.
