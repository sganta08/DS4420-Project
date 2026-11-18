# charles-river-flood-ml

DS4420 project: forecast Charles River flow and flood risk at Waltham, MA
(USGS 01104500) from stream-gauge and Boston Logan weather data.

| Model | Owner | Goal |
|---|---|---|
| LSTM | Gwen | Multi-day flow forecasting |
| MLP | Xinxiang | Flow from recent rainfall, temperature, season (snowmelt) |
| Bayesian | Shravan | Probability that flow/stage exceeds flood thresholds, with uncertainty |
| Data | Shravan | Scraping and cleaning |

## Data

The processed CSVs (`daily_merged.csv`, `hourly_flow.csv`, `usgs_peaks.csv` and the
`DATA.md` data dictionary) are shared **outside git**; ask Shravan for the link. Put
them in `data/processed/` (git-ignored). See [scraper/DATA.md](scraper/DATA.md) for
column definitions and caveats.

### Regenerating the data (only needed to refresh)

```bash
pip install -r scraper/requirements.txt
export USGS_API_KEY=...                       # optional; free at api.waterdata.usgs.gov
python scraper/charles_scraper.py check       # smoke test
python scraper/charles_scraper.py all         # ~90 requests; writes data/raw and data/processed
```
