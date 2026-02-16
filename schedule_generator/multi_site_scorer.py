"""
AstriaNet Schedule Generator — Multi-Site Scorer
Ranks satellite passes by multi-site observability and science value,
then builds conflict-free per-site schedules with nighttime filtering.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from config import (
    DEFAULT_MAX_OBS_PER_NIGHT,
    MIN_GAP_MINUTES,
    MULTI_SITE_SEQUENTIAL_HOURS,
    SUN_ALTITUDE_THRESHOLD,
    TIER_WEIGHTS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Nighttime filtering
# ---------------------------------------------------------------------------

def compute_dark_windows(site_cfg, t_start_utc, t_end_utc):
    # type: (dict, datetime, datetime) -> list
    """
    Return list of (dark_start_utc, dark_end_utc) intervals where sun
    altitude < SUN_ALTITUDE_THRESHOLD at the site.

    Uses Skyfield ephemeris for accuracy.
    """
    from skyfield.api import wgs84
    from pass_predictor import get_timescale, get_ephemeris

    ts = get_timescale()
    eph = get_ephemeris()
    sun = eph["sun"]
    earth = eph["earth"]

    observer = earth + wgs84.latlon(
        site_cfg["lat"], site_cfg["lon"], site_cfg["alt_m"]
    )

    # Sample at 5-minute intervals to find dark windows
    step_minutes = 5
    t_current = t_start_utc
    dark_windows = []
    in_dark = False
    dark_start = None

    while t_current <= t_end_utc:
        t_sky = ts.from_datetime(t_current)
        sun_pos = observer.at(t_sky).observe(sun).apparent()
        alt, _, _ = sun_pos.altaz()

        if alt.degrees < SUN_ALTITUDE_THRESHOLD:
            if not in_dark:
                dark_start = t_current
                in_dark = True
        else:
            if in_dark:
                dark_windows.append((dark_start, t_current))
                in_dark = False

        t_current += timedelta(minutes=step_minutes)

    # If still dark at end of window
    if in_dark:
        dark_windows.append((dark_start, t_end_utc))

    return dark_windows


def is_pass_during_darkness(pass_info, dark_windows):
    # type: (dict, list) -> bool
    """Check if a pass's midpoint falls within a dark window."""
    mid = pass_info["rise_utc"] + (
        pass_info["set_utc"] - pass_info["rise_utc"]
    ) / 2
    for dstart, dend in dark_windows:
        if dstart <= mid <= dend:
            return True
    return False


def filter_nighttime(passes, dark_windows):
    # type: (list, list) -> list
    """Filter passes to only those during astronomical darkness."""
    filtered = [p for p in passes if is_pass_during_darkness(p, dark_windows)]
    logger.info(
        "Nighttime filter: %d → %d passes", len(passes), len(filtered)
    )
    return filtered


# ---------------------------------------------------------------------------
# Multi-site opportunity detection
# ---------------------------------------------------------------------------

def find_multi_site_opportunities(all_passes):
    # type: (dict) -> dict
    """
    Group passes across sites by NORAD ID and detect multi-site opportunities.

    Args:
        all_passes: {site_id: [pass_dict, ...]}

    Returns:
        {norad_id: {"sites": set, "simultaneous": bool, "sequential": bool,
                     "passes": {site_id: [pass_dict, ...]}}}
    """
    # Group by NORAD ID across all sites
    by_norad = defaultdict(lambda: defaultdict(list))
    for site_id, passes in all_passes.items():
        for p in passes:
            by_norad[p["norad_id"]][site_id].append(p)

    opportunities = {}
    for norad_id, site_passes in by_norad.items():
        sites_visible = set(site_passes.keys())
        simultaneous = False
        sequential = False

        if len(sites_visible) >= 2:
            # Check for simultaneous (overlapping) passes
            all_intervals = []
            for sid, plist in site_passes.items():
                for p in plist:
                    all_intervals.append((p["rise_utc"], p["set_utc"], sid))

            # Check pairwise overlap
            for i in range(len(all_intervals)):
                for j in range(i + 1, len(all_intervals)):
                    if all_intervals[i][2] != all_intervals[j][2]:
                        # Different sites — check overlap
                        latest_start = max(all_intervals[i][0], all_intervals[j][0])
                        earliest_end = min(all_intervals[i][1], all_intervals[j][1])
                        if latest_start < earliest_end:
                            simultaneous = True
                            break
                if simultaneous:
                    break

            # Check for sequential (within N hours)
            if not simultaneous:
                flat_times = []
                for sid, plist in site_passes.items():
                    for p in plist:
                        flat_times.append((p["max_el_utc"], sid))
                flat_times.sort(key=lambda x: x[0])
                seq_window = timedelta(hours=MULTI_SITE_SEQUENTIAL_HOURS)
                for i in range(len(flat_times)):
                    for j in range(i + 1, len(flat_times)):
                        if flat_times[i][1] != flat_times[j][1]:
                            if (flat_times[j][0] - flat_times[i][0]) <= seq_window:
                                sequential = True
                                break
                    if sequential:
                        break

        opportunities[norad_id] = {
            "sites": sites_visible,
            "simultaneous": simultaneous,
            "sequential": sequential,
            "passes": dict(site_passes),
        }

    multi_ct = sum(1 for v in opportunities.values() if len(v["sites"]) >= 2)
    logger.info(
        "Multi-site analysis: %d unique objects, %d visible from 2+ sites",
        len(opportunities), multi_ct,
    )
    return opportunities


# ---------------------------------------------------------------------------
# Pass scoring
# ---------------------------------------------------------------------------

def score_pass(pass_info, num_sites_visible):
    # type: (dict, int) -> float
    """
    Compute a priority score for a single pass.

    score = tier_weight × num_sites × (max_el / 90) × min(duration_min / 5, 1.0)
    """
    tier_weight = TIER_WEIGHTS.get(pass_info["tier"], 1.0)
    site_factor = float(num_sites_visible)
    el_factor = pass_info["max_el_deg"] / 90.0
    dur_min = pass_info["duration_sec"] / 60.0
    dur_factor = min(dur_min / 5.0, 1.0)

    return tier_weight * site_factor * el_factor * dur_factor


# ---------------------------------------------------------------------------
# Schedule builder (greedy, per-site)
# ---------------------------------------------------------------------------

def build_schedule(passes, opportunities, site_id, max_obs=None):
    # type: (list, dict, str, int) -> list
    """
    Build a conflict-free, score-sorted schedule for one site.

    Args:
        passes: list of pass dicts for this site (already nighttime-filtered)
        opportunities: multi-site opportunity dict from find_multi_site_opportunities()
        site_id: the site being scheduled
        max_obs: maximum observations per night

    Returns:
        Sorted list of scheduled pass dicts with added "score" key.
    """
    if max_obs is None:
        max_obs = DEFAULT_MAX_OBS_PER_NIGHT

    gap = timedelta(minutes=MIN_GAP_MINUTES)

    # Score each pass
    scored = []
    for p in passes:
        nid = p["norad_id"]
        opp = opportunities.get(nid, {})
        num_sites = len(opp.get("sites", {site_id}))
        s = score_pass(p, num_sites)
        p_copy = dict(p)
        p_copy["score"] = round(s, 4)
        p_copy["multi_site"] = num_sites >= 2
        scored.append(p_copy)

    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Greedy schedule
    scheduled = []
    for p in scored:
        if len(scheduled) >= max_obs:
            break

        # Check for conflicts with already-scheduled passes
        conflict = False
        for sp in scheduled:
            # Check if this pass's window overlaps with any scheduled pass + gap
            if (p["rise_utc"] < sp["set_utc"] + gap and
                    p["set_utc"] > sp["rise_utc"] - gap):
                conflict = True
                break

        if not conflict:
            scheduled.append(p)

    # Sort final schedule chronologically
    scheduled.sort(key=lambda x: x["rise_utc"])

    multi_ct = sum(1 for p in scheduled if p.get("multi_site", False))
    logger.info(
        "[%s] Schedule: %d observations (%d multi-site) from %d candidates",
        site_id, len(scheduled), multi_ct, len(passes),
    )
    return scheduled
