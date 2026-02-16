"""
AstriaNet Schedule Generator — Plan Writer
Outputs per-site tleplan.txt files and schedule_summary.json in the exact
format consumed by automated2.py / pwi4_tle_observer.py.
"""

import json
import logging
import os
import shutil
from datetime import datetime, timedelta

import pytz

from config import DEFAULT_OBSERVATION_WINDOW_MIN, SITES

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Observation window calculation
# ---------------------------------------------------------------------------

def _observation_window(pass_info, window_minutes):
    # type: (dict, object) -> tuple
    """
    Compute the actual observation [begin, end] for a pass.

    If window_minutes == "full", use the entire pass.
    Otherwise, center the window on the pass midpoint.
    """
    rise = pass_info["rise_utc"]
    set_ = pass_info["set_utc"]

    if window_minutes == "full":
        return rise, set_

    half = timedelta(minutes=float(window_minutes) / 2.0)
    midpoint = rise + (set_ - rise) / 2
    begin = max(midpoint - half, rise)
    end = min(midpoint + half, set_)
    return begin, end


# ---------------------------------------------------------------------------
# Format a single observation block
# ---------------------------------------------------------------------------

def _format_entry(pass_info, begin_local, end_local):
    # type: (dict, datetime, datetime) -> str
    """Format one observation block for tleplan.txt."""
    lines = [
        "BEGINLOCAL %s" % begin_local.strftime("%Y-%m-%d %H:%M:%S"),
        "ENDLOCAL %s" % end_local.strftime("%Y-%m-%d %H:%M:%S"),
        "NAME %s" % pass_info["name"],
        "0 %s" % pass_info["name"],
        pass_info["tle_line1"],
        pass_info["tle_line2"],
        "",  # blank separator
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Write tleplan file for one site
# ---------------------------------------------------------------------------

def write_tleplan(schedule, site_id, output_dir, observation_window=None):
    # type: (list, str, str, object) -> str
    """
    Write a tleplan_{site_id}.txt file for one site.

    Args:
        schedule: list of pass dicts (already sorted chronologically)
        site_id: site key from config.SITES
        output_dir: directory to write into
        observation_window: minutes (int/float) or "full"

    Returns:
        Path to the written file.
    """
    if observation_window is None:
        observation_window = DEFAULT_OBSERVATION_WINDOW_MIN

    site_cfg = SITES[site_id]
    tz = pytz.timezone(site_cfg["timezone"])

    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    filename = "tleplan_%s.txt" % site_id
    filepath = os.path.join(output_dir, filename)

    entries = []
    for p in schedule:
        begin_utc, end_utc = _observation_window(p, observation_window)
        begin_local = begin_utc.astimezone(tz) if begin_utc.tzinfo else pytz.utc.localize(begin_utc).astimezone(tz)
        end_local = end_utc.astimezone(tz) if end_utc.tzinfo else pytz.utc.localize(end_utc).astimezone(tz)
        entries.append(_format_entry(p, begin_local, end_local))

    with open(filepath, "w") as f:
        f.write("\n".join(entries))
        if entries:
            f.write("\n")

    logger.info("Wrote %d observations to %s", len(schedule), filepath)
    return filepath


# ---------------------------------------------------------------------------
# Legacy backward-compatible tleplan.txt
# ---------------------------------------------------------------------------

def write_legacy_tleplan(output_dir):
    # type: (str) -> str
    """Copy the NM site plan as tleplan.txt for backward compatibility."""
    src = os.path.join(output_dir, "tleplan_new_mexico.txt")
    dst = os.path.join(output_dir, "tleplan.txt")
    if os.path.isfile(src):
        shutil.copy2(src, dst)
        logger.info("Legacy tleplan.txt written (copy of NM plan)")
    else:
        logger.warning("NM plan not found; legacy tleplan.txt not created")
    return dst


# ---------------------------------------------------------------------------
# Schedule summary JSON
# ---------------------------------------------------------------------------

def write_schedule_summary(
    all_schedules,
    catalog_total,
    catalog_filtered,
    opportunities,
    planning_hours,
    output_dir,
):
    # type: (dict, int, int, dict, int, str) -> str
    """
    Write schedule_summary.json with metadata about the run.

    Args:
        all_schedules: {site_id: [pass_dict, ...]}
        catalog_total: total TLEs fetched before filtering
        catalog_filtered: number after filtering
        opportunities: multi-site opportunity dict
        planning_hours: planning window in hours
        output_dir: directory to write into

    Returns:
        Path to the written file.
    """
    # Tier breakdown (across all scheduled passes)
    tier_counts = {1: 0, 2: 0, 3: 0, 4: 0}
    all_norad_ids = set()
    for sid, sched in all_schedules.items():
        for p in sched:
            tier_counts[p["tier"]] = tier_counts.get(p["tier"], 0) + 1
            all_norad_ids.add(p["norad_id"])

    multi_site_objects = sum(
        1 for v in opportunities.values() if len(v.get("sites", set())) >= 2
    )

    sites_info = {}
    for sid, sched in all_schedules.items():
        multi_ct = sum(1 for p in sched if p.get("multi_site", False))
        sites_info[sid] = {
            "total_passes": len(sched),
            "scheduled": len(sched),
            "multi_site_passes": multi_ct,
        }

    summary = {
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "planning_window_hours": planning_hours,
        "catalog_size": catalog_total,
        "catalog_filtered": catalog_filtered,
        "sites": sites_info,
        "multi_site_objects": multi_site_objects,
        "tier_breakdown": {
            "tier_1": tier_counts.get(1, 0),
            "tier_2": tier_counts.get(2, 0),
            "tier_3": tier_counts.get(3, 0),
            "tier_4": tier_counts.get(4, 0),
        },
    }

    filepath = os.path.join(output_dir, "schedule_summary.json")
    with open(filepath, "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("Schedule summary written to %s", filepath)
    return filepath
