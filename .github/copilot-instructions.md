# Copilot instructions

This project collects Charles River flood data. Use the USGS Water Data OGC API
(`https://api.waterdata.usgs.gov/ogcapi/v1`) with the USGS-01104500 site. Do not use
`waterservices.usgs.gov` or deprecated `waterdata.usgs.gov/nwis/*` endpoints.

All USGS items requests use `f=json&skipGeometry=true` and paginate by `rel="next"`.
Use 20-year daily windows, 1-year continuous windows, and no datetime filter for peaks.
Keep USGS fields and preserve provisional/approved status and qualifiers.

Use NOAA NCEI Access at `https://www.ncei.noaa.gov/access/services/data/v1` for Logan
station USW00014739 in 10-year windows. An empty HTTP 200 body means no record.
`PRCP_ATTRIBUTES` beginning with `T` is trace precipitation and sets `precip_trace=true`.

Cache chunks under `data/raw/chunks/<source>/<start>_<end>.csv`. Refetch chunks whose end
is within 400 days. Aggregate continuous observations by local standard time
`Etc/GMT+5`, UTC-5 with no DST. Never commit downloaded data.
