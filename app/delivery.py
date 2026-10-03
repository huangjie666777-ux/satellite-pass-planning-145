"""Delivery: JSON summary and per-second tracking CSV packaged as ZIP."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timedelta

from .passes import PassInterval, Site, look
from .tle import TLEData

C_LIGHT_M_S = 299_792_458.0

CSV_HEADER = [
    "time_utc",
    "azimuth_deg",
    "elevation_deg",
    "slant_range_km",
    "range_rate_km_s",
    "doppler_shift_hz",
]


def interval_summary(p: PassInterval) -> dict:
    return {
        "satellite_id": p.sat_id,
        "site": p.site,
        "start_utc": p.start.isoformat(),
        "end_utc": p.end.isoformat(),
        "duration_s": round(p.duration_s, 1),
        "truncated_start": p.truncated_start,
        "truncated_end": p.truncated_end,
        "max_elevation_deg": round(p.max_el_deg, 3),
        "max_elevation_time_utc": p.max_el_time.isoformat(),
    }


def track_csv(
    tle: TLEData, site: Site, p: PassInterval, downlink_hz: float
) -> str:
    """Per-second tracking rows; Doppler negative when range increases."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_HEADER)
    n = int(p.duration_s)
    dt = timedelta(seconds=1.0)
    times = [p.start + timedelta(seconds=k) for k in range(n + 1)]
    if times[-1] < p.end:
        times.append(p.end)
    rows = []
    for t in times:
        az, el, rng_m = look(tle, site, t)
        rows.append((t, az, el, rng_m))
    for i, (t, az, el, rng_m) in enumerate(rows):
        if i == 0:
            rr = (rows[1][3] - rows[0][3]) / _secs(rows[1][0] - rows[0][0])
        elif i == len(rows) - 1:
            rr = (rows[i][3] - rows[i - 1][3]) / _secs(rows[i][0] - rows[i - 1][0])
        else:
            rr = (rows[i + 1][3] - rows[i - 1][3]) / _secs(rows[i + 1][0] - rows[i - 1][0])
        doppler = -downlink_hz * rr / C_LIGHT_M_S
        w.writerow([
            t.isoformat(),
            f"{az:.3f}",
            f"{el:.3f}",
            f"{rng_m / 1000.0:.3f}",
            f"{rr / 1000.0:.6f}",
            f"{doppler:.1f}",
        ])
    return buf.getvalue()


def _secs(delta) -> float:
    s = delta.total_seconds()
    return s if s > 0 else 1.0


def build_zip(
    summary: dict,
    tracks: list[tuple[PassInterval, str]],
) -> bytes:
    """summary: JSON-able dict; tracks: (interval, csv_text)."""
    import json

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("summary.json", json.dumps(summary, indent=2))
        for i, (p, csv_text) in enumerate(tracks):
            name = (
                f"track_{i:03d}_{p.sat_id}_{p.site}_"
                f"{p.start.strftime('%Y%m%dT%H%M%SZ')}.csv"
            )
            zf.writestr(name, csv_text)
    return buf.getvalue()

