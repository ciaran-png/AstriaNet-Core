"""
AstriaNet Schedule Generator — Configuration
Site definitions, CelesTrak endpoints, tiering thresholds, and CLI defaults.
"""

# ---------------------------------------------------------------------------
# Observatory site definitions
# ---------------------------------------------------------------------------
SITES = {
    "new_mexico": {
        "name": "Cloudcroft, NM",
        "lat": 32.903,
        "lon": -105.5295,
        "alt_m": 2225,
        "timezone": "America/Denver",       # MST / MDT
        "min_elevation": 20,
    },
    "chile": {
        "name": "Chile Observatory",
        "lat": -30.2407,    # PLACEHOLDER — update when known
        "lon": -70.7366,    # PLACEHOLDER
        "alt_m": 2200,      # PLACEHOLDER
        "timezone": "America/Santiago",     # CLT
        "min_elevation": 20,
    },
    "australia": {
        "name": "Australia Observatory",
        "lat": -31.2727,    # PLACEHOLDER — update when known
        "lon": 149.0618,    # PLACEHOLDER
        "alt_m": 1165,      # PLACEHOLDER
        "timezone": "Australia/Sydney",     # AEST / AEDT
        "min_elevation": 20,
    },
}

# ---------------------------------------------------------------------------
# CelesTrak GP data endpoints
# ---------------------------------------------------------------------------
CELESTRAK_URLS = {
    "active": "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle",
    "stations": "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle",
    "visual": "https://celestrak.org/NORAD/elements/gp.php?GROUP=visual&FORMAT=tle",
    "last-30-days": "https://celestrak.org/NORAD/elements/gp.php?GROUP=last-30-days&FORMAT=tle",
}

# JSON endpoint (used as primary for easier parsing)
CELESTRAK_JSON_URL = (
    "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json"
)

# ---------------------------------------------------------------------------
# Catalog filtering thresholds
# ---------------------------------------------------------------------------
# LEO filter: mean_motion > this value (rev/day) ≈ period < 130 min
MIN_MEAN_MOTION = 11.08

# TLE epoch staleness — number of days before considering it decayed
MAX_EPOCH_AGE_DAYS = 30

# ---------------------------------------------------------------------------
# Tiering thresholds
# ---------------------------------------------------------------------------
# Tier 1: high-drag / decaying — ndot (revs/day²) significantly positive
TIER1_NDOT_THRESHOLD = 5e-5

# Tier 2: debris / rocket body name heuristics
DEBRIS_KEYWORDS = frozenset([
    "R/B", "DEB", "COOLANT", "WESTFORD", "SLAG", "FRAGMENTATION",
    "DEBRIS", "ROCKET BODY", "ROCKET", "PLATFORM",
])

# Tier 3: active payloads with perigee < this value (km)
TIER3_PERIGEE_KM = 400

# Tier weights for scoring
TIER_WEIGHTS = {
    1: 4.0,
    2: 3.0,
    3: 2.0,
    4: 1.0,
}

# ---------------------------------------------------------------------------
# Cache settings
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS = 21600          # 6 hours
CACHE_DIR = ".cache"
CACHE_CATALOG_FILE = "catalog_cache.json"
CACHE_TIMESTAMP_FILE = "catalog_timestamp.txt"

# ---------------------------------------------------------------------------
# Pass prediction defaults
# ---------------------------------------------------------------------------
DEFAULT_PLANNING_HOURS = 24
DEFAULT_OBSERVATION_WINDOW_MIN = 4  # minutes, centered on pass midpoint
DEFAULT_MAX_OBS_PER_NIGHT = 200

# Solar altitude threshold for "astronomical darkness"
SUN_ALTITUDE_THRESHOLD = -12.0     # degrees — nautical twilight boundary

# Multi-site sequential window: max hours between passes at different sites
MULTI_SITE_SEQUENTIAL_HOURS = 3.0  # ≈ 2 orbits

# Minimum gap between consecutive observations at one site (minutes)
MIN_GAP_MINUTES = 1
