# AstriaNet Schedule Generator

Multi-site satellite observation scheduler for the AstriaNet telescope network.
Replaces the legacy `api_interaction.py` with local SGP4/Skyfield propagation
and CelesTrak catalog data — no API keys required.

## Sites

| Site | Location | Lat | Lon | Alt | Timezone |
|------|----------|-----|-----|-----|----------|
| `new_mexico` | Cloudcroft, NM | 32.903°N | 105.5295°W | 2225 m | America/Denver |
| `chile` | Chile Observatory* | 30.2407°S | 70.7366°W | 2200 m | America/Santiago |
| `australia` | Australia Observatory* | 31.2727°S | 149.0618°E | 1165 m | Australia/Sydney |

\* Coordinates are placeholders — update in `config.py` when confirmed.

## Architecture

```
schedule_generator.py   ← CLI entry point
├── catalog_builder.py  ← CelesTrak TLE fetch + LEO filtering + tiering
├── pass_predictor.py   ← Skyfield/SGP4 pass prediction per site
├── multi_site_scorer.py ← Multi-site scoring + greedy scheduling + nighttime filter
├── plan_writer.py      ← tleplan.txt output + schedule_summary.json
└── config.py           ← Site definitions, thresholds, constants
```

## Quick Start

```bash
cd schedule_generator
pip install -r requirements.txt
python schedule_generator.py
```

## CLI Options

```
--hours N              Planning window in hours (default: 24)
--sites s1,s2          Comma-separated site IDs (default: all)
--observation-window N Minutes, or 'full' (default: 4)
--non-interactive      No prompts (for automation)
--output-dir PATH      Output directory (default: cwd)
--refresh-catalog      Force CelesTrak re-fetch
--min-elevation DEG    Override minimum pass elevation
--max-obs N            Max observations per site (default: 200)
```

## Output Files

| File | Description |
|------|-------------|
| `tleplan_new_mexico.txt` | NM site schedule |
| `tleplan_chile.txt` | Chile site schedule |
| `tleplan_australia.txt` | Australia site schedule |
| `tleplan.txt` | Legacy copy of NM plan (backward compat) |
| `schedule_summary.json` | Run metadata & statistics |

## Output Format

Each observation block in `tleplan.txt`:
```
BEGINLOCAL 2025-08-11 19:39:55
ENDLOCAL 2025-08-11 19:43:55
NAME STARLINK-1628
0 STARLINK-1628
1 46169U 20057BE  25222.93928310  .00090653  00000-0  85658-3 0  9996
2 46169  53.0434 106.2911 0000315 268.4288  91.6691 15.66280961275329
```

## Satellite Priority Tiers

| Tier | Weight | Description |
|------|--------|-------------|
| 1 | 4.0× | High-drag / decaying (ṅ > 5e-5) |
| 2 | 3.0× | Rocket bodies & debris |
| 3 | 2.0× | Active payloads, perigee < 400 km |
| 4 | 1.0× | Everything else in LEO |

## Integration with Existing Automation

- `infinite.py` calls `schedule_generator.py --non-interactive` instead of `api_interaction.py`
- `automated2.py` reads `tleplan.txt` unchanged
- `pwi4_tle_observer.py` parses the same format unchanged

## Tests

```bash
python -m pytest test_schedule_generator.py -v
```

## Dependencies

- `skyfield>=1.46` — SGP4 propagation + ephemeris
- `numpy>=1.20` — array math
- `requests>=2.25` — HTTP for CelesTrak
- `pytz>=2021.1` — timezone conversion

No paid APIs. No API keys.
