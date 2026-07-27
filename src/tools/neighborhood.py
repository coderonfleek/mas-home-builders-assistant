from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import httpx
from langchain.tools import tool

CENSUS_BASE = "https://api.census.gov/data/2022/acs/acs5"
CENSUS_TIMEOUT = 15.0
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "census_snapshot.json"

VARIABLES = {
    "total_population": "B01003_001E",
    "median_age": "B01002_001E",
    "median_household_income": "B19013_001E",
    "median_home_value": "B25077_001E",
    "median_gross_rent": "B25064_001E",
    "owner_occupied_units": "B25003_002E",
    "total_occupied_units": "B25003_001E",
}

@lru_cache(maxsize=1)
def _load_snapshot() -> dict:
    """Load the bundled Census snapshot JSON once per session. Returns {} on any error."""
    try:
        with SNAPSHOT_PATH.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _from_snapshot(zip_code: str) -> dict | None:
    """Look up a ZIP in the snapshot and reshape it to match the API's response format.

    The API returns ``{"B01003_001E": "46274", ...}``; the snapshot uses friendly
    field names. We translate so downstream code doesn't care where the data came from.
    """
    entry = _load_snapshot().get(zip_code)
    if not entry:
        return None
    return {
        VARIABLES["total_population"]: str(entry["population"]),
        VARIABLES["median_age"]: str(entry["median_age"]),
        VARIABLES["median_household_income"]: str(entry["median_household_income"]),
        VARIABLES["median_home_value"]: str(entry["median_home_value"]),
        VARIABLES["median_gross_rent"]: str(entry["median_gross_rent"]),
        VARIABLES["owner_occupied_units"]: str(entry["owner_occupied_units"]),
        VARIABLES["total_occupied_units"]: str(entry["total_occupied_units"]),
    }

def _api_key() -> str | None:
    """Return the Census API key from env, or None if it isn't configured."""
    return os.environ.get("CENSUS_API_KEY") or None

@lru_cache(maxsize=256)
def _fetch_acs(zip_code: str, variables: tuple[str, ...]) -> dict | None:
    """Fetch ACS variables for a ZIP. Tries the API first, snapshot second."""
    # Try the live API if a key is configured.
    key = _api_key()
    if key:
        params = {
            "get": ",".join(variables),
            "for": f"zip code tabulation area:{zip_code}",
            "key": key,
        }
        try:
            resp = httpx.get(
                CENSUS_BASE,
                params=params,
                timeout=CENSUS_TIMEOUT,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and len(data) >= 2:
                headers, values = data[0], data[1]
                return dict(zip(headers, values))
        except (httpx.HTTPError, json.JSONDecodeError):
            pass  # Fall through to the snapshot.

    # Fallback: bundled snapshot. Same return shape as the API.
    return _from_snapshot(zip_code)

def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (ValueError, TypeError):
        return None
    if n < 0:
        return None
    return n

@tool
def get_demographics(zip_code: str) -> str:
    """Get population, median age, and median household income for a ZIP.

    Uses the US Census Bureau's American Community Survey (ACS 5-Year).
    Returns a summary string or an "unavailable" message if the ZIP has
    no ACS data.
    """
    zip_code = str(zip_code).zfill(5)
    vars_ = (
        VARIABLES["total_population"],
        VARIABLES["median_age"],
        VARIABLES["median_household_income"],
    )
    data = _fetch_acs(zip_code, vars_)
    if data is None:
        return f"Census data unavailable for ZIP {zip_code}."

    population = _safe_int(data.get(VARIABLES["total_population"]))
    median_age = _safe_int(data.get(VARIABLES["median_age"]))
    income = _safe_int(data.get(VARIABLES["median_household_income"]))

    lines = [f"Demographics for ZIP {zip_code}:"]
    if population is not None:
        lines.append(f"  Population: {population:,}")
    if median_age is not None:
        lines.append(f"  Median age: {median_age}")
    if income is not None:
        lines.append(f"  Median household income: ${income:,}")
    if len(lines) == 1:
        return f"Census returned no usable demographic data for ZIP {zip_code}."
    return "\n".join(lines)

@tool
def get_housing_stats(zip_code: str) -> str:
    """Get housing stats for a ZIP: median home value, rent, ownership rate.

    Uses the ACS 5-Year dataset. Returns a summary string or an
    "unavailable" message if the ZIP has no ACS data.
    """
    zip_code = str(zip_code).zfill(5)
    vars_ = (
        VARIABLES["median_home_value"],
        VARIABLES["median_gross_rent"],
        VARIABLES["owner_occupied_units"],
        VARIABLES["total_occupied_units"],
    )
    data = _fetch_acs(zip_code, vars_)
    if data is None:
        return f"Census data unavailable for ZIP {zip_code}."

    home_value = _safe_int(data.get(VARIABLES["median_home_value"]))
    rent = _safe_int(data.get(VARIABLES["median_gross_rent"]))
    owner = _safe_int(data.get(VARIABLES["owner_occupied_units"]))
    total = _safe_int(data.get(VARIABLES["total_occupied_units"]))

    lines = [f"Housing stats for ZIP {zip_code}:"]
    if home_value is not None:
        lines.append(f"  Median home value: ${home_value:,}")
    if rent is not None:
        lines.append(f"  Median gross rent: ${rent:,}/month")
    if owner is not None and total is not None and total > 0:
        pct = 100 * owner / total
        lines.append(f"  Owner-occupancy: {pct:.0f}% ({owner:,} of {total:,} units)")
    if len(lines) == 1:
        return f"Census returned no usable housing data for ZIP {zip_code}."
    return "\n".join(lines)


def fetch_neighborhood_raw(zip_code: str) -> dict:
    """Return a flat dict of stats for a ZIP. Missing values become None."""
    zip_code = str(zip_code).zfill(5)
    data = _fetch_acs(
        zip_code,
        (
            VARIABLES["total_population"],
            VARIABLES["median_household_income"],
            VARIABLES["median_home_value"],
            VARIABLES["owner_occupied_units"],
            VARIABLES["total_occupied_units"],
        ),
    )
    if data is None:
        return {
            "zip_code": zip_code,
            "population": None,
            "median_household_income": None,
            "median_home_value": None,
            "owner_occupancy_pct": None,
        }
    owner = _safe_int(data.get(VARIABLES["owner_occupied_units"]))
    total = _safe_int(data.get(VARIABLES["total_occupied_units"]))
    owner_pct = (100 * owner / total) if owner is not None and total else None
    return {
        "zip_code": zip_code,
        "population": _safe_int(data.get(VARIABLES["total_population"])),
        "median_household_income": _safe_int(
            data.get(VARIABLES["median_household_income"])
        ),
        "median_home_value": _safe_int(data.get(VARIABLES["median_home_value"])),
        "owner_occupancy_pct": owner_pct,
    }


