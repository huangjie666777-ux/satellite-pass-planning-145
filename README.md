# Offline Satellite Pass Prediction Backend

Ground-station pass planner: predicts satellite visibility intervals and
generates antenna/receiver tracking tables (azimuth, elevation, range,
range rate, Doppler shift) for up to 4 satellites and 4 ground sites.

## Stack

- Python 3.10, FastAPI 0.115.12, sgp4 2.26 (SGP4 with the WGS72 constants)
- Runs fully offline; no external ephemeris services.

## Run

```bash
python3.10 -m venv .venv
.venv/bin/pip install fastapi==0.115.12 sgp4==2.26 uvicorn pytest httpx
.venv/bin/uvicorn app.main:app --port 8000
```

## API

### POST /passes — JSON forecast

### POST /passes/download — ZIP (summary.json + one tracking CSV per interval)

Request body (see examples/request.json):

```json
{
  "satellites": [{"name": "ISS", "line1": "1 ...", "line2": "2 ..."}],
  "sites": [{
    "name": "ground-a",
    "lat_deg": 39.9042, "lon_deg": 116.4074, "alt_m": 50.0,
    "mask": [{"azimuth_deg": 90.0, "min_elevation_deg": 30.0}]
  }],
  "window": {"start_utc": "2026-10-01T07:00:00Z",
             "end_utc": "2026-10-01T13:00:00Z"},
  "downlink_frequency_hz": 145800000.0
}
```

Limits: at most 4 satellites, 4 sites, and a 24 h UTC window.

### Validation

- TLE lines must be exactly 69 chars, pass the mod-10 checksum, and carry
  the same satellite number on both lines.
- Duplicate satellite IDs are rejected.
- Latitude must be in [-90, 90], longitude in [-180, 180]; all numeric
  fields must be finite (NaN/Inf rejected).
- The query window must lie within 7 days of the TLE epoch.
- Any SGP4 propagation failure fails the whole request (HTTP 500).

### Response (JSON)

Each interval: satellite id, site, start/end UTC, duration_s,
truncated_start/truncated_end flags (interval clipped by the query
window), max elevation and its time (sampled once per second).
Intervals are sorted by start time, then satellite id.

### Tracking CSV columns

time_utc, azimuth_deg, elevation_deg, slant_range_km, range_rate_km_s,
doppler_shift_hz. Doppler shift = -f_tx * range_rate / c, so an
increasing range gives a negative shift. One row per second.

## Models and approximations

- SGP4 propagation in TEME with WGS72 constants (sgp4 package).
- TEME -> ECEF by GMST rotation only, using UTC as an approximation of
  UT1; polar motion, nutation, refraction and light-time are NOT modelled.
  Expect ~km-level position and sub-degree look-angle residuals versus a
  full IAU-2000 chain.
- Sites use WGS84 geodetic lat/lon/height; azimuth is clockwise from
  true north.
- Obstruction mask: (azimuth, min-elevation) nodes, sorted and linearly
  interpolated around the compass (wraps across 0/360 deg). A pass may be
  split into several intervals by the mask.
- Search grid is 1 s; crossing times are bisected to 0.1 s. Visibility
  windows shorter than 1 s may be missed. Tangential contacts (grazing
  the mask without exceeding it) do not count as intervals.

## Example

```bash
.venv/bin/python examples/make_request.py   # regenerates examples/request.json
curl -s -X POST localhost:8000/passes -H 'Content-Type: application/json' \
  -d @examples/request.json
curl -s -X POST localhost:8000/passes/download -H 'Content-Type: application/json' \
  -d @examples/request.json -o passes.zip
```

The example TLE is the classic ISS (25544) element set with its epoch
rewritten to 2026-10-01 and checksums recomputed, so the whole request is
reproducible offline.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

## Layout

- app/tle.py — TLE parsing/validation
- app/coords.py — GMST, TEME->ECEF, geodetic->ECEF, look angles
- app/passes.py — obstruction mask, pass search, bisection
- app/delivery.py — JSON summary, tracking CSV, ZIP packaging
- app/main.py — FastAPI endpoints and request validation

