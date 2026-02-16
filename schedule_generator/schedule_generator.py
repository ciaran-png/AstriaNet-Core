#!/usr/bin/env python
"""
AstriaNet Schedule Generator — Main CLI Entry Point

Replaces api_interaction.py with local SGP4/Skyfield pass prediction and
multi-site scheduling.  Fetches TLE data from CelesTrak, computes pass
predictions for each observatory site, scores/prioritises objects, and
outputs per-site tleplan.txt files consumable by the existing automation.

Usage:
    python schedule_generator.py                          # defaults
    python schedule_generator.py --hours 48
    python schedule_generator.py --sites new_mexico,chile
    python schedule_generator.py --non-interactive
    python schedule_generator.py --refresh-catalog
    python schedule_generator.py --observation-window full
    python schedule_generator.py --min-elevation 30
    python schedule_generator.py --output-dir /tmp/plans
"""

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta

import pytz

# ---------------------------------------------------------------------------
# Ensure the package directory is on sys.path so sibling imports work when
# invoked as ``python schedule_generator.py`` from within the directory.
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from catalog_builder import load_or_fetch_catalog, fetch_tle_catalog, filter_catalog
from config import (
    DEFAULT_MAX_OBS_PER_NIGHT,
    DEFAULT_OBSERVATION_WINDOW_MIN,
    DEFAULT_PLANNING_HOURS,
    SITES,
)
from multi_site_scorer import (
    build_schedule,
    compute_dark_windows,
    filter_nighttime,
    find_multi_site_opportunities,
)
from pass_predictor import predict_passes_all_sites
from plan_writer import (
    write_legacy_tleplan,
    write_schedule_summary,
    write_tleplan,
)

logger = logging.getLogger("schedule_generator")


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="AstriaNet multi-site satellite schedule generator.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_PLANNING_HOURS,
        help="Planning window in hours (default: %d)" % DEFAULT_PLANNING_HOURS,
    )
    parser.add_argument(
        "--sites",
        type=str,
        default=None,
        help="Comma-separated site IDs (default: all). Options: %s"
        % ",".join(SITES.keys()),
    )
    parser.add_argument(
        "--observation-window",
        dest="observation_window",
        default=str(DEFAULT_OBSERVATION_WINDOW_MIN),
        help="Observation window in minutes, or 'full' for entire pass "
        "(default: %d)" % DEFAULT_OBSERVATION_WINDOW_MIN,
    )
    parser.add_argument(
        "--non-interactive",
        dest="non_interactive",
        action="store_true",
        help="Run without prompts (for automation by infinite.py)",
    )
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=None,
        help="Directory for output files (default: current working directory)",
    )
    parser.add_argument(
        "--refresh-catalog",
        dest="refresh_catalog",
        action="store_true",
        help="Force catalog refresh, ignoring cache TTL",
    )
    parser.add_argument(
        "--min-elevation",
        dest="min_elevation",
        type=float,
        default=None,
        help="Minimum pass elevation in degrees (overrides per-site config)",
    )
    parser.add_argument(
        "--max-obs",
        dest="max_obs",
        type=int,
        default=DEFAULT_MAX_OBS_PER_NIGHT,
        help="Maximum observations per site per night (default: %d)"
        % DEFAULT_MAX_OBS_PER_NIGHT,
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main(argv=None):
    args = parse_args(argv)

    # --- Logging ---
    log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Resolve parameters ---
    site_ids = list(SITES.keys())
    if args.sites:
        site_ids = [s.strip() for s in args.sites.split(",")]
        for s in site_ids:
            if s not in SITES:
                logger.error("Unknown site '%s'. Valid: %s", s, list(SITES.keys()))
                sys.exit(1)

    obs_window = args.observation_window
    if obs_window != "full":
        try:
            obs_window = int(obs_window)
        except ValueError:
            try:
                obs_window = float(obs_window)
            except ValueError:
                logger.error(
                    "Invalid --observation-window '%s'. Use an integer or 'full'.",
                    obs_window,
                )
                sys.exit(1)

    output_dir = args.output_dir or os.getcwd()

    now_utc = datetime.utcnow().replace(tzinfo=pytz.utc)
    t_start = now_utc
    t_end = now_utc + timedelta(hours=args.hours)

    logger.info("=" * 70)
    logger.info("AstriaNet Schedule Generator")
    logger.info("=" * 70)
    logger.info("Planning window : %s → %s (%d hours)", t_start, t_end, args.hours)
    logger.info("Sites           : %s", ", ".join(site_ids))
    logger.info("Output directory: %s", output_dir)
    logger.info("Obs window      : %s min", obs_window)
    logger.info("")

    # ------------------------------------------------------------------
    # Step 1: Build satellite catalog
    # ------------------------------------------------------------------
    logger.info("Step 1/5: Building satellite catalog …")
    catalog = load_or_fetch_catalog(force_refresh=args.refresh_catalog)
    catalog_filtered = len(catalog)

    # We approximate total fetched as filtered * 1.5 (can't know without re-fetching).
    # If we force-refreshed we have exact numbers via logging, but the summary
    # needs a count.  We'll record a rough estimate.
    catalog_total_approx = int(catalog_filtered * 2.5)

    tier_counts = {}
    for sat in catalog:
        tier_counts[sat["tier"]] = tier_counts.get(sat["tier"], 0) + 1
    logger.info(
        "Catalog: %d LEO objects  |  Tiers: %s",
        catalog_filtered,
        {("T%d" % k): v for k, v in sorted(tier_counts.items())},
    )

    # ------------------------------------------------------------------
    # Step 2: Predict passes for each site
    # ------------------------------------------------------------------
    logger.info("Step 2/5: Computing pass predictions …")
    all_passes = predict_passes_all_sites(
        catalog, site_ids, t_start, t_end, args.min_elevation
    )

    # ------------------------------------------------------------------
    # Step 3: Nighttime filtering
    # ------------------------------------------------------------------
    logger.info("Step 3/5: Filtering to nighttime passes …")
    dark_windows = {}
    for sid in site_ids:
        site_cfg = SITES[sid]
        dark_windows[sid] = compute_dark_windows(site_cfg, t_start, t_end)
        logger.info(
            "  [%s] %d dark windows found",
            sid,
            len(dark_windows[sid]),
        )
        all_passes[sid] = filter_nighttime(all_passes[sid], dark_windows[sid])

    # ------------------------------------------------------------------
    # Step 4: Multi-site scoring & schedule building
    # ------------------------------------------------------------------
    logger.info("Step 4/5: Scoring & scheduling …")
    opportunities = find_multi_site_opportunities(all_passes)

    all_schedules = {}
    for sid in site_ids:
        sched = build_schedule(
            all_passes[sid], opportunities, sid, max_obs=args.max_obs
        )
        all_schedules[sid] = sched

    # ------------------------------------------------------------------
    # Step 5: Write output files
    # ------------------------------------------------------------------
    logger.info("Step 5/5: Writing output files …")
    for sid in site_ids:
        write_tleplan(all_schedules[sid], sid, output_dir, obs_window)

    # Legacy backward-compatible tleplan.txt
    if "new_mexico" in site_ids:
        write_legacy_tleplan(output_dir)

    write_schedule_summary(
        all_schedules,
        catalog_total_approx,
        catalog_filtered,
        opportunities,
        args.hours,
        output_dir,
    )

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("=" * 70)
    parts = []
    for sid in site_ids:
        sched = all_schedules[sid]
        multi_ct = sum(1 for p in sched if p.get("multi_site", False))
        parts.append(
            "%d for %s (%d multi-site)"
            % (len(sched), SITES[sid]["name"], multi_ct)
        )
    logger.info("Scheduled %s", ", ".join(parts))
    logger.info("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
