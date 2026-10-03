"""Build a reproducible example request.json.

Takes a well-known ISS TLE, rewrites the epoch to 2026-274 (Oct 1, 2026),
recomputes both checksums, and writes examples/request.json with a site
that has an obstruction mask.
"""
import json

L1 = "1 25544U 98067A   26274.50000000  .00016717  00000-0  30815-3 0  9990"
L2 = "2 25544  51.6400 208.9163 0006703  69.9862  25.2906 15.49560532    00"


def fix(line: str) -> str:
    line = line[:68]
    total = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in line)
    return line + str(total % 10)


req = {
    "satellites": [{"name": "ISS", "line1": fix(L1), "line2": fix(L2)}],
    "sites": [
        {
            "name": "ground-a",
            "lat_deg": 39.9042,
            "lon_deg": 116.4074,
            "alt_m": 50.0,
            "mask": [
                {"azimuth_deg": 0.0, "min_elevation_deg": 5.0},
                {"azimuth_deg": 90.0, "min_elevation_deg": 30.0},
                {"azimuth_deg": 180.0, "min_elevation_deg": 5.0},
                {"azimuth_deg": 270.0, "min_elevation_deg": 10.0},
            ],
        }
    ],
    "window": {"start_utc": "2026-10-01T07:00:00Z", "end_utc": "2026-10-01T13:00:00Z"},
    "downlink_frequency_hz": 145_800_000.0,
}

with open("examples/request.json", "w") as f:
    json.dump(req, f, indent=2)
print(fix(L1))
print(fix(L2))
