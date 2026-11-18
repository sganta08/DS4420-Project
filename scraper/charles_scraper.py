#!/usr/bin/env python3
"""
Charles River flood-ML data scraper
===================================
Pulls everything the three models need from two public sources:

  USGS 01104500  Charles River at Waltham, MA
      - daily mean discharge (1931-08-04 -> today)      -> LSTM / MLP / Bayesian
      - 15-minute discharge + gage height (continuous)  -> LSTM, flood peaks
      - annual peak flows + stages                      -> Bayesian exceedance model
  NOAA GHCN-Daily USW00014739  Boston Logan Intl Airport (1936 -> today)
      - precip, snowfall, snow depth, Tmax/Tmin/Tavg, wind

APIs used (no scraping of HTML pages):
  * USGS Water Data OGC API  https://api.waterdata.usgs.gov/ogcapi/v1
    (the legacy waterservices.usgs.gov / nwis/* endpoints shut down 2027-02-22
     and are already throttled, so we don't use them)
  * NCEI Access Data Service https://www.ncei.noaa.gov/access/services/data/v1
    (same GHCN-Daily data as the CDO station page, but no token required)

API behavior verified 2026-11-18:
  * USGS rows live in features[].properties; values are strings; rows are NOT sorted;
    paginate by following links[rel=next].href (opaque cursor); max limit = 50000.
  * USGS `qualifier` is a JSON list (e.g. ["ICE"]) or null -> stored as "ICE;EST".
  * X-RateLimit-Remaining is only sent when an API key is used.
  * 15-min discharge (00060): 4 days in Feb 1976, none 1977-1988, data from 1989.
    15-min gage height (00065) starts 2007-10-01.
  * Peaks collection mixes discharge (00060) and stage (00065) peaks; no approval_status.
  * NCEI returns HTTP 200 with an empty body OR a header-only CSV outside the record.
    PRCP_ATTRIBUTES first field "T" = trace precipitation (stored as 0.00).

Usage (from the repo root)
-----
    pip install -r scraper/requirements.txt
    export USGS_API_KEY=...        # optional, free from api.waterdata.usgs.gov; raises rate limit
    python scraper/charles_scraper.py check     # quick smoke test (small requests)
    python scraper/charles_scraper.py all       # download everything + build processed tables
    python scraper/charles_scraper.py usgs --start 2007-10-01
    python scraper/charles_scraper.py noaa
    python scraper/charles_scraper.py build     # rebuild processed tables from raw files

Downloads are cached per window in data/raw/chunks/; re-runs only refetch chunks that end
within the last 400 days (provisional data gets revised). See scraper/DATA.md for columns.

Outputs (data/ is git-ignored; override location with DATA_DIR)
-------
  data/raw/usgs_daily_discharge.csv
  data/raw/usgs_continuous_00060.csv     (15-min discharge, cfs, UTC)
  data/raw/usgs_continuous_00065.csv     (15-min gage height, ft, UTC)
  data/raw/usgs_peaks.csv
  data/raw/noaa_logan_daily.csv
  data/processed/daily_merged.csv        (one row per day: flow + weather + season)
  data/processed/hourly_flow.csv         (hourly mean/max discharge & stage, UTC)
"""

from __future__ import annotations

import argparse
import ast
import io
import logging
import os
import time
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

# ----------------------------------------------------------------------------- config
SITE = "USGS-01104500"
NOAA_STATION = "USW00014739"
USGS_BASE = os.environ.get("USGS_OGC_BASE", "https://api.waterdata.usgs.gov/ogcapi/v1")
NCEI_BASE = "https://www.ncei.noaa.gov/access/services/data/v1"
USGS_MAX_LIMIT = 50000

DAILY_START = date(1931, 8, 4)
NOAA_START = date(1936, 1, 1)
# parameter code -> (column prefix, first date with 15-min data)
CONTINUOUS_PARAMS = {
    "00060": ("discharge_cfs", date(1976, 1, 1)),
    "00065": ("gage_height_ft", date(2007, 10, 1)),
}
NOAA_TYPES = "PRCP,SNOW,SNWD,TMAX,TMIN,TAVG,AWND"
NOAA_RENAME = {"PRCP": "precip_in", "SNOW": "snowfall_in", "SNWD": "snow_depth_in",
               "TMAX": "tmax_f", "TMIN": "tmin_f", "TAVG": "tavg_f", "AWND": "wind_mph"}

USGS_KEEP = ["time", "value", "unit_of_measure", "parameter_code",
             "approval_status", "qualifier", "last_modified"]
PEAKS_KEEP = ["parameter_code", "time", "value", "unit_of_measure", "qualifier",
              "water_year", "time_of_day", "peak_since", "last_modified"]
DAILY_COLUMNS = [
    "date", "discharge_cfs_mean", "discharge_approval", "discharge_qualifier",
    "precip_in", "snowfall_in", "snow_depth_in", "tmax_f", "tmin_f", "tavg_f", "wind_mph",
    "precip_trace", "discharge_cfs_15min_max", "discharge_cfs_15min_mean",
    "gage_height_ft_15min_max", "gage_height_ft_15min_mean",
    "month", "doy_sin", "doy_cos", "water_year",
]

# GHCN-Daily days at first-order stations run midnight-to-midnight local *standard*
# time, so we aggregate USGS sub-daily data on the same clock (UTC-5, no DST).
LOCAL_STD_TZ = "Etc/GMT+5"

# default: <repo>/data regardless of the current directory
DATA = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
RAW, CHUNKS, PROC = DATA / "raw", DATA / "raw" / "chunks", DATA / "processed"
REFRESH_DAYS = 400  # chunks ending within the last ~year are refetched (provisional data)

log = logging.getLogger("scraper")
session = requests.Session()
session.headers["User-Agent"] = "charles-river-flood-ml/1.0 (student research project)"
if os.environ.get("USGS_API_KEY"):
    session.headers["X-Api-Key"] = os.environ["USGS_API_KEY"]


# ----------------------------------------------------------------------------- http
def retry_after_seconds(value):
    """Parse Retry-After given as seconds or an HTTP-date; None if absent/unparseable."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return int(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max((when - datetime.now(UTC)).total_seconds(), 0)


def get(url, params=None, tries=6):
    """GET with exponential backoff on network errors and 429/5xx (honors Retry-After)."""
    last = ""
    for attempt in range(tries):
        final = attempt == tries - 1
        try:
            r = session.get(url, params=params, timeout=180)
        except requests.RequestException as e:
            last = repr(e)
            if final:
                break
            wait = 5 * 2 ** attempt
            log.warning("network error %s; retry in %ss", e, wait)
            time.sleep(wait)
            continue
        if r.status_code == 200:
            rem = r.headers.get("X-RateLimit-Remaining")  # only sent with an API key
            if rem is not None and rem.isdigit() and int(rem) < 50:
                log.warning("only %s USGS requests left this hour", rem)
            return r
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"HTTP {r.status_code}"
            if final:
                break
            wait = retry_after_seconds(r.headers.get("Retry-After")) or 5 * 2 ** attempt
            log.warning("HTTP %s from %s; retry in %ss", r.status_code, r.url[:120], wait)
            time.sleep(wait)
            continue
        log.error("HTTP %s: %s", r.status_code, r.text[:500])
        r.raise_for_status()
    raise RuntimeError(f"gave up on {url} after {tries} tries ({last})")


# ----------------------------------------------------------------------------- cache
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
    # the newest window ends "today", so its name changes each run: drop older versions
    for old in path.parent.glob(f"{s:%Y%m%d}_*.csv"):
        if old != path:
            old.unlink()
    log.info("%-18s %s..%s  %6d rows", name, s, e, len(df))
    return df


def concat(frames):
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_raw(df, fname, time_col="time"):
    RAW.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW / fname, index=False)
    if df.empty:
        log.warning("%s: no data returned", fname)
    else:
        log.info("wrote %s (%d rows, %s..%s)", fname, len(df),
                 df[time_col].min(), df[time_col].max())


# ----------------------------------------------------------------------------- USGS
def normalize_qualifier(q):
    """["ICE", "EST"] (or its string repr from a cached chunk) -> "ICE;EST"; empty -> None."""
    if q is None or (isinstance(q, float) and np.isnan(q)):
        return None
    if isinstance(q, str):
        q = q.strip()
        if not q.startswith("["):
            return q or None
        try:
            q = ast.literal_eval(q)
        except (ValueError, SyntaxError):
            return q
    if isinstance(q, list | tuple):
        return ";".join(str(x) for x in q if x) or None
    return str(q)


def ogc_items(collection, params):
    """Fetch all features from a USGS OGC API collection, following 'next' links."""
    url = f"{USGS_BASE}/collections/{collection}/items"
    query = {"f": "json", "skipGeometry": "true", **params}
    rows = []
    while url:
        js = get(url, query).json()
        for f in js.get("features", []):
            p = dict(f.get("properties") or {})
            if "qualifier" in p:
                p["qualifier"] = normalize_qualifier(p["qualifier"])
            rows.append(p)
        url = next((ln["href"] for ln in js.get("links", []) if ln.get("rel") == "next"), None)
        query = None  # the next link already carries the query string
    return pd.DataFrame(rows)


def finish_usgs(df):
    """Keep standard columns, values -> float, dedupe by time, sort by time."""
    if df.empty:
        return pd.DataFrame(columns=USGS_KEEP)
    df = df[[c for c in USGS_KEEP if c in df.columns]].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    if "qualifier" in df:
        df["qualifier"] = df["qualifier"].map(normalize_qualifier)
    return df.drop_duplicates("time", keep="last").sort_values("time").reset_index(drop=True)


def usgs_daily(start, end):
    def fetch(s, e):
        return ogc_items("daily", {
            "monitoring_location_id": SITE, "parameter_code": "00060",
            "statistic_id": "00003",  # daily mean
            "datetime": f"{s}/{e}", "limit": USGS_MAX_LIMIT})
    start = max(start, DAILY_START)
    df = finish_usgs(concat([cached("usgs_daily", s, e, fetch)
                             for s, e in windows(start, end, 20)]))
    write_raw(df, "usgs_daily_discharge.csv")
    return df


def usgs_continuous(start, end):
    """15-min data in 1-year windows; start=None uses each parameter's first data date."""
    for pcode, (_, first) in CONTINUOUS_PARAMS.items():
        def fetch(s, e, pcode=pcode):
            return ogc_items("continuous", {
                "monitoring_location_id": SITE, "parameter_code": pcode,
                "datetime": f"{s}T00:00:00Z/{e}T23:59:59Z", "limit": USGS_MAX_LIMIT})
        s0 = max(start, first) if start else first
        df = finish_usgs(concat([cached(f"usgs_cont_{pcode}", s, e, fetch)
                                 for s, e in windows(s0, end, 1)]))
        write_raw(df, f"usgs_continuous_{pcode}.csv")


def usgs_peaks():
    df = ogc_items("peaks", {"monitoring_location_id": SITE, "limit": USGS_MAX_LIMIT})
    if df.empty:
        df = pd.DataFrame(columns=PEAKS_KEEP)
    else:
        df = df[[c for c in PEAKS_KEEP if c in df.columns]].copy()
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.sort_values(["parameter_code", "time"]).reset_index(drop=True)
    write_raw(df, "usgs_peaks.csv")
    return df


# ----------------------------------------------------------------------------- NOAA
def parse_ncei_csv(text):
    """Empty body or header-only CSV (both happen outside the record) -> empty frame."""
    text = text.strip()
    return pd.read_csv(io.StringIO(text), dtype=str) if text else pd.DataFrame()


def noaa_params(s, e, attributes=True):
    return {"dataset": "daily-summaries", "stations": NOAA_STATION,
            "startDate": str(s), "endDate": str(e), "dataTypes": NOAA_TYPES,
            "format": "csv", "units": "standard",  # inches, deg F, mph
            "includeAttributes": str(attributes).lower()}


def noaa_daily(start, end):
    def fetch(s, e):
        return parse_ncei_csv(get(NCEI_BASE, noaa_params(s, e)).text)
    start = max(start, NOAA_START)
    df = concat([cached("noaa_daily", s, e, fetch) for s, e in windows(start, end, 10)])
    if not df.empty:
        df = df.drop_duplicates("DATE", keep="last").sort_values("DATE").reset_index(drop=True)
    write_raw(df, "noaa_logan_daily.csv", time_col="DATE")
    return df


# ----------------------------------------------------------------------------- build
def read_raw(fname):
    p = RAW / fname
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(p, dtype={"qualifier": str, "approval_status": str})
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def weather_frame(wx):
    """NOAA raw -> date + readable columns + precip_trace (NA where PRCP is missing)."""
    if wx.empty:
        return pd.DataFrame(columns=["date"])
    out = pd.DataFrame({"date": pd.to_datetime(wx["DATE"]).dt.date})
    for src, dst in NOAA_RENAME.items():
        if src in wx:
            out[dst] = pd.to_numeric(wx[src], errors="coerce")
    if "PRCP_ATTRIBUTES" in wx:  # measurement flag (first field) 'T' = trace
        flag = wx["PRCP_ATTRIBUTES"].fillna("").astype(str).str.split(",").str[0].str.strip()
        trace = pd.Series(pd.array(flag.eq("T"), dtype="boolean"), index=wx.index)
        if "PRCP" in wx:
            trace[pd.to_numeric(wx["PRCP"], errors="coerce").isna()] = pd.NA
        out["precip_trace"] = trace
    return out


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
            "discharge_qualifier": dv.get("qualifier"),  # e.g. ICE, ESTIMATED
        })

    # 15-min -> hourly (UTC) and daily max/mean (local standard time)
    hourly_parts, dagg_parts = [], []
    for pcode, (name, _) in CONTINUOUS_PARAMS.items():
        cv = read_raw(f"usgs_continuous_{pcode}.csv")
        if cv.empty:
            continue
        s = pd.Series(pd.to_numeric(cv["value"], errors="coerce").values,
                      index=pd.to_datetime(cv["time"], utc=True, format="ISO8601")).sort_index()
        h = s.resample("1h").agg(["mean", "max"]).add_prefix(f"{name}_")
        hourly_parts.append(h.dropna(how="all"))  # skip hours/days inside data gaps
        d = s.tz_convert(LOCAL_STD_TZ).resample("1D").agg(["max", "mean"])
        d = d.add_prefix(f"{name}_15min_").dropna(how="all")
        d.index = d.index.date
        dagg_parts.append(d)
    if hourly_parts:
        hourly = pd.concat(hourly_parts, axis=1)
        hourly.index.name = "time_utc"
        hourly.to_csv(PROC / "hourly_flow.csv")
        log.info("wrote hourly_flow.csv (%d rows)", len(hourly))

    # weather + 15-min daily aggregates, all outer-joined on date
    daily = daily.merge(weather_frame(read_raw("noaa_logan_daily.csv")), on="date", how="outer")
    for d in dagg_parts:
        daily = daily.merge(d, left_on="date", right_index=True, how="outer")

    daily = daily.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
    daily = daily.reindex(columns=DAILY_COLUMNS)  # same columns even if a source is missing
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

    # processed/ is the hand-off folder: add the (already clean) peaks and the data dictionary
    peaks = RAW / "usgs_peaks.csv"
    if peaks.exists():
        (PROC / "usgs_peaks.csv").write_bytes(peaks.read_bytes())
    (PROC / "DATA.md").write_bytes((Path(__file__).parent / "DATA.md").read_bytes())


# ----------------------------------------------------------------------------- check
def check():
    """Small requests to confirm every endpoint answers and returns the expected fields."""
    today = date.today()
    wk = today - timedelta(days=7)
    probes = [("daily", "daily", {"parameter_code": "00060", "statistic_id": "00003",
                                  "datetime": f"{today - timedelta(days=60)}/{today}"})]
    probes += [(f"continuous {p}", "continuous",
                {"parameter_code": p, "datetime": f"{wk}T00:00:00Z/{today}T23:59:59Z"})
               for p in CONTINUOUS_PARAMS]
    probes.append(("peaks", "peaks", {}))
    for name, coll, extra in probes:
        df = ogc_items(coll, {"monitoring_location_id": SITE, "limit": 1000, **extra})
        print(f"USGS {name:<16} rows={len(df):<5} cols={list(df.columns)[:8]}")
        if not df.empty and "time" in df:
            print(f"{'':22}range={df['time'].min()} .. {df['time'].max()}")
    rem = get(f"{USGS_BASE}/collections").headers.get("X-RateLimit-Remaining")
    key = "set" if os.environ.get("USGS_API_KEY") else "NOT set"
    print(f"USGS_API_KEY {key}; X-RateLimit-Remaining={rem or 'not reported'}")
    wx = parse_ncei_csv(get(NCEI_BASE, noaa_params(today - timedelta(days=60), today)).text)
    print(f"NOAA daily            rows={len(wx):<5} cols={list(wx.columns)[:8]}")
    if not wx.empty:
        print(f"{'':22}latest={wx['DATE'].max()}")


# ----------------------------------------------------------------------------- cli
def main():
    ap = argparse.ArgumentParser(description="Charles River flood-ML data scraper")
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
        usgs_daily(start or DAILY_START, end)
        usgs_continuous(start, end)
        usgs_peaks()
    if a.cmd in ("noaa", "all"):
        noaa_daily(start or NOAA_START, end)
    if a.cmd in ("build", "all"):
        build()


if __name__ == "__main__":
    main()
