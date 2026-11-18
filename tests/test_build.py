import pandas as pd

from charles.build import build_daily_merged


def test_local_standard_time_daily_aggregation(tmp_path):
    discharge = tmp_path / "discharge.csv"
    gage = tmp_path / "gage.csv"
    noaa = tmp_path / "noaa.csv"
    output = tmp_path / "daily.csv"
    pd.DataFrame({
        "time": ["2024-01-02T02:00:00Z", "2024-01-02T05:00:00Z"],
        "value": [10.0, 20.0],
    }).to_csv(discharge, index=False)
    pd.DataFrame({
        "time": ["2024-01-02T02:00:00Z", "2024-01-02T05:00:00Z"],
        "value": [1.0, 2.0],
    }).to_csv(gage, index=False)
    pd.DataFrame({"DATE": ["2024-01-01"], "precip_in": [0.5]}).to_csv(noaa, index=False)

    frame = build_daily_merged(
        daily_path=tmp_path / "missing.csv",
        continuous_path=discharge,
        gage_path=gage,
        noaa_path=noaa,
        output_path=output,
    )
    assert frame.loc[0, "date"] == "2024-01-01"
    assert frame.loc[0, "discharge_cfs_15min_mean"] == 10.0
    assert frame.loc[0, "discharge_cfs_15min_max"] == 10.0
    assert frame.loc[0, "water_year"] == 2024
