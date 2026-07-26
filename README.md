# Sydney Transport Live

Private Home Assistant custom integration for live **Transport for NSW** bus
data. Built for a personal Home Assistant Green install; installable via HACS
as a **custom repository**.

## Features

- Live GPS positions for route **311** (Map card via `geo_location`)
- ETA timetable for both Rockwall Cres stops near **81 Macleay St**
  (At Rockwall Cres → City, Opp Rockwall Cres → Central)
- Active-bus count sensor
- Config Flow with API key, route, stop, and direction
- ~8s vehicle polling / 30s departure polling (configurable)
- Diagnostics, refresh, cache clear, and purge-unavailable-trackers services

> Home Assistant’s Map card cannot show a TripView-style timetable. Keep the
> map for GPS pins and put the ETA markdown/tile cards underneath (see
> [`lovelace/sydney_transport_live.yaml`](lovelace/sydney_transport_live.yaml)).

## Install with HACS (recommended)

1. HACS → **⋯** → **Custom repositories**
2. Repository: `https://github.com/wlee-star/sydney-transport-live`
3. Type: **Integration**
4. Add, then download **Sydney Transport Live**
5. Restart Home Assistant
6. **Settings → Devices & Services → Add Integration → Sydney Transport Live**

## Manual install

1. Copy `custom_components/sydney_transport_live` into your HA config:

   ```text
   /config/custom_components/sydney_transport_live/
   ```

2. Restart Home Assistant.
3. Add the integration as above.

## Setup

1. Create an API token at [TfNSW Open Data Hub](https://opendata.transport.nsw.gov.au).
2. Enter the API key in the config flow.
3. Keep route **311**, pick **Macleay St at Rockwall Cres**, and choose the
   **Sydney CBD** direction.
4. Optional: paste [`lovelace/sydney_transport_live.yaml`](lovelace/sydney_transport_live.yaml)
   into a dashboard view and add live `device_tracker` entities to the Map card.

## Services

| Service | Description |
|---------|-------------|
| `sydney_transport_live.refresh` | Force-refresh positions + departures |
| `sydney_transport_live.clear_cache` | Delete cached buses GTFS ZIP and re-download |

## Logging

In `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.sydney_transport_live: debug
```

## Notes

- The vehicle-positions feed is **city-wide**; the integration filters to your
  route/direction immediately after decode.
- Static GTFS is cached under `/config/sydney_transport_live/gtfs_buses/` and
  refreshed around the overnight timetable window.
- Never commit your API key. Config entries store it encrypted on HAOS.
