"""TLE parsing and validation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sgp4.api import Satrec

TLE_LINE_WIDTH = 69
MAX_EPOCH_AGE_DAYS = 7.0


class TLEError(ValueError):
    """Raised when a TLE fails validation."""


def _checksum_ok(line: str) -> bool:
    check_char = line[68]
    if not check_char.isdigit():
        return False
    total = 0
    for ch in line[:68]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10 == int(check_char)


def _validate_line(line: str, expected_no: str) -> str:
    if len(line) != TLE_LINE_WIDTH:
        raise TLEError(
            f"TLE line must be exactly {TLE_LINE_WIDTH} characters, got {len(line)}"
        )
    if line[0] != expected_no:
        raise TLEError(f"expected TLE line {expected_no}, got {line[0]!r}")
    if not _checksum_ok(line):
        raise TLEError(f"TLE line {expected_no} checksum mismatch")
    return line


@dataclass
class TLEData:
    sat_id: str
    line1: str
    line2: str
    epoch: datetime
    sat: Satrec


def parse_tle(name: str, line1: str, line2: str) -> TLEData:
    line1 = _validate_line(line1.rstrip("\n"), "1")
    line2 = _validate_line(line2.rstrip("\n"), "2")
    num1 = line1[2:7].strip()
    num2 = line2[2:7].strip()
    if num1 != num2:
        raise TLEError(
            f"satellite number mismatch between lines: {num1} vs {num2}"
        )
    sat = Satrec.twoline2rv(line1, line2)
    if sat.error != 0:
        raise TLEError(f"SGP4 rejected TLE (error {sat.error})")
    year = sat.epochyr + (1900 if sat.epochyr >= 57 else 2000)
    epoch = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=sat.epochdays - 1
    )
    return TLEData(sat_id=num1, line1=line1, line2=line2, epoch=epoch, sat=sat)


def check_epoch_freshness(tles: list[TLEData], now: datetime) -> None:
    for t in tles:
        age_days = abs((now - t.epoch).total_seconds()) / 86400.0
        if age_days > MAX_EPOCH_AGE_DAYS:
            raise TLEError(
                f"satellite {t.sat_id}: query is {age_days:.1f} days from TLE epoch "
                f"(limit {MAX_EPOCH_AGE_DAYS})"
            )


def check_unique_ids(tles: list[TLEData]) -> None:
    seen: set[str] = set()
    for t in tles:
        if t.sat_id in seen:
            raise TLEError(f"duplicate satellite id {t.sat_id}")
        seen.add(t.sat_id)
