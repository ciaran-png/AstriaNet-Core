# AstriaNet-Core — Automated Multi-Site Satellite Observation System

Remote observatory automation for satellite tracking and imaging across a
global telescope network.

## Network Sites

| Site | Location | Status |
|------|----------|--------|
| **Cloudcroft, NM** | 32.903°N, 105.5295°W, 2225 m | Active |
| **Chile** | TBD (Cerro Tololo region placeholder) | Planned |
| **Australia** | TBD (Siding Spring region placeholder) | Planned |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      infinite.py                         │
│              (Daily loop / sunset trigger)               │
│                         │                                │
│            ┌────────────┴────────────┐                   │
│            ▼                         ▼                   │
│   schedule_generator/          automated2.py             │
│   (CelesTrak → SGP4 →         (Mount/Dome/Camera)       │
│    multi-site schedule)              │                   │
│            │                         ▼                   │
│            ▼                  pwi4_tle_observer.py       │
│    tleplan_*.txt              (Track & image sats)       │
│    tleplan.txt (legacy)                                  │
└─────────────────────────────────────────────────────────┘

Hardware Stack (per site):
  PWI4 ──── PlaneWave telescope mount control
  DDW  ──── Digital Dome Works (ASCOM)
  MaxIm DL ─ Camera control (COM automation)
  ASCOM ──── Hardware abstraction layer
```

## Core Scripts

| Script | Role |
|--------|------|
| **infinite.py** | Top-level loop. Checks date, fetches sunset time, waits, kicks off automated2.py. |
| **schedule_generator/** | Multi-site schedule generator. Fetches TLEs from CelesTrak, predicts passes via SGP4/Skyfield, scores by multi-site observability, outputs `tleplan.txt`. See [schedule_generator/README.md](schedule_generator/README.md). |
| **automated2.py** | Main orchestrator. Initializes PWI4 mount, opens dome, reads schedule, calls observer. |
| **pwi4_tle_observer.py** | Follows satellites via `pwi4.mount_follow_tle()`, controls MaxIm DL camera, saves FITS. |

## Legacy Scripts (Replaced)

| Script | Role | Status |
|--------|------|--------|
| **api_interaction.py** | N2YO API-based TLE fetch & pass prediction | **Replaced** by `schedule_generator/` |
| **noradid.txt** | Static list of ~900 Starlink NORAD IDs | **Replaced** by dynamic CelesTrak catalog |

## Supporting Scripts

| Script | Role |
|--------|------|
| **dashboard.py** | Flask web UI for remote start/stop/log viewing |
| **run_it_up2.py** | Tkinter GUI with weather, schedule view, status |
| **cache_manager.py** | JSON caching for TLE data |
| **platesolve.py** | PlateSolve3 wrapper for astrometric calibration |
| **askfornorad.py** | Tkinter dialog for manual NORAD ID entry |
| **oneminuteman.py** | Modifies tleplan.txt window timing |

## Quick Start

```bash
# Install dependencies
cd schedule_generator
pip install -r requirements.txt

# Generate multi-site schedule (all sites, next 24h)
python schedule_generator.py

# Generate for a single site
python schedule_generator.py --sites new_mexico

# Non-interactive (for automation)
python schedule_generator.py --non-interactive

# Run tests
python -m pytest test_schedule_generator.py -v
```

## Key Configuration

- **Timezone:** America/Denver (NM), America/Santiago (Chile), Australia/Sydney (AU)
- **Observation window:** Default 4 min centered on pass midpoint
- **Min elevation:** 20° (configurable per site)
- **Catalog cache TTL:** 6 hours
- **Python:** 3.8+ required
