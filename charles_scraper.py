#!/usr/bin/env python3
"""
Charles River flood-ML data scraper
===================================
Pulls everything the three models need from two public sources:

  USGS 01104500  Charles River at Waltham, MA
      - daily mean discharge (1931 -> today)            -> LSTM / MLP / Bayesian
      - 15-minute discharge + gage height (continuous)  -> LSTM, flood peaks
      - annual peak flows                               -> Bayesian exceedance model
  NOAA GHCN-Daily USW00014739  Boston Logan Intl Airport
      - precip, snowfall, snow depth, Tmax/Tmin/Tavg, wind

APIs used (no scraping of HTML pages):
  * USGS Water Data OGC API  https://api.waterdata.usgs.gov/ogcapi/v1
    (the legacy waterservices.usgs.gov / nwis/uv endpoints are being shut down
     on 2027-02-22 and are already being throttled, so we don't use them)
  * NCEI Access Data Service https://www.ncei.noaa.gov/access/services/data/v1
    (same GHCN-Daily data as the CDO station page, but no token required)

Usage
-----
    pip install -r requirements.txt
    export USGS_API_KEY=...        # optional, free from api.waterdata.usgs.gov; raises rate limit
    python charles_scraper.py check        # quick smoke test (small requests)
    python charles_scraper.py all          # download everything + build merged tables
    python charles_scraper.py usgs --start 2007-10-01   # just USGS, custom start
    python charles_scraper.py noaa
    python charles_scraper.py build        # rebuild processed tables from raw files

Downloads are cached per chunk in data/raw/chunks/, so re-runs only refetch
the most recent (still-provisional) chunks.

Outputs
-------
  data/raw/usgs_daily_discharge.csv
  data/raw/usgs_continuous_00060.csv     (15-min discharge, cfs, UTC)
  data/raw/usgs_continuous_00065.csv     (15-min gage height, ft, UTC)
  data/raw/usgs_peaks.csv
  data/raw/noaa_logan_daily.csv
  data/processed/daily_merged.csv        (one row per day: flow + weather + season)
  data/processed/hourly_flow.csv         (hourly mean/max discharge & stage)
"""
import argparse
import io
import logging
import os
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ----------------------------------------------------------------------------- config
SITE = "USGS-01104500"
NOAA_STATION = "USW00014739"
USGS_BASE = os.environ.get("USGS_OGC_BASE", "https://api.waterdata.usgs.gov/ogcapi/v1")
NCEI_BASE = "https://www.ncei.noaa.gov/access/services/data/v1"

CONTINUOUS_PARAMS = {"00060": "discharge_cfs", "00065": "gage_height_ft"}
NOAA_TYPES = "PRCP,SNOW,SNWD,TMAX,TMIN,TAVG,AWND"

# GHCN-Daily days at first-order stations run midnight-to-midnight local *standard*
# time, so we aggregate USGS sub-daily data on the same clock (UTC-5, no DST).
LOCAL_STD_TZ = "Etc/GMT+5"

DATA = Path(os.environ.get("DATA_DIR", "data"))
RAW, CHUNKS, PROC = DATA / "raw", DATA / "raw" / "chunks", DATA / "processed"
REFRESH_DAYS = 400  # chunks overlapping the last ~year are always refetched (provisional data)

log = logging.getLogger("scraper")
session = requests.Session()
session.headers["User-Agent"] = "charles-river-flood-ml/1.0 (student research project)"
if os.environ.get("USGS_API_KEY"):
    session.headers["X-Api-Key"] = os.environ["USGS_API_KEY"]


# ----------------------------------------------------------------------------- http
def get(url, params=None, tries=6):
    """GET with retry/backoff on rate limits and server errors."""
    for attempt in range(tries):
        try:
            r = session.get(url, params=params, timeout=180)
        except requests.RequestException as e:
            wait = 5 * 2 ** attempt
            log.warning("network error %s; retry in %ss", e, wait)
            time.sleep(wait)
            continue
        if r.status_code == 200:
            rem = r.headers.get("X-RateLimit-Remaining")
            if rem is not None and int(rem) < 50:
                log.warning("only %s USGS requests left this hour (set USGS_API_KEY)", rem)
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            wait = int(r.headers.get("Retry-After") or 0) or 5 * 2 ** attempt
            log.warning("HTTP %s from %s; retry in %ss", r.status_code, r.url[:120], wait)
            time.sleep(wait)
            continue
        log.error("HTTP %s: %s", r.status_code, r.text[:500])
        r.raise_for_status()
    raise RuntimeError(f"gave up on {url}")


def windows(start, end, years):
    """Yield (start, end) date windows of `years` length covering [start, end]."""
    s = start
    while s <= end:
        e = min(date(s.year + years, s.month, 1) - timedelta(days=1), end)
        yield s, e
        s = e + timedelta(days=1)


def cached(name, s, e, fetch):
    """Run fetch() for a window, caching the result as a chunk CSV."""
    path = CHUNKS / name / f"{s:%Y%m%d}_{e:%Y%m%d}.csv"
    stale = e >= date.today() - timedelta(days=REFRESH_DAYS)
    if path.exists() and not stale:
        try:
            return pd.read_csv(path, dtype=str)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    df = fetch(s, e)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    log.info("%-22s %s..%s  %6d rows", name, s, e, len(df))
    return df


# ----------------------------------------------------------------------------- USGS
def ogc_items(collection, params):
    """Fetch all features from a USGS OGC API collection, following 'next' links."""
    url = f"{USGS_BASE}/collections/{collection}/items"
    query = {"f": "json", "skipGeometry": "true", **params}
    rows = []
    while url:
        js = get(url, query).json()
        rows.extend(f.get("properties", {}) for f in js.get("features", []))
        url = next((l["href"] for l in js.get("links", []) if l.get("rel") == "next"), None)
        query = None  # the next link already carries the query string
    return pd.DataFrame(rows)


def usgs_daily(start, end):
    def fetch(s, e):
        return ogc_items("daily", {
            "monitoring_location_id": SITE, "parameter_code": "00060",
            "statistic_id": "00003",  # daily mean
            "datetime": f"{s}/{e}", "limit": 10000})
    df = pd.concat([cached("usgs_daily", s, e, fetch) for s, e in windows(start, end, 20)],
                   ignore_index=True)
    return finish_usgs(df, "usgs_daily_discharge.csv")


def usgs_continuous(start, end):
    for pcode in CONTINUOUS_PARAMS:
        def fetch(s, e, pcode=pcode):
            return ogc_items("continuous", {
                "monitoring_location_id": SITE, "parameter_code": pcode,
                "datetime": f"{s}T00:00:00Z/{e}T23:59:59Z", "limit": 50000})
        df = pd.concat([cached(f"usgs_cont_{pcode}", s, e, fetch)
                        for s, e in windows(start, end, 1)], ignore_index=True)
        finish_usgs(df, f"usgs_continuous_{pcode}.csv")


def usgs_peaks():
    df = ogc_items("peaks", {"monitoring_location_id": SITE, "limit": 10000})
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW / "usgs_peaks.csv", index=False)
    log.info("usgs_peaks: %d rows", len(df))
    return df


def finish_usgs(df, fname):
    keep = ["time", "value", "unit_of_measure", "parameter_code",
            "approval_status", "qualifier", "last_modified"]
    if df.empty:
        log.warning("%s: no data returned", fname)
    else:
        df = df[[c for c in keep if c in df.columns]].copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.drop_duplicates("time").sort_values("time")
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW / fname, index=False)
    log.info("wrote %s (%d rows)", fname, len(df))
    return df


# ----------------------------------------------------------------------------- NOAA
def noaa_daily(start, end):
    def fetch(s, e):
        r = get(NCEI_BASE, {
            "dataset": "daily-summaries", "stations": NOAA_STATION,
            "startDate": str(s), "endDate": str(e), "dataTypes": NOAA_TYPES,
            "format": "csv", "units": "standard",  # inches, deg F, mph
            "includeAttributes": "true"})
        text = r.text.strip()  # outside the period of record NCEI returns an empty 200
        return pd.read_csv(io.StringIO(text), dtype=str) if text else pd.DataFrame()
    df = pd.concat([cached("noaa_daily", s, e, fetch) for s, e in windows(start, end, 10)],
                   ignore_index=True)
    if not df.empty:
        df = df.drop_duplicates("DATE").sort_values("DATE")
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW / "noaa_logan_daily.csv", index=False)
    log.info("wrote noaa_logan_daily.csv (%d rows)", len(df))
    return df


# ----------------------------------------------------------------------------- build
def read_raw(fname):
    p = RAW / fname
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def build():
    PROC.mkdir(parents=True, exist_ok=True)

    # daily mean discharge (official USGS daily values; days are local time at the gauge)
    dv = read_raw("usgs_daily_discharge.csv")
    daily = pd.DataFrame(columns=["date"])
    if not dv.empty:
        daily = pd.DataFrame({
            "date": pd.to_datetime(dv["time"]).dt.date,
            "discharge_cfs_mean": dv["value"],
            "discharge_approval": dv.get("approval_status"),
            "discharge_qualifier": dv.get("qualifier"),  # e.g. ice-affected, estimated
        })

    # 15-min -> hourly and daily max (peaks matter for flooding)
    hourly_parts, dmax_parts = [], []
    for pcode, name in CONTINUOUS_PARAMS.items():
        cv = read_raw(f"usgs_continuous_{pcode}.csv")
        if cv.empty:
            continue
        s = cv.set_index(pd.to_datetime(cv["time"], utc=True))["value"]
        hourly_parts.append(s.resample("1h").agg(["mean", "max"]).add_prefix(f"{name}_"))
        local = s.tz_convert(LOCAL_STD_TZ)
        d = local.resample("1D").agg(["max", "mean"]).add_prefix(f"{name}_15min_")
        d.index = d.index.date
        dmax_parts.append(d)
    if hourly_parts:
        hourly = pd.concat(hourly_parts, axis=1)
        hourly.index.name = "time_utc"
        hourly.to_csv(PROC / "hourly_flow.csv")
        log.info("wrote hourly_flow.csv (%d rows)", len(hourly))

    # weather
    wx = read_raw("noaa_logan_daily.csv")
    if not wx.empty:
        cols = [c for c in NOAA_TYPES.split(",") if c in wx.columns]
        wx_d = wx[["DATE"] + cols].rename(columns=str.lower).rename(columns={
            "prcp": "precip_in", "snow": "snowfall_in", "snwd": "snow_depth_in",
            "tmax": "tmax_f", "tmin": "tmin_f", "tavg": "tavg_f", "awnd": "wind_mph"})
        wx_d["date"] = pd.to_datetime(wx_d.pop("date")).dt.date
        if "PRCP_ATTRIBUTES" in wx.columns:  # measurement flag 'T' = trace (stored as 0)
            wx_d["precip_trace"] = wx["PRCP_ATTRIBUTES"].fillna("").str.startswith("T").values
        daily = daily.merge(wx_d, on="date", how="outer")

    for d in dmax_parts:
        daily = daily.merge(d, left_on="date", right_index=True, how="left")

    daily = daily.sort_values("date").reset_index(drop=True)
    dt = pd.to_datetime(daily["date"])
    doy = dt.dt.dayofyear
    daily["month"] = dt.dt.month
    daily["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)  # season features for the MLP
    daily["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    # water year starts Oct 1 (standard in hydrology; useful for Bayesian annual maxima)
    daily["water_year"] = dt.dt.year + (dt.dt.month >= 10).astype(int)
    daily.to_csv(PROC / "daily_merged.csv", index=False)
    log.info("wrote daily_merged.csv (%d rows, %s..%s)",
             len(daily), daily["date"].min(), daily["date"].max())


# ----------------------------------------------------------------------------- check
def check():
    """Small requests to confirm every endpoint answers and returns the expected fields."""
    today = date.today()
    wk = today - timedelta(days=7)
    for name, coll, extra in [
        ("daily", "daily", {"parameter_code": "00060", "statistic_id": "00003",
                            "datetime": f"{today - timedelta(days=60)}/{today}"}),
        ("continuous", "continuous", {"parameter_code": "00060",
                                      "datetime": f"{wk}T00:00:00Z/{today}T00:00:00Z"}),
        ("peaks", "peaks", {}),
    ]:
        df = ogc_items(coll, {"monitoring_location_id": SITE, "limit": 1000, **extra})
        print(f"USGS {name:<11} rows={len(df):<5} cols={list(df.columns)[:8]}")
        if not df.empty and "time" in df:
            print(f"                 latest={df['time'].max()}")
    r = get(NCEI_BASE, {"dataset": "daily-summaries", "stations": NOAA_STATION,
                        "startDate": str(today - timedelta(days=60)), "endDate": str(today),
                        "dataTypes": NOAA_TYPES, "format": "csv", "units": "standard"})
    lines = r.text.strip().splitlines()
    print(f"NOAA daily       rows={max(len(lines) - 1, 0)}  header={lines[0] if lines else None}")
    if len(lines) > 1:
        print(f"                 latest={lines[-1][:80]}")


# ----------------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("cmd", choices=["check", "usgs", "noaa", "build", "all"])
    ap.add_argument("--start", help="start date YYYY-MM-DD (default: full record)")
    ap.add_argument("--end", default=str(date.today()))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    end = date.fromisoformat(a.end)
    start = date.fromisoformat(a.start) if a.start else None

    if a.cmd == "check":
        return check()
    if a.cmd in ("usgs", "all"):
        usgs_daily(start or date(1931, 8, 1), end)
        usgs_continuous(start or date(1976, 1, 1), end)
        usgs_peaks()
    if a.cmd in ("noaa", "all"):
        noaa_daily(start or date(1936, 1, 1), end)
    if a.cmd in ("build", "all"):
        build()


if __name__ == "__main__":
    main()
