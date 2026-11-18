"""USGS OGC API collection fetchers."""

import logging
from datetime import date
from urllib.parse import urljoin

import pandas as pd
import requests

from .cache import chunk_path, is_chunk_stale, window_ranges
from .config import (
    CHUNK_DIR,
    CONTINUOUS_DISCHARGE_FILE,
    CONTINUOUS_GAGE_FILE,
    CONTINUOUS_START,
    DAILY_DISCHARGE_FILE,
    DATA_START,
    PEAKS_FILE,
    USGS_BASE_URL,
    USGS_SITE,
)
from .http import create_session, retry_request

LOGGER = logging.getLogger(__name__)
KEEP_FIELDS = [
    "time",
    "value",
    "unit_of_measure",
    "parameter_code",
    "approval_status",
    "qualifier",
    "last_modified",
]
NUMERIC_FIELDS = {"value"}


def ogc_items(
    session: requests.Session,
    collection: str,
    params: dict,
) -> list[dict]:
    """Fetch and paginate a USGS OGC GeoJSON collection."""
    url = f"{USGS_BASE_URL}/collections/{collection}/items"
    query = {"f": "json", "skipGeometry": "true", **params}
    rows: list[dict] = []
    next_url: str | None = url
    next_params: dict | None = query
    while next_url:
        response = retry_request(session, "GET", next_url, params=next_params)
        payload = response.json()
        for feature in payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            row = {field: properties.get(field) for field in KEEP_FIELDS}
            for field in NUMERIC_FIELDS:
                if field in row and row[field] not in (None, ""):
                    try:
                        row[field] = float(row[field])
                    except (TypeError, ValueError):
                        row[field] = None
            rows.append(row)
        next_link = next((link for link in payload.get("links", []) if link.get("rel") == "next"), None)
        next_url = urljoin(url, next_link.get("href")) if next_link else None
        next_params = None
    return rows


def _cached_fetch(
    source: str,
    start: str,
    end: str,
    years: int,
    fetch_window,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for window_start, window_end in window_ranges(start, end, years):
        path = chunk_path(source, window_start, window_end, CHUNK_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not is_chunk_stale(path, window_end) and path.stat().st_size > 0:
            frames.append(pd.read_csv(path))
        elif path.exists() and not is_chunk_stale(path, window_end) and path.stat().st_size == 0:
            continue
        else:
            frame = fetch_window(window_start, window_end)
            if frame.empty:
                path.write_text("", encoding="utf-8")
            else:
                frame.to_csv(path, index=False)
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=KEEP_FIELDS)
    result = pd.concat(frames, ignore_index=True)
    time_column = "time" if "time" in result else "DATE"
    if time_column in result:
        result = result.drop_duplicates(subset=[time_column])
        result = result.sort_values(time_column)
    return result.reset_index(drop=True)


def fetch_daily(
    start: str = DATA_START,
    end: str | None = None,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch daily mean discharge in 20-year cached windows."""
    session = session or create_session()
    end = end or date.today().isoformat()

    def fetch_window(start_date: str, end_date: str) -> pd.DataFrame:
        rows = ogc_items(
            session,
            "daily",
            {
                "monitoring_location_id": USGS_SITE,
                "parameter_code": "00060",
                "statistic_id": "00003",
                "datetime": f"{start_date}/{end_date}",
                "limit": 10000,
            },
        )
        return pd.DataFrame(rows)

    frame = _cached_fetch("usgs_daily", start, end, 20, fetch_window)
    DAILY_DISCHARGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(DAILY_DISCHARGE_FILE, index=False)
    return frame


def fetch_continuous(
    start: str = CONTINUOUS_START,
    end: str | None = None,
    session: requests.Session | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch 15-minute discharge and gage-height data in yearly windows."""
    session = session or create_session()
    end = end or date.today().isoformat()
    results: dict[str, pd.DataFrame] = {}
    for parameter, source, destination in (
        ("00060", "usgs_continuous_00060", CONTINUOUS_DISCHARGE_FILE),
        ("00065", "usgs_continuous_00065", CONTINUOUS_GAGE_FILE),
    ):
        def fetch_window(start_date: str, end_date: str, parameter_code: str = parameter) -> pd.DataFrame:
            rows = ogc_items(
                session,
                "continuous",
                {
                    "monitoring_location_id": USGS_SITE,
                    "parameter_code": parameter_code,
                    "datetime": f"{start_date}T00:00:00Z/{end_date}T23:59:59Z",
                    "limit": 50000,
                },
            )
            return pd.DataFrame(rows)

        frame = _cached_fetch(source, start, end, 1, fetch_window)
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False)
        results[source] = frame
    return results["usgs_continuous_00060"], results["usgs_continuous_00065"]


def fetch_peaks(
    start: str | None = None,
    end: str | None = None,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch annual peak flows (time filtering is intentionally omitted)."""
    session = session or create_session()
    rows = ogc_items(
        session,
        "peaks",
        {
            "monitoring_location_id": USGS_SITE,
            "limit": 10000,
        },
    )
    frame = pd.DataFrame(rows)
    PEAKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(PEAKS_FILE, index=False)
    return frame
