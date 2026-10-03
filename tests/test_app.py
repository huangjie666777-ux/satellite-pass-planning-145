import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.coords import geodetic_to_ecef, gmst_rad, look_angles
from app.main import app
from app.passes import Site, mask_elevation
from app.tle import TLEError, parse_tle

REQ = json.load(open("examples/request.json"))
client = TestClient(app)


def test_tle_ok():
    t = parse_tle("ISS", REQ["satellites"][0]["line1"], REQ["satellites"][0]["line2"])
    assert t.sat_id == "25544"
    assert t.epoch.year == 2026 and t.epoch.month == 10 and t.epoch.day == 1


def test_tle_bad_checksum():
    bad = REQ["satellites"][0]["line1"][:68] + "0"
    if bad == REQ["satellites"][0]["line1"]:
        bad = bad[:68] + "1"
    with pytest.raises(TLEError):
        parse_tle("ISS", bad, REQ["satellites"][0]["line2"])


def test_tle_bad_width():
    with pytest.raises(TLEError):
        parse_tle("ISS", REQ["satellites"][0]["line1"][:-2], REQ["satellites"][0]["line2"])


def test_tle_number_mismatch():
    l2 = REQ["satellites"][0]["line2"]
    l2 = "2 25545" + l2[7:68]
    total = sum(int(c) if c.isdigit() else 1 if c == "-" else 0 for c in l2)
    l2 = l2 + str(total % 10)
    with pytest.raises(TLEError):
        parse_tle("ISS", REQ["satellites"][0]["line1"], l2)


def test_mask_interpolation_wraps():
    mask = [(350.0, 10.0), (10.0, 20.0)]
    assert mask_elevation(mask, 0.0) == pytest.approx(15.0)
    assert mask_elevation(mask, 355.0) == pytest.approx(12.5)
    assert mask_elevation(mask, 180.0) == pytest.approx(15.0)


def test_look_angles_zenith():
    # satellite directly overhead at 400 km altitude -> el 90, range ~400 km
    lat, lon, alt = 10.0, 20.0, 0.0
    sat = geodetic_to_ecef(lat, lon, 400000.0)
    az, el, rng = look_angles(sat, lat, lon, alt)
    assert el == pytest.approx(90.0, abs=1e-6)
    assert rng == pytest.approx(400000.0, rel=1e-3)


def test_gmst_j2000():
    g = gmst_rad(datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    assert g == pytest.approx(280.46061837 * 3.141592653589793 / 180.0, abs=1e-10)


def _post(payload):
    return client.post("/passes", json=payload)


def test_predict_endpoint():
    r = _post(REQ)
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["intervals"]) >= 1
    iv = data["intervals"][0]
    assert iv["duration_s"] > 0
    assert 0 <= iv["max_elevation_deg"] <= 90


def test_duplicate_id_rejected():
    bad = dict(REQ)
    bad["satellites"] = REQ["satellites"] * 2
    r = _post(bad)
    assert r.status_code == 422


def test_bad_lat_rejected():
    bad = json.loads(json.dumps(REQ))
    bad["sites"][0]["lat_deg"] = 91.0
    assert _post(bad).status_code == 422
    bad["sites"][0]["lat_deg"] = float("nan")
    body = json.dumps(bad, allow_nan=True)  # non-finite must be rejected
    r = client.post("/passes", content=body,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_window_too_long():
    bad = json.loads(json.dumps(REQ))
    bad["window"]["end_utc"] = "2026-10-03T00:00:01Z"
    assert _post(bad).status_code == 422


def test_stale_epoch_rejected():
    bad = json.loads(json.dumps(REQ))
    bad["window"] = {"start_utc": "2026-11-01T00:00:00Z", "end_utc": "2026-11-01T01:00:00Z"}
    assert _post(bad).status_code == 422


def test_download_zip():
    import io, zipfile
    r = client.post("/passes/download", json=REQ)
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "summary.json" in names
    csvs = [n for n in names if n.endswith(".csv")]
    assert csvs
    head = zf.read(csvs[0]).decode().splitlines()[0]
    assert "doppler_shift_hz" in head
