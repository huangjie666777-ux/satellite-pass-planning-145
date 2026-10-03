"""Pass (overflight) search on a 1-second grid with 0.1 s bisection refinement."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sgp4.api import jday

from .coords import look_angles, teme_to_ecef
from .tle import TLEData

GRID_STEP_S = 1.0
BISECT_TOL_S = 0.1


class PropagationError(RuntimeError):
    """Raised when SGP4 propagation fails for any sample."""


@dataclass
class Site:
    name: str
    lat_deg: float
    lon_deg: float
    alt_m: float
    # sorted obstruction nodes: (azimuth_deg, min_elevation_deg)
    mask: list[tuple[float, float]] = field(default_factory=list)


def mask_elevation(mask: list[tuple[float, float]], az_deg: float) -> float:
    """Min elevation at azimuth via circular linear interpolation (wraps 0/360)."""
    if not mask:
        return 0.0
    if len(mask) == 1:
        return mask[0][1]
    az = az_deg % 360.0
    pts = mask  # assumed sorted by azimuth
    n = len(pts)
    # find segment [i, i+1) (circular)
    for i in range(n):
        a0, e0 = pts[i]
        a1, e1 = pts[(i + 1) % n]
        span = (a1 - a0) % 360.0
        off = (az - a0) % 360.0
        if off <= span:
            if span == 0.0:
                return e0
            return e0 + (e1 - e0) * off / span
    return pts[-1][1]


def _propagate(tle: TLEData, dt: datetime) -> tuple:
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute,
                  dt.second + dt.microsecond * 1e-6)
    err, r, v = tle.sat.sgp4(jd, fr)
    if err != 0:
        raise PropagationError(
            f"SGP4 error {err} for satellite {tle.sat_id} at {dt.isoformat()}"
        )
    return r


def elevation_minus_mask(tle: TLEData, site: Site, dt: datetime) -> float:
    r_teme = _propagate(tle, dt)
    sat_ecef = teme_to_ecef(r_teme, dt)
    az, el, _ = look_angles(sat_ecef, site.lat_deg, site.lon_deg, site.alt_m)
    return el - mask_elevation(site.mask, az)


def look(tle: TLEData, site: Site, dt: datetime) -> tuple:
    """(az_deg, el_deg, range_m) at dt."""
    r_teme = _propagate(tle, dt)
    sat_ecef = teme_to_ecef(r_teme, dt)
    return look_angles(sat_ecef, site.lat_deg, site.lon_deg, site.alt_m)


def _bisect_crossing(tle, site, t_inside, t_outside) -> datetime:
    """Refine the crossing between an inside and an outside sample to 0.1 s."""
    lo = t_inside
    hi = t_outside
    while abs((hi - lo).total_seconds()) > BISECT_TOL_S:
        mid = lo + (hi - lo) / 2
        if elevation_minus_mask(tle, site, mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return lo


@dataclass
class PassInterval:
    sat_id: str
    site: str
    start: datetime
    end: datetime
    truncated_start: bool
    truncated_end: bool
    max_el_deg: float
    max_el_time: datetime

    @property
    def duration_s(self) -> float:
        return (self.end - self.start).total_seconds()


def find_passes(
    tles: list[TLEData], sites: list[Site], t0: datetime, t1: datetime
) -> list[PassInterval]:
    """Find visibility intervals above the obstruction mask.

    1 s grid; crossings bisected to 0.1 s. Intervals touching the window
    boundary are flagged truncated. Tangential contacts (grazing the mask
    without exceeding it) never produce intervals. Visibility windows
    shorter than the 1 s grid step may be missed.
    """
    results: list[PassInterval] = []
    n_steps = int((t1 - t0).total_seconds() / GRID_STEP_S)
    times = [t0 + timedelta(seconds=i * GRID_STEP_S) for i in range(n_steps + 1)]
    for tle in tles:
        for site in sites:
            results.extend(_find_passes_pair(tle, site, times, t0, t1))
    results.sort(key=lambda p: (p.start, p.sat_id))
    return results


def _find_passes_pair(tle, site, times, t0, t1) -> list[PassInterval]:
    margins = [elevation_minus_mask(tle, site, t) for t in times]
    intervals: list[PassInterval] = []
    i = 0
    n = len(times)
    while i < n:
        if margins[i] > 0.0:
            # interval start
            if i == 0:
                start, trunc_start = times[0], True
            else:
                start = _bisect_crossing(tle, site, times[i], times[i - 1])
                trunc_start = False
            j = i
            while j + 1 < n and margins[j + 1] > 0.0:
                j += 1
            if j == n - 1:
                end, trunc_end = times[-1], True
            else:
                end = _bisect_crossing(tle, site, times[j], times[j + 1])
                trunc_end = False
            intervals.append(_build_interval(tle, site, start, end,
                                             trunc_start, trunc_end))
            i = j + 1
        else:
            i += 1
    return intervals


def _build_interval(tle, site, start, end, trunc_start, trunc_end) -> PassInterval:
    # max elevation sampled once per second within the interval
    duration = (end - start).total_seconds()
    n = max(1, int(duration))
    best_el = -math.inf
    best_t = start
    for k in range(n + 1):
        t = start + timedelta(seconds=k)
        if t > end:
            t = end
        _, el, _ = look(tle, site, t)
        if el > best_el:
            best_el = el
            best_t = t
    return PassInterval(
        sat_id=tle.sat_id,
        site=site.name,
        start=start,
        end=end,
        truncated_start=trunc_start,
        truncated_end=trunc_end,
        max_el_deg=best_el,
        max_el_time=best_t,
    )

