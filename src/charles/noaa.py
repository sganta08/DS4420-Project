"""NOAA NCEI daily-summary fetcher."""

from datetime import date

import pandas as pd
import requests

from .cache import chunk_path, is_chunk_stale, window_ranges
from .config import CHUNK_DIR, NOAA_BASE_URL, NOAA_FILE, NOAA_START, NOAA_STATION
from .http import create_session, retry_request

DATA_TYPES = "PRCP,SNOW,SNWD,TMAX,TMIN,TAVG,AWND"


def fetch_noaa(
    start: str = NOAA_START,
    end: str | None = None,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch Logan Airport GHCN-Daily CSV in cached 10-year windows."""
    session = session or create_session()
    end = end or date.today().isoformat()
    frames: list[pd.DataFrame] = []
    for window_start, window_end in window_ranges(start, end, 10):
        path = chunk_path("noaa_logan", window_start, window_end, CHUNK_DIR)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not is_chunk_stale(path, window_end) and path.stat().st_size > 0:
            frames.append(pd.read_csv(path))
        elif path.exists() and not is_chunk_stale(path, window_end) and path.stat().st_size == 0:
            continue
        else:
            response = retry_request(
                session,
                "GET",
                NOAA_BASE_URL,
                params={
                    "dataset": "daily-summaries",
                    "stations": NOAA_STATION,
                    "startDate": window_start,
                    "endDate": window_end,
                    "dataTypes": DATA_TYPES,
                    "format": "csv",
                    "units": "standard",
                    "includeAttributes": "true",
                },
            )
            if not response.text.strip():
                path.write_text("", encoding="utf-8")
                continue
            frame = parse_noaa_csv(response.text)
            if frame.empty:
                path.write_text("", encoding="utf-8")
            else:
                frame.to_csv(path, index=False)
            frames.append(frame)
    if frames:
        frame = pd.concat(frames, ignore_index=True)
        frame = frame.drop_duplicates(subset=["DATE"]).sort_values("DATE").reset_index(drop=True)
    else:
        frame = pd.DataFrame()
    NOAA_FILE.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(NOAA_FILE, index=False)
    return frame


def parse_noaa_csv(text: str) -> pd.DataFrame:
    """Parse NOAA CSV and add the trace-precipitation boolean."""
    if not text.strip():
        return pd.DataFrame()
    from io import StringIO

    frame = pd.read_csv(StringIO(text))
    if "DATE" not in frame.columns:
        return frame
    rename = {
        "PRCP": "precip_in",
        "SNOW": "snowfall_in",
        "SNWD": "snow_depth_in",
        "TMAX": "tmax_f",
        "TMIN": "tmin_f",
        "TAVG": "tavg_f",
        "AWND": "wind_mph",
    }
    frame = frame.rename(columns=rename)
    for column in rename.values():
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "PRCP_ATTRIBUTES" in frame.columns:
        frame["precip_trace"] = frame["PRCP_ATTRIBUTES"].fillna("").apply(
            lambda value: str(value).split(",", 1)[0].strip() == "T"
        )
    else:
        frame["precip_trace"] = False
    keep = [
        "DATE",
        "precip_in",
        "snowfall_in",
        "snow_depth_in",
        "tmax_f",
        "tmin_f",
        "tavg_f",
        "wind_mph",
        "precip_trace",
    ]
    return frame[[column for column in keep if column in frame.columns]]
