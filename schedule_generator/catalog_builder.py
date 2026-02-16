"""
AstriaNet Schedule Generator — Catalog Builder
Fetches satellite TLE data from CelesTrak, filters to LEO, assigns science tiers,
and caches results locally.
"""

import json
import logging
import math
import os
import re
import time
from datetime import datetime, timedelta

import pytz
import requests

# Identifiable User-Agent per CelesTrak policy (Dr. Kelso recommends this)
_USER_AGENT = "AstriaNet-ScheduleGenerator/1.0 (satellite-ops; contact@astrianet.org)"

from config import (
    CACHE_CATALOG_FILE,
    CACHE_DIR,
    CACHE_TIMESTAMP_FILE,
    CACHE_TTL_SECONDS,
    CELESTRAK_URLS,
    DEBRIS_KEYWORDS,
    MAX_EPOCH_AGE_DAYS,
    MIN_MEAN_MOTION,
    TIER1_NDOT_THRESHOLD,
    TIER3_PERIGEE_KM,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TLE field extraction helpers
# ---------------------------------------------------------------------------

def _parse_tle_epoch(line1):
    # type: (str) -> datetime
    """Parse TLE epoch from line 1 (cols 18-32): YYDDD.DDDDDDDD."""
    epoch_str = line1[18:32].strip()
    year_2d = int(epoch_str[:2])
    year = 2000 + year_2d if year_2d < 57 else 1900 + year_2d
    day_frac = float(epoch_str[2:])
    return datetime(year, 1, 1) + timedelta(days=day_frac - 1)


def _parse_ndot(line1):
    # type: (str) -> float
    """Parse mean motion first derivative (ṅ/2) from line 1 cols 33-43."""
    raw = line1[33:43].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_mean_motion(line2):
    # type: (str) -> float
    """Parse mean motion (rev/day) from line 2 cols 52-63."""
    raw = line2[52:63].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_inclination(line2):
    # type: (str) -> float
    """Parse inclination (degrees) from line 2 cols 8-16."""
    raw = line2[8:16].strip()
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _parse_eccentricity(line2):
    # type: (str) -> float
    """Parse eccentricity from line 2 cols 26-33 (implied leading '0.')."""
    raw = line2[26:33].strip()
    try:
        return float("0." + raw)
    except ValueError:
        return 0.0


def _compute_perigee_km(mean_motion, eccentricity):
    # type: (float, float) -> float
    """Derive approximate perigee altitude from mean motion and eccentricity."""
    if mean_motion <= 0:
        return 99999.0
    MU = 398600.4418       # km³/s²  (Earth GM)
    R_EARTH = 6371.0       # km
    period_sec = 86400.0 / mean_motion
    a = (MU * (period_sec / (2.0 * math.pi)) ** 2) ** (1.0 / 3.0)
    perigee = a * (1.0 - eccentricity) - R_EARTH
    return max(perigee, 0.0)


def _parse_norad_id(line1):
    # type: (str) -> int
    """Parse NORAD catalog number from line 1 cols 2-7."""
    raw = line1[2:7].strip()
    try:
        return int(raw)
    except ValueError:
        return 0


# ---------------------------------------------------------------------------
# TLE text file parsing (3-line format: name / line1 / line2)
# ---------------------------------------------------------------------------

def parse_tle_text(text):
    # type: (str) -> list
    """Parse raw CelesTrak 3-line TLE text into a list of (name, line1, line2)."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    entries = []
    i = 0
    while i + 2 < len(lines):
        # Line 1 starts with '1 ', line 2 with '2 '
        if lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name = lines[i].strip()
            line1 = lines[i + 1]
            line2 = lines[i + 2]
            entries.append((name, line1, line2))
            i += 3
        else:
            i += 1
    return entries


# ---------------------------------------------------------------------------
# Tier assignment
# ---------------------------------------------------------------------------

def assign_tier(name, ndot, perigee_km):
    # type: (str, float, float) -> int
    """Assign a science priority tier (1-4) to a satellite."""
    # Tier 1: high-drag / decaying
    if ndot > TIER1_NDOT_THRESHOLD:
        return 1

    # Tier 2: debris / rocket bodies (name heuristics)
    name_upper = name.upper()
    for kw in DEBRIS_KEYWORDS:
        if kw in name_upper:
            return 2

    # Tier 3: active payloads in low LEO
    if perigee_km < TIER3_PERIGEE_KM:
        return 3

    # Tier 4: everything else
    return 4


# ---------------------------------------------------------------------------
# Catalog building
# ---------------------------------------------------------------------------

def fetch_tle_catalog(force_refresh=False):
    # type: (bool) -> list
    """Fetch TLE catalog from CelesTrak, merge all groups, deduplicate."""
    all_entries = {}  # norad_id -> (name, line1, line2)

    for group_name, url in CELESTRAK_URLS.items():
        logger.info("Fetching CelesTrak group: %s", group_name)
        try:
            resp = requests.get(
                url, timeout=60,
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
            entries = parse_tle_text(resp.text)
            logger.info("  → %d TLEs from %s", len(entries), group_name)
            for name, line1, line2 in entries:
                nid = _parse_norad_id(line1)
                if nid > 0:
                    all_entries[nid] = (name, line1, line2)
        except requests.RequestException as e:
            logger.warning("Failed to fetch %s: %s", group_name, e)

    logger.info("Total unique TLEs fetched: %d", len(all_entries))
    return list(all_entries.values())


def filter_catalog(raw_entries):
    # type: (list) -> list
    """Filter raw TLE entries to interesting LEO objects and enrich with metadata."""
    now = datetime.now(pytz.utc).replace(tzinfo=None)
    catalog = []

    for name, line1, line2 in raw_entries:
        # --- Parse fields ---
        mean_motion = _parse_mean_motion(line2)
        ndot = _parse_ndot(line1)
        inclination = _parse_inclination(line2)
        eccentricity = _parse_eccentricity(line2)
        norad_id = _parse_norad_id(line1)
        perigee_km = _compute_perigee_km(mean_motion, eccentricity)

        # --- LEO filter ---
        if mean_motion < MIN_MEAN_MOTION:
            continue

        # --- Epoch freshness ---
        try:
            epoch = _parse_tle_epoch(line1)
            age_days = (now - epoch).total_seconds() / 86400.0
            if age_days > MAX_EPOCH_AGE_DAYS:
                continue
        except Exception:
            continue  # skip unparseable epochs

        # --- Tier ---
        tier = assign_tier(name, ndot, perigee_km)

        catalog.append({
            "norad_id": norad_id,
            "name": name,
            "tle_line1": line1,
            "tle_line2": line2,
            "tier": tier,
            "mean_motion": round(mean_motion, 8),
            "ndot": ndot,
            "perigee_km": round(perigee_km, 1),
            "inclination": round(inclination, 4),
        })

    logger.info(
        "Catalog filtered: %d → %d LEO objects",
        len(raw_entries),
        len(catalog),
    )
    return catalog


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def _cache_path(filename):
    # type: (str) -> str
    """Return absolute path to a cache file, creating the dir if needed."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), CACHE_DIR)
    if not os.path.isdir(base):
        os.makedirs(base)
    return os.path.join(base, filename)


def _cache_is_fresh():
    # type: () -> bool
    """Check if the local catalog cache is still within TTL."""
    ts_path = _cache_path(CACHE_TIMESTAMP_FILE)
    if not os.path.isfile(ts_path):
        return False
    try:
        with open(ts_path, "r") as f:
            ts = float(f.read().strip())
        return (time.time() - ts) < CACHE_TTL_SECONDS
    except (ValueError, IOError):
        return False


def _write_cache(catalog):
    # type: (list) -> None
    """Write catalog to local JSON cache."""
    cat_path = _cache_path(CACHE_CATALOG_FILE)
    ts_path = _cache_path(CACHE_TIMESTAMP_FILE)
    with open(cat_path, "w") as f:
        json.dump(catalog, f)
    with open(ts_path, "w") as f:
        f.write(str(time.time()))
    logger.info("Catalog cached to %s", cat_path)


def _read_cache():
    # type: () -> list
    """Read catalog from local JSON cache."""
    cat_path = _cache_path(CACHE_CATALOG_FILE)
    with open(cat_path, "r") as f:
        return json.load(f)


def load_or_fetch_catalog(force_refresh=False):
    # type: (bool) -> tuple
    """Return (catalog, total_fetched, total_filtered).

    Uses cache when fresh.  When returning from cache, total_fetched is
    set to -1 (unknown) to distinguish from a live fetch.
    """
    if not force_refresh and _cache_is_fresh():
        logger.info("Using cached catalog (TTL OK)")
        try:
            cached = _read_cache()
            return cached, -1, len(cached)
        except Exception as e:
            logger.warning("Cache read failed, re-fetching: %s", e)

    raw = fetch_tle_catalog(force_refresh=force_refresh)
    total_fetched = len(raw)
    catalog = filter_catalog(raw)
    _write_cache(catalog)
    return catalog, total_fetched, len(catalog)


# ---------------------------------------------------------------------------
# Convenience: standalone run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cat = load_or_fetch_catalog(force_refresh=True)
    tier_counts = {}
    for sat in cat:
        tier_counts[sat["tier"]] = tier_counts.get(sat["tier"], 0) + 1
    print("Catalog size: %d" % len(cat))
    print("Tier breakdown: %s" % tier_counts)
