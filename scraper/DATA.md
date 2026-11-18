# Charles River flood-ML dataset

Processed data for the LSTM, MLP and Bayesian models. Everyone should use the same
copy of these files so results are comparable. Each file has a refresh date, so note
which one you used.

**Sources**
- USGS gauge 01104500, Charles River at Waltham, MA (USGS Water Data OGC API).
- NOAA GHCN-Daily station USW00014739, Boston Logan Airport (NCEI Access Data Service).

## Files

| File | One row per | Coverage | Use for |
|---|---|---|---|
| `daily_merged.csv` | calendar day | 1931-08-04 → refresh date | all models |
| `hourly_flow.csv` | UTC hour that has readings | discharge from 1989 (plus 4 days in Feb 1976); gage height from 2007-10-01 | LSTM at sub-daily resolution, flood peaks |
| `usgs_peaks.csv` | annual peak event | water years 1932 → last complete year | Bayesian exceedance model |

### `daily_merged.csv`

Dates are full outer joins, so a day appears if *any* source has data. A blank cell means no data.

| Column | Units | Notes |
|---|---|---|
| `date` | YYYY-MM-DD | |
| `discharge_cfs_mean` | ft³/s | Official USGS daily mean discharge, the main **target** |
| `discharge_approval` | | `Approved` (final) or `Provisional` (recent data, may be revised) |
| `discharge_qualifier` | | e.g. `ICE` (ice-affected, so discharge is estimated), `ESTIMATED`. Several qualifiers are joined with `;` |
| `precip_in` | inches | Daily precipitation at Logan |
| `snowfall_in` | inches | |
| `snow_depth_in` | inches | Often blank in recent years |
| `tmax_f`, `tmin_f` | °F | |
| `tavg_f` | °F | Sparse; if missing, use `(tmax_f + tmin_f) / 2` |
| `wind_mph` | mph | Average daily wind; missing in early decades |
| `precip_trace` | bool | `True` = trace precipitation (recorded as 0.00) |
| `discharge_cfs_15min_max`, `_mean` | ft³/s | Daily max/mean of 15-min readings. Good for flood peaks |
| `gage_height_ft_15min_max`, `_mean` | ft | Daily max/mean river stage. Flood thresholds are defined on stage |
| `month` | 1–12 | |
| `doy_sin`, `doy_cos` | | Day-of-year on a 365.25-day cycle (season / snowmelt signal) |
| `water_year` | | Oct 1 – Sep 30; Oct–Dec belong to the next year |

**Day boundaries.** The 15-min aggregates use **local standard time (UTC−5, no
daylight saving)**, matching how NOAA defines a day at Logan. USGS daily means use the
gauge's local day.

### `hourly_flow.csv`

`time_utc`, `discharge_cfs_mean`, `discharge_cfs_max`, `gage_height_ft_mean`,
`gage_height_ft_max`. Hours without readings are left out, so check for time jumps
before building fixed-length sequences.

### `usgs_peaks.csv`

`parameter_code` is `00060` for a discharge peak (ft³/s) or `00065` for a stage peak
(ft); **filter on it**. Other columns: `time` (date of peak), `value`,
`unit_of_measure`, `qualifier`, `water_year`, `time_of_day`, `peak_since`, `last_modified`.

## Caveats
- Recent months are **Provisional** and USGS revises them. Consider excluding or
  down-weighting them when evaluating.
- `ICE`-qualified winter discharge is estimated, not measured.
- Logan (on the coast) is about 15 km from the Waltham gauge, so its weather is a proxy for the watershed.
- NOAA data lags real time by a few days, so the newest rows have flow but no weather.
