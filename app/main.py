"""FastAPI entry point for the offline satellite pass prediction backend."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from .delivery import build_zip, interval_summary, track_csv
from .passes import Site, find_passes
from .tle import (
    TLEError,
    check_epoch_freshness,
    check_unique_ids,
    parse_tle,
)

MAX_SATELLITES = 4
MAX_SITES = 4
MAX_WINDOW_H = 24.0

app = FastAPI(title="Offline Pass Predictor", version="1.0.0")


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc):
    # sanitize errors: non-finite inputs cannot be JSON-serialized
    details = [
        {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", ""))}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


class TLEIn(BaseModel):
    name: str = ""
    line1: str
    line2: str


class MaskNode(BaseModel):
    azimuth_deg: float
    min_elevation_deg: float

    @field_validator("azimuth_deg", "min_elevation_deg")
    @classmethod
    def _finite(cls, v: float) -> float:
        import math
        if not math.isfinite(v):
            raise ValueError("mask values must be finite")
        return v


class SiteIn(BaseModel):
    name: str
    lat_deg: float = Field(ge=-90.0, le=90.0)
    lon_deg: float = Field(ge=-180.0, le=180.0)
    alt_m: float = 0.0
    mask: list[MaskNode] = []

    @field_validator("lat_deg", "lon_deg", "alt_m")
    @classmethod
    def _finite(cls, v: float) -> float:
        import math
        if not math.isfinite(v):
            raise ValueError("coordinates must be finite")
        return v


class Window(BaseModel):
    start_utc: datetime
    end_utc: datetime


class PredictRequest(BaseModel):
    satellites: list[TLEIn] = Field(min_length=1, max_length=MAX_SATELLITES)
    sites: list[SiteIn] = Field(min_length=1, max_length=MAX_SITES)
    window: Window
    downlink_frequency_hz: float = Field(gt=0.0)

    @field_validator("downlink_frequency_hz")
    @classmethod
    def _finite_freq(cls, v: float) -> float:
        import math
        if not math.isfinite(v):
            raise ValueError("frequency must be finite")
        return v


def _prepare(req: PredictRequest):
    start = req.window.start_utc
    end = req.window.end_utc
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start:
        raise HTTPException(422, "window end_utc must be after start_utc")
    span_h = (end - start).total_seconds() / 3600.0
    if span_h > MAX_WINDOW_H:
        raise HTTPException(422, f"window exceeds {MAX_WINDOW_H} hours")
    try:
        tles = [parse_tle(s.name, s.line1, s.line2) for s in req.satellites]
        check_unique_ids(tles)
        check_epoch_freshness(tles, start)
    except TLEError as exc:
        raise HTTPException(422, str(exc))
    sites = [
        Site(
            name=s.name,
            lat_deg=s.lat_deg,
            lon_deg=s.lon_deg,
            alt_m=s.alt_m,
            mask=sorted(
                ((m.azimuth_deg % 360.0, m.min_elevation_deg) for m in s.mask)
            ),
        )
        for s in req.sites
    ]
    return tles, sites, start, end


def _run(req: PredictRequest):
    tles, sites, start, end = _prepare(req)
    try:
        passes = find_passes(tles, sites, start, end)
    except Exception as exc:
        # propagation failure fails the whole request
        raise HTTPException(500, f"propagation failed: {exc}")
    tle_by_id = {t.sat_id: t for t in tles}
    site_by_name = {s.name: s for s in sites}
    return tle_by_id, site_by_name, passes


@app.post("/passes")
def predict(req: PredictRequest):
    _, _, passes = _run(req)
    return {
        "units": {
            "angles": "deg",
            "azimuth": "deg clockwise from true north",
            "distance": "km",
            "range_rate": "km/s",
            "doppler_shift": "Hz (negative when range increases)",
            "time": "UTC ISO8601",
        },
        "intervals": [interval_summary(p) for p in passes],
        "notes": [
            "UTC used as UT1; no polar motion, refraction or light-time.",
            "1 s search grid: visibility windows shorter than 1 s may be missed.",
            "Tangential (grazing) contacts do not count as intervals.",
        ],
    }


@app.post("/passes/download")
def predict_download(req: PredictRequest):
    tle_by_id, site_by_name, passes = _run(req)
    summary = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "downlink_frequency_hz": req.downlink_frequency_hz,
        "intervals": [interval_summary(p) for p in passes],
    }
    tracks = [
        (
            p,
            track_csv(
                tle_by_id[p.sat_id],
                site_by_name[p.site],
                p,
                req.downlink_frequency_hz,
            ),
        )
        for p in passes
    ]
    payload = build_zip(summary, tracks)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="passes.zip"'},
    )
