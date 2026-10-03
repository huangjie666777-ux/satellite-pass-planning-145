"""Coordinate transforms: TEME -> ECEF (approximate), geodetic -> ECEF, look angles.

Approximations: UTC used as UT1, no polar motion, no refraction, no light-time.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

# WGS84 ellipsoid
WGS84_A = 6378137.0            # semi-major axis, m
WGS84_F = 1.0 / 298.257223563  # flattening
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

DEG = math.pi / 180.0


def gmst_rad(dt: datetime) -> float:
    """Greenwich mean sidereal time (IAU 1982), UTC approximating UT1."""
    dt = dt.astimezone(timezone.utc)
    j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    d = (dt - j2000).total_seconds() / 86400.0
    gmst_deg = 280.46061837 + 360.98564736629 * d
    return math.radians(gmst_deg % 360.0)


def teme_to_ecef(r_teme_km: tuple, dt: datetime) -> tuple:
    """Rotate TEME (km) to ECEF (m) by GMST only (no polar motion/nutation)."""
    g = gmst_rad(dt)
    x, y, z = r_teme_km
    cosg, sing = math.cos(g), math.sin(g)
    return (
        (x * cosg + y * sing) * 1000.0,
        (-x * sing + y * cosg) * 1000.0,
        z * 1000.0,
    )


def geodetic_to_ecef(lat_deg: float, lon_deg: float, alt_m: float) -> tuple:
    lat = lat_deg * DEG
    lon = lon_deg * DEG
    sin_lat = math.sin(lat)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + alt_m) * math.cos(lat) * math.cos(lon)
    y = (n + alt_m) * math.cos(lat) * math.sin(lon)
    z = (n * (1.0 - WGS84_E2) + alt_m) * sin_lat
    return (x, y, z)


def look_angles(
    sat_ecef_m: tuple, lat_deg: float, lon_deg: float, alt_m: float
) -> tuple:
    """Return (azimuth_deg, elevation_deg, slant_range_m).

    Azimuth measured clockwise from true north.
    """
    sx, sy, sz = sat_ecef_m
    ox, oy, oz = geodetic_to_ecef(lat_deg, lon_deg, alt_m)
    dx, dy, dz = sx - ox, sy - oy, sz - oz
    lat = lat_deg * DEG
    lon = lon_deg * DEG
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    # ENU basis
    east = -sin_lon * dx + cos_lon * dy
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    rng = math.sqrt(east * east + north * north + up * up)
    el = math.degrees(math.asin(up / rng))
    az = math.degrees(math.atan2(east, north)) % 360.0
    return (az, el, rng)

