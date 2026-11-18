"""Build processed hourly and daily datasets."""

import math
from pathlib import Path

import pandas as pd

from .config import (
    CONTINUOUS_DISCHARGE_FILE,
    CONTINUOUS_GAGE_FILE,
    DAILY_DISCHARGE_FILE,
    DAILY_MERGED_FILE,
    HOURLY_FLOW_FILE,
    LOCAL_STANDARD_TZ,
    NOAA_FILE,
)


def _read_csv(path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def build_hourly_flow(
    discharge_path=CONTINUOUS_DISCHARGE_FILE,
    gage_path=CONTINUOUS_GAGE_FILE,
    output_path=HOURLY_FLOW_FILE,
) -> pd.DataFrame:
    """Resample 15-minute discharge and gage height to hourly UTC."""
    discharge = _read_csv(discharge_path)
    gage = _read_csv(gage_path)
    series: dict[str, pd.Series] = {}

    if not discharge.empty and "time" in discharge and "value" in discharge:
        values = pd.to_datetime(discharge["time"], utc=True, errors="coerce")
        frame = pd.DataFrame({"time": values, "value": pd.to_numeric(discharge["value"], errors="coerce")})
        frame = frame.dropna(subset=["time"]).set_index("time").sort_index()
        series["discharge_cfs_mean"] = frame["value"].resample("1h").mean()
        series["discharge_cfs_max"] = frame["value"].resample("1h").max()
    if not gage.empty and "time" in gage and "value" in gage:
        values = pd.to_datetime(gage["time"], utc=True, errors="coerce")
        frame = pd.DataFrame({"time": values, "value": pd.to_numeric(gage["value"], errors="coerce")})
        frame = frame.dropna(subset=["time"]).set_index("time").sort_index()
        series["gage_height_ft_mean"] = frame["value"].resample("1h").mean()
        series["gage_height_ft_max"] = frame["value"].resample("1h").max()

    hourly = pd.DataFrame(series).sort_index()
    hourly.index.name = "time_utc"
    output_path = _ensure_parent(output_path)
    hourly.to_csv(output_path)
    return hourly


def _ensure_parent(path) -> object:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_daily_merged(
    daily_path=DAILY_DISCHARGE_FILE,
    continuous_path=CONTINUOUS_DISCHARGE_FILE,
    gage_path=CONTINUOUS_GAGE_FILE,
    noaa_path=NOAA_FILE,
    output_path=DAILY_MERGED_FILE,
) -> pd.DataFrame:
    """Outer-merge NOAA and USGS fields by local standard-time date."""
    daily = _read_csv(daily_path)
    continuous = _read_csv(continuous_path)
    gage = _read_csv(gage_path)
    noaa = _read_csv(noaa_path)

    usgs_daily = pd.DataFrame()
    if not daily.empty and "time" in daily:
        daily["value"] = pd.to_numeric(daily["value"], errors="coerce")
        daily["date"] = pd.to_datetime(daily["time"], utc=True, errors="coerce").dt.date
        usgs_daily = (
            daily.groupby("date", as_index=False)
            .agg(
                discharge_cfs_mean=("value", "mean"),
                discharge_approval=("approval_status", "first"),
                discharge_qualifier=("qualifier", "first"),
            )
        )

    if not continuous.empty and "time" in continuous:
        con = pd.DataFrame(
            {
                "time": pd.to_datetime(continuous["time"], utc=True, errors="coerce"),
                "value": pd.to_numeric(continuous["value"], errors="coerce"),
            }
        ).dropna(subset=["time"])
        con["date"] = con["time"].dt.tz_convert(LOCAL_STANDARD_TZ).dt.date
        con_daily = con.groupby("date").agg(
            discharge_cfs_15min_max=("value", "max"),
            discharge_cfs_15min_mean=("value", "mean"),
        )
    else:
        con_daily = pd.DataFrame(
            columns=["discharge_cfs_15min_max", "discharge_cfs_15min_mean"]
        )
        con_daily.index.name = "date"

    if not gage.empty and "time" in gage:
        gh = pd.DataFrame(
            {
                "time": pd.to_datetime(gage["time"], utc=True, errors="coerce"),
                "value": pd.to_numeric(gage["value"], errors="coerce"),
            }
        ).dropna(subset=["time"])
        gh["date"] = gh["time"].dt.tz_convert(LOCAL_STANDARD_TZ).dt.date
        gh_daily = gh.groupby("date").agg(
            gage_height_ft_15min_max=("value", "max"),
            gage_height_ft_15min_mean=("value", "mean"),
        )
    else:
        gh_daily = pd.DataFrame(
            columns=["gage_height_ft_15min_max", "gage_height_ft_15min_mean"]
        )
        gh_daily.index.name = "date"

    if not noaa.empty:
        noaa = noaa.copy()
        noaa["date"] = pd.to_datetime(noaa["DATE"], errors="coerce").dt.date
        noaa = noaa.drop(columns=["DATE"], errors="ignore")
    else:
        noaa = pd.DataFrame(columns=["date"])

    merged = usgs_daily
    if merged.empty:
        merged = pd.DataFrame(columns=["date"])
    merged = merged.merge(noaa, on="date", how="outer")
    merged = merged.merge(con_daily.reset_index(), on="date", how="outer")
    merged = merged.merge(gh_daily.reset_index(), on="date", how="outer")
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = merged.sort_values("date").reset_index(drop=True)
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")

    dates = pd.to_datetime(merged["date"], errors="coerce")
    merged["month"] = dates.dt.month
    days = dates.dt.day_of_year if hasattr(dates.dt, "day_of_year") else dates.dt.dayofyear
    merged["doy_sin"] = [math.sin(2 * math.pi * day / 365.25) if pd.notna(day) else None for day in days]
    merged["doy_cos"] = [math.cos(2 * math.pi * day / 365.25) if pd.notna(day) else None for day in days]
    merged["water_year"] = dates.dt.year + (dates.dt.month >= 10)

    columns = [
        "date",
        "discharge_cfs_mean",
        "discharge_approval",
        "discharge_qualifier",
        "precip_in",
        "snowfall_in",
        "snow_depth_in",
        "tmax_f",
        "tmin_f",
        "tavg_f",
        "wind_mph",
        "precip_trace",
        "discharge_cfs_15min_max",
        "discharge_cfs_15min_mean",
        "gage_height_ft_15min_max",
        "gage_height_ft_15min_mean",
        "month",
        "doy_sin",
        "doy_cos",
        "water_year",
    ]
    for column in columns:
        if column not in merged:
            merged[column] = None
    merged = merged[columns]
    output_path = _ensure_parent(output_path)
    merged.to_csv(output_path, index=False)
    return merged


def build_all() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build hourly and daily outputs."""
    return build_hourly_flow(), build_daily_merged()
