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
| `daily_merged.csv` | calendar day | 1931-08-04 → last day with an official daily mean (refresh date − 1) | all models |
| `hourly_flow.csv` | UTC hour (complete grid, no skipped hours) | 1990-10-01 → refresh time; gage height from 2007-10-01 | LSTM at sub-daily resolution, flood peaks |
| `usgs_peaks.csv` | annual peak event | water years 1932 → last complete year | Bayesian exceedance model |

### `daily_merged.csv`

Every calendar day is present, with no duplicates. `discharge_cfs_mean` (the target) has no blanks.
A blank cell in any other column means no data.

| Column | Units | Notes |
|---|---|---|
| `date` | YYYY-MM-DD | |
| `discharge_cfs_mean` | ft³/s | Official USGS daily mean discharge, the main **target** |
| `discharge_approval` | | `Approved` (final) or `Provisional` (recent data, may be revised) |
| `discharge_qualifier` | | Blank for measured values. `ESTIMATED` (58 days) means USGS estimated the value, mostly for winter ice (Jan–Feb) or equipment outages. Several qualifiers would be joined with `;` |
| `precip_in` | inches | Daily precipitation at Logan. Weather starts 1936-01-01; 7 later days are blank |
| `snowfall_in` | inches | |
| `tmax_f`, `tmin_f` | °F | 3 days in 1938–43 where Tmax < Tmin (NOAA source error) are blanked |
| `tmean_f` | °F | `(tmax_f + tmin_f) / 2`. Use this as the daily temperature |
| `wind_mph` | mph | Average daily wind. **Starts 1984-01-01** (blank before), so only use it for models trained on 1984+ |
| `precip_trace` | bool | `True` = trace precipitation (recorded as 0.00) |
| `discharge_cfs_15min_max`, `_mean` | ft³/s | Daily max/mean of 15-min readings, good for flood peaks. Only filled for days with ≥ 20 hours of readings. Continuous from 1990-10-01; before that only Feb 1976 (4 days), Jul 1988 (a few days) and Oct 1988 – Sep 1989 |
| `gage_height_ft_15min_max`, `_mean` | ft | Daily max/mean river stage, from 2007-10-01. Flood thresholds are defined on stage. Same ≥ 20 h rule |
| `month` | 1–12 | |
| `doy_sin`, `doy_cos` | | Day-of-year on a 365.25-day cycle (season / snowmelt signal) |
| `water_year` | | Oct 1 – Sep 30; Oct–Dec belong to the next year |

**Day boundaries.** The 15-min aggregates use **local standard time (UTC−5, no
daylight saving)**, matching how NOAA defines a day at Logan. USGS daily means use the
gauge's local day.

### `hourly_flow.csv`

| Column | Units | Notes |
|---|---|---|
| `time_utc` | ISO timestamp, UTC | One row for every hour. No hours are skipped |
| `discharge_cfs_mean`, `discharge_cfs_max` | ft³/s | Mean/max of the readings in that hour |
| `gage_height_ft_mean`, `gage_height_ft_max` | ft | Blank before 2007-10-01 |
| `discharge_cfs_filled`, `gage_height_ft_filled` | bool | `True` = gap of ≤ 6 h filled by linear interpolation, not measured |

Gaps longer than 6 hours stay blank: 15 discharge gaps, 1,163 hours in all, the longest
432 h (18 days, Feb 2002). Split sequences at blanks, or drop windows that contain one.
The 1976 and 1988–89 fragments are only in `daily_merged.csv`, to keep this file continuous.

### `usgs_peaks.csv`

`parameter_code` is `00060` for a discharge peak (ft³/s) or `00065` for a stage peak
(ft); **filter on it**. pandas reads it as the integer `60` / `65`, unless you pass `dtype={"parameter_code": str}`. Other columns: `time` (date of peak), `value`,
`unit_of_measure`, `qualifier`, `water_year`, `time_of_day`, `peak_since`, `last_modified`.

## Caveats
- Recent months are **Provisional** and USGS revises them. Consider excluding or
  down-weighting them when evaluating.
- `ESTIMATED` winter discharge (ice) is estimated, not measured. Consider dropping or down-weighting it.
- Logan (on the coast) is about 15 km from the Waltham gauge, so its weather is a proxy for the watershed.
- NOAA data lags real time by a few days, so the newest ~4 rows have flow but no weather.
- Not included (still in `data/raw/`): NOAA `TAVG` (only 1998–2005, with bogus 0 °F days) and
  `SNWD` snow depth (ends 2004-11-30).
