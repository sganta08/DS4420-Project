# Charles River Flood ML

Charles River flood forecasting for the Charles River at Waltham, Massachusetts.
This repository currently contains data collection and processing only; machine-learning
models are placeholders for future team work.

## Team roles

| Area | Owner |
|---|---|
| Data scraping | Shravan |
| LSTM river-flow forecasting | Gwen |
| MLP rainfall, temperature, and season model | Xinxiang |
| Bayesian flood-probability model | Shravan |

## Setup

Requires Python 3.11.

```bash
python -m venv .venv
source .venv/bin/activate
make install
```

An optional `USGS_API_KEY` can be set in the environment.

## Run

```bash
python -m charles.cli check
python -m charles.cli usgs
python -m charles.cli noaa
python -m charles.cli build
python -m charles.cli all
# equivalent entry point
charles-data all
```

Use `--start` and `--end` with the `usgs` or `noaa` subcommands. Use `-v` for debug logs.
Set `DATA_DIR` to change the default `data/` output directory.

## Outputs

| File | Columns/meaning | Units |
|---|---|---|
| `data/raw/usgs_daily_discharge.csv` | time, value, unit_of_measure, parameter_code, approval_status, qualifier, last_modified | discharge in cfs |
| `data/raw/usgs_continuous_00060.csv` | USGS fields for 15-minute discharge | cfs |
| `data/raw/usgs_continuous_00065.csv` | USGS fields for 15-minute gage height | feet |
| `data/raw/usgs_peaks.csv` | USGS fields for annual peak flows | cfs |
| `data/raw/noaa_logan_daily.csv` | DATE, PRCP/SNOW/SNWD/TMAX/TMIN/TAVG/AWND normalized to precipitation, snowfall, snow depth, temperatures, wind, and precip_trace | inches, °F, mph |
| `data/processed/hourly_flow.csv` | `time_utc`; discharge/gage mean and max | cfs; feet |
| `data/processed/daily_merged.csv` | date, discharge_cfs_mean, discharge_approval, discharge_qualifier, precip_in, snowfall_in, snow_depth_in, tmax_f, tmin_f, tavg_f, wind_mph, precip_trace, discharge_cfs_15min_max/mean, gage_height_ft_15min_max/mean, month, doy_sin, doy_cos, water_year | mixed, listed above |

## Data caveats

- USGS provisional values may be revised; windows ending in the last 400 days are refetched.
- Ice-affected values and estimates are indicated by USGS `qualifier` fields.
- Logan Airport is coastal and outside the Charles River watershed, so it approximates basin weather.
- NOAA GHCN-Daily observations can lag a few days.
- 15-minute data is aggregated into local standard time (`Etc/GMT+5`, UTC-5) for daily matching.
- Downloaded data is intentionally excluded from git.

USGS [monitoring location](https://waterdata.usgs.gov/monitoring-location/USGS-01104500);
[OGC API documentation](https://api.waterdata.usgs.gov/).