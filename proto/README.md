# TfNSW GTFS-Realtime protobuf references

This integration uses the PyPI package `gtfs-realtime-bindings`, which vendors
the standard Google `gtfs-realtime.proto`.

TfNSW publishes an extended proto (extension field 1007) with extra vehicle
descriptor fields (air conditioning, wheelchair, vehicle model). V1 does not
require those extensions for map + occupancy enums already present in the
standard feed.

## Sources

- [TfNSW Open Data documentation](https://opendata.transport.nsw.gov.au/developers/documentation)
- [gtfs-realtime.proto (TfNSW copy)](https://opendata.transport.nsw.gov.au/sites/default/files/2023-08/gtfs-realtime.proto_.txt)
- Standard bindings: `pip install gtfs-realtime-bindings`

## Regenerating (optional)

If you need TfNSW extensions later:

1. Download the TfNSW proto (rename `*.txt` → `*.proto`).
2. Generate Python stubs with `protoc` / `grpc_tools`.
3. Swap the import in `api/gtfs_realtime.py`.
