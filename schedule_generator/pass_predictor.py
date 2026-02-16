"""
AstriaNet Schedule Generator — Pass Predictor
Uses Skyfield + SGP4 to compute satellite passes over each observatory site.
"""

import logging
import os
from datetime import datetime, timedelta

from skyfield.api import EarthSatellite, load, wgs84

from config import SITES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Skyfield loader — caches ephemeris and timescale files locally
# ---------------------------------------------------------------------------
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

def _get_loader():
    # type: () -> load
    """Return a Skyfield Loader that stores data in our cache dir."""
    if not os.path.isdir(_DATA_DIR):
        os.makedirs(_DATA_DIR)
    return load  # Skyfield's default loader; we set its directory below


def get_timescale():
    """Return Skyfield timescale object."""
    return load.timescale(builtin=True)


def get_ephemeris():
    """Return the Sun ephemeris for solar-altitude calculations."""
    eph_path = os.path.join(_DATA_DIR, "de421.bsp")
    if os.path.isfile(eph_path):
        return load(eph_path)
    # Download to cache directory
    return load("de421.bsp")


# ---------------------------------------------------------------------------
# Build Skyfield satellite objects from catalog entries
# ---------------------------------------------------------------------------

def _build_satellite(sat_dict, ts):
    # type: (dict, object) -> EarthSatellite
    """Create a Skyfield EarthSatellite from a catalog dict entry."""
    try:
        return EarthSatellite(
            sat_dict["tle_line1"],
            sat_dict["tle_line2"],
            sat_dict["name"],
            ts,
        )
    except Exception as e:
        logger.debug("Cannot build satellite %s: %s", sat_dict.get("name", "?"), e)
        return None


# ---------------------------------------------------------------------------
# Pass prediction for one site
# ---------------------------------------------------------------------------

def predict_passes_for_site(catalog, site_id, t_start_utc, t_end_utc, min_elevation=None):
    # type: (list, str, datetime, datetime, float) -> list
    """
    Compute all satellite passes over a site in [t_start_utc, t_end_utc].

    Returns a list of pass dicts:
        {
            "norad_id": int,
            "name": str,
            "tle_line1": str,
            "tle_line2": str,
            "tier": int,
            "site_id": str,
            "rise_utc": datetime,
            "set_utc": datetime,
            "max_el_utc": datetime,
            "max_el_deg": float,
            "duration_sec": float,
        }
    """
    site_cfg = SITES[site_id]
    if min_elevation is None:
        min_elevation = site_cfg["min_elevation"]

    ts = get_timescale()
    observer = wgs84.latlon(site_cfg["lat"], site_cfg["lon"], site_cfg["alt_m"])

    t0 = ts.from_datetime(t_start_utc)
    t1 = ts.from_datetime(t_end_utc)

    passes = []
    skipped = 0

    for idx, sat_dict in enumerate(catalog):
        if idx % 500 == 0 and idx > 0:
            logger.info(
                "  [%s] Processed %d / %d satellites (%d passes found so far)",
                site_id, idx, len(catalog), len(passes),
            )

        sat = _build_satellite(sat_dict, ts)
        if sat is None:
            skipped += 1
            continue

        try:
            t_events, events = sat.find_events(
                observer, t0, t1, altitude_degrees=min_elevation
            )
        except Exception as e:
            logger.debug("find_events failed for %s: %s", sat_dict["name"], e)
            skipped += 1
            continue

        if len(t_events) == 0:
            continue

        # Events come in triplets: 0=rise, 1=culminate, 2=set
        # Walk through and group them
        i = 0
        while i < len(events):
            # Find next rise event
            if events[i] != 0:
                i += 1
                continue

            rise_t = t_events[i]
            max_el_t = None
            max_el_deg = min_elevation
            set_t = None

            j = i + 1
            while j < len(events):
                if events[j] == 1:  # culminate
                    max_el_t = t_events[j]
                    # Compute actual max elevation
                    try:
                        diff = sat - observer
                        topo = diff.at(max_el_t)
                        alt, _, _ = topo.altaz()
                        max_el_deg = alt.degrees
                    except Exception:
                        pass
                elif events[j] == 2:  # set
                    set_t = t_events[j]
                    break
                elif events[j] == 0:  # another rise — previous pass was incomplete
                    break
                j += 1

            if set_t is not None:
                rise_dt = rise_t.utc_datetime()
                set_dt = set_t.utc_datetime()
                max_el_dt = max_el_t.utc_datetime() if max_el_t else rise_dt
                duration = (set_dt - rise_dt).total_seconds()

                if duration > 5:  # skip trivially short passes (< 5 seconds)
                    passes.append({
                        "norad_id": sat_dict["norad_id"],
                        "name": sat_dict["name"],
                        "tle_line1": sat_dict["tle_line1"],
                        "tle_line2": sat_dict["tle_line2"],
                        "tier": sat_dict["tier"],
                        "site_id": site_id,
                        "rise_utc": rise_dt,
                        "set_utc": set_dt,
                        "max_el_utc": max_el_dt,
                        "max_el_deg": round(max_el_deg, 2),
                        "duration_sec": round(duration, 1),
                    })

            i = j + 1

    logger.info(
        "[%s] Pass prediction complete: %d passes from %d satellites (%d skipped)",
        site_id, len(passes), len(catalog), skipped,
    )
    return passes


def predict_passes_all_sites(catalog, site_ids, t_start_utc, t_end_utc, min_elevation=None):
    # type: (list, list, datetime, datetime, float) -> dict
    """
    Predict passes for multiple sites.

    Returns:
        { site_id: [pass_dict, ...], ... }
    """
    all_passes = {}
    for sid in site_ids:
        logger.info("Computing passes for site: %s", sid)
        all_passes[sid] = predict_passes_for_site(
            catalog, sid, t_start_utc, t_end_utc, min_elevation
        )
    return all_passes
