"""Configuration constants and paths."""

import os
from pathlib import Path

USGS_BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v1"
NOAA_BASE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
USGS_SITE = "USGS-01104500"
NOAA_STATION = "USW00014739"

DATA_START = "1931-08-04"
CONTINUOUS_START = "1976-01-01"
NOAA_START = "1936-01-01"
LOCAL_STANDARD_TZ = "Etc/GMT+5"

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data"))
RAW_DIR = DATA_DIR / "raw"
CHUNK_DIR = RAW_DIR / "chunks"
PROCESSED_DIR = DATA_DIR / "processed"

DAILY_DISCHARGE_FILE = RAW_DIR / "usgs_daily_discharge.csv"
CONTINUOUS_DISCHARGE_FILE = RAW_DIR / "usgs_continuous_00060.csv"
CONTINUOUS_GAGE_FILE = RAW_DIR / "usgs_continuous_00065.csv"
PEAKS_FILE = RAW_DIR / "usgs_peaks.csv"
NOAA_FILE = RAW_DIR / "noaa_logan_daily.csv"
HOURLY_FLOW_FILE = PROCESSED_DIR / "hourly_flow.csv"
DAILY_MERGED_FILE = PROCESSED_DIR / "daily_merged.csv"
