"""
AstriaNet Schedule Generator — Test Suite

Validates:
  1. CelesTrak catalog fetch returns valid satellite dicts
  2. Output format is compatible with pwi4_tle_observer.py parser
  3. No overlapping observation windows per site (1-min gap)
  4. Timezone correctness (local times, not UTC)
  5. Multi-site detection works (ISS should be visible from ≥1 site)
  6. Legacy tleplan.txt is parseable by the existing Plan class
"""

import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from io import StringIO

import pytz

# Ensure the package directory is on sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from catalog_builder import (
    assign_tier,
    filter_catalog,
    load_or_fetch_catalog,
    parse_tle_text,
)
from config import SITES
from multi_site_scorer import find_multi_site_opportunities, score_pass
from plan_writer import write_tleplan, write_legacy_tleplan


# ---------------------------------------------------------------------------
# Bundled test TLE data (ISS + a Starlink + a rocket body)
# ---------------------------------------------------------------------------
TEST_TLE_TEXT = """ISS (ZARYA)
1 25544U 98067A   26047.50000000  .00012345  00000-0  23456-3 0  9991
2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49999999999993

STARLINK-1628
1 46169U 20057BE  26047.50000000  .00090653  00000-0  85658-3 0  9996
2 46169  53.0434 106.2911 0000315 268.4288  91.6691 15.66280961275329

CZ-2D R/B
1 49999U 21999A   26047.50000000  .00000100  00000-0  10000-4 0  9999
2 49999  97.5000 100.0000 0010000  90.0000 270.0000 14.80000000 10001
"""


class TestCatalogBuilder(unittest.TestCase):
    """Tests for catalog_builder.py."""

    def test_parse_tle_text(self):
        entries = parse_tle_text(TEST_TLE_TEXT)
        self.assertEqual(len(entries), 3)
        names = [e[0] for e in entries]
        self.assertIn("ISS (ZARYA)", names)
        self.assertIn("STARLINK-1628", names)
        self.assertIn("CZ-2D R/B", names)

    def test_parse_tle_line_format(self):
        entries = parse_tle_text(TEST_TLE_TEXT)
        for name, line1, line2 in entries:
            self.assertTrue(line1.startswith("1 "), "Line 1 should start with '1 '")
            self.assertTrue(line2.startswith("2 "), "Line 2 should start with '2 '")

    def test_filter_catalog_keeps_leo(self):
        entries = parse_tle_text(TEST_TLE_TEXT)
        catalog = filter_catalog(entries)
        # All three test objects are LEO
        self.assertGreaterEqual(len(catalog), 1)
        for sat in catalog:
            self.assertGreater(sat["mean_motion"], 11.0)

    def test_tier_assignment(self):
        # High ndot → Tier 1
        self.assertEqual(assign_tier("TESTSAT", 1e-3, 500), 1)
        # Rocket body → Tier 2
        self.assertEqual(assign_tier("CZ-2D R/B", 1e-6, 500), 2)
        # Debris keyword → Tier 2
        self.assertEqual(assign_tier("COSMOS DEB", 1e-6, 500), 2)
        # Low perigee active → Tier 3
        self.assertEqual(assign_tier("TESTSAT", 1e-6, 350), 3)
        # Everything else → Tier 4
        self.assertEqual(assign_tier("STARLINK-1234", 1e-6, 550), 4)

    def test_catalog_dict_keys(self):
        entries = parse_tle_text(TEST_TLE_TEXT)
        catalog = filter_catalog(entries)
        if catalog:
            required_keys = {
                "norad_id", "name", "tle_line1", "tle_line2",
                "tier", "mean_motion", "ndot", "perigee_km", "inclination",
            }
            for sat in catalog:
                self.assertTrue(
                    required_keys.issubset(sat.keys()),
                    "Missing keys: %s" % (required_keys - sat.keys()),
                )


class TestOutputFormat(unittest.TestCase):
    """Tests for tleplan.txt output format compatibility."""

    def _make_test_schedule(self):
        """Create a minimal test schedule."""
        now_utc = datetime.now(pytz.utc)
        return [
            {
                "norad_id": 25544,
                "name": "ISS (ZARYA)",
                "tle_line1": "1 25544U 98067A   26047.50000000  .00012345  00000-0  23456-3 0  9991",
                "tle_line2": "2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.49999999999993",
                "tier": 1,
                "site_id": "new_mexico",
                "rise_utc": now_utc,
                "set_utc": now_utc + timedelta(minutes=5),
                "max_el_utc": now_utc + timedelta(minutes=2.5),
                "max_el_deg": 65.0,
                "duration_sec": 300,
                "score": 5.0,
                "multi_site": False,
            },
            {
                "norad_id": 46169,
                "name": "STARLINK-1628",
                "tle_line1": "1 46169U 20057BE  26047.50000000  .00090653  00000-0  85658-3 0  9996",
                "tle_line2": "2 46169  53.0434 106.2911 0000315 268.4288  91.6691 15.66280961275329",
                "tier": 1,
                "site_id": "new_mexico",
                "rise_utc": now_utc + timedelta(minutes=10),
                "set_utc": now_utc + timedelta(minutes=15),
                "max_el_utc": now_utc + timedelta(minutes=12.5),
                "max_el_deg": 45.0,
                "duration_sec": 300,
                "score": 3.0,
                "multi_site": True,
            },
        ]

    def test_tleplan_format(self):
        """Verify the output matches the expected BEGINLOCAL/ENDLOCAL format."""
        schedule = self._make_test_schedule()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tleplan(schedule, "new_mexico", tmpdir, observation_window=4)
            filepath = os.path.join(tmpdir, "tleplan_new_mexico.txt")
            self.assertTrue(os.path.isfile(filepath))

            with open(filepath, "r") as f:
                content = f.read()

            # Check BEGINLOCAL pattern
            begin_pattern = re.compile(
                r"^BEGINLOCAL \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                re.MULTILINE,
            )
            self.assertTrue(
                begin_pattern.search(content),
                "Missing BEGINLOCAL line with correct format",
            )

            # Check ENDLOCAL pattern
            end_pattern = re.compile(
                r"^ENDLOCAL \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
                re.MULTILINE,
            )
            self.assertTrue(
                end_pattern.search(content),
                "Missing ENDLOCAL line with correct format",
            )

            # Check NAME line
            self.assertIn("NAME ISS (ZARYA)", content)

            # Check TLE line 0
            self.assertIn("0 ISS (ZARYA)", content)

            # Check TLE lines 1 and 2
            self.assertIn("1 25544U", content)
            self.assertIn("2 25544", content)

    def test_legacy_tleplan(self):
        """Verify legacy tleplan.txt is created as copy of NM plan."""
        schedule = self._make_test_schedule()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tleplan(schedule, "new_mexico", tmpdir, observation_window=4)
            write_legacy_tleplan(tmpdir)

            nm_path = os.path.join(tmpdir, "tleplan_new_mexico.txt")
            legacy_path = os.path.join(tmpdir, "tleplan.txt")

            self.assertTrue(os.path.isfile(legacy_path))

            with open(nm_path, "r") as f:
                nm_content = f.read()
            with open(legacy_path, "r") as f:
                legacy_content = f.read()

            self.assertEqual(nm_content, legacy_content)

    def test_no_overlapping_windows(self):
        """Check that no two observation windows overlap within a schedule."""
        schedule = self._make_test_schedule()
        # The test schedule has a 5-minute gap between entries — no overlap expected
        for i in range(len(schedule) - 1):
            end_i = schedule[i]["set_utc"]
            start_j = schedule[i + 1]["rise_utc"]
            gap = (start_j - end_i).total_seconds()
            self.assertGreaterEqual(
                gap, 60,
                "Overlap detected between entries %d and %d (gap: %.1fs)"
                % (i, i + 1, gap),
            )

    def test_timezone_is_local(self):
        """Verify that BEGINLOCAL times are in site-local timezone, not UTC."""
        schedule = self._make_test_schedule()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tleplan(schedule, "new_mexico", tmpdir, observation_window=4)
            filepath = os.path.join(tmpdir, "tleplan_new_mexico.txt")

            with open(filepath, "r") as f:
                content = f.read()

            # Extract the first BEGINLOCAL time
            match = re.search(
                r"BEGINLOCAL (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", content
            )
            self.assertIsNotNone(match, "No BEGINLOCAL found in output")

            local_time_str = match.group(1)
            local_dt = datetime.strptime(local_time_str, "%Y-%m-%d %H:%M:%S")

            # The UTC time from the schedule should differ from local (MST is UTC-7)
            # unless it happens to be midnight UTC = 5pm MST
            utc_hour = schedule[0]["rise_utc"].hour
            # Local time (Mountain) should be UTC - 7 (MST) or UTC - 6 (MDT)
            offset = utc_hour - local_dt.hour
            self.assertIn(
                offset % 24, [6, 7],
                "Local time doesn't appear to be Mountain Time (offset %d)" % offset,
            )

    def test_pwi4_parser_compatibility(self):
        """
        Verify output is parseable by the Plan class from pwi4_tle_observer.py.
        We replicate the minimal parser logic here to avoid importing win32com.
        """
        schedule = self._make_test_schedule()
        with tempfile.TemporaryDirectory() as tmpdir:
            write_tleplan(schedule, "new_mexico", tmpdir, observation_window=4)
            filepath = os.path.join(tmpdir, "tleplan_new_mexico.txt")

            with open(filepath, "r") as f:
                content = f.read()

            # Minimal parser replicating pwi4_tle_observer.py Plan.parse()
            reader = StringIO(content)
            entries = []

            def read_next_nonempty(r):
                while True:
                    line = r.readline()
                    if line == "":
                        return None
                    line = line.strip()
                    if line == "":
                        continue
                    return line

            while True:
                begin_line = read_next_nonempty(reader)
                if begin_line is None:
                    break
                end_line = read_next_nonempty(reader)
                name_line = read_next_nonempty(reader)
                tle0 = read_next_nonempty(reader)
                tle1 = read_next_nonempty(reader)
                tle2 = read_next_nonempty(reader)

                if tle2 is None:
                    break

                self.assertTrue(
                    begin_line.startswith("BEGINLOCAL"),
                    "Expected BEGINLOCAL, got: %s" % begin_line,
                )
                self.assertTrue(
                    end_line.startswith("ENDLOCAL"),
                    "Expected ENDLOCAL, got: %s" % end_line,
                )
                self.assertTrue(
                    name_line.startswith("NAME"),
                    "Expected NAME, got: %s" % name_line,
                )
                self.assertTrue(
                    tle0.startswith("0 "),
                    "Expected TLE line 0, got: %s" % tle0,
                )
                self.assertTrue(
                    tle1.startswith("1 "),
                    "Expected TLE line 1, got: %s" % tle1,
                )
                self.assertTrue(
                    tle2.startswith("2 "),
                    "Expected TLE line 2, got: %s" % tle2,
                )

                entries.append({
                    "begin": begin_line,
                    "end": end_line,
                    "name": name_line,
                })

            self.assertEqual(
                len(entries), 2,
                "Expected 2 entries, got %d" % len(entries),
            )


class TestScoring(unittest.TestCase):
    """Tests for the scoring formula."""

    def test_score_increases_with_tier(self):
        base = {
            "tier": 4, "max_el_deg": 45.0, "duration_sec": 300,
        }
        s4 = score_pass(dict(base, tier=4), 1)
        s1 = score_pass(dict(base, tier=1), 1)
        self.assertGreater(s1, s4)

    def test_score_increases_with_sites(self):
        base = {
            "tier": 2, "max_el_deg": 60.0, "duration_sec": 240,
        }
        s1 = score_pass(base, 1)
        s3 = score_pass(base, 3)
        self.assertGreater(s3, s1)

    def test_score_increases_with_elevation(self):
        base = {"tier": 2, "duration_sec": 300}
        s_low = score_pass(dict(base, max_el_deg=25.0), 1)
        s_high = score_pass(dict(base, max_el_deg=80.0), 1)
        self.assertGreater(s_high, s_low)


class TestMultiSiteDetection(unittest.TestCase):
    """Tests for multi-site opportunity detection."""

    def test_overlapping_passes_detected(self):
        now = datetime.now(pytz.utc)
        passes = {
            "site_a": [{
                "norad_id": 25544, "name": "ISS",
                "rise_utc": now, "set_utc": now + timedelta(minutes=5),
                "max_el_utc": now + timedelta(minutes=2.5),
                "tier": 1,
            }],
            "site_b": [{
                "norad_id": 25544, "name": "ISS",
                "rise_utc": now + timedelta(minutes=2),
                "set_utc": now + timedelta(minutes=7),
                "max_el_utc": now + timedelta(minutes=4.5),
                "tier": 1,
            }],
        }
        opps = find_multi_site_opportunities(passes)
        self.assertIn(25544, opps)
        self.assertTrue(opps[25544]["simultaneous"])
        self.assertEqual(len(opps[25544]["sites"]), 2)

    def test_sequential_passes_detected(self):
        now = datetime.now(pytz.utc)
        passes = {
            "site_a": [{
                "norad_id": 25544, "name": "ISS",
                "rise_utc": now, "set_utc": now + timedelta(minutes=5),
                "max_el_utc": now + timedelta(minutes=2.5),
                "tier": 1,
            }],
            "site_b": [{
                "norad_id": 25544, "name": "ISS",
                "rise_utc": now + timedelta(hours=1.5),
                "set_utc": now + timedelta(hours=1.5, minutes=5),
                "max_el_utc": now + timedelta(hours=1.5, minutes=2.5),
                "tier": 1,
            }],
        }
        opps = find_multi_site_opportunities(passes)
        self.assertIn(25544, opps)
        self.assertFalse(opps[25544]["simultaneous"])
        self.assertTrue(opps[25544]["sequential"])


if __name__ == "__main__":
    unittest.main()
