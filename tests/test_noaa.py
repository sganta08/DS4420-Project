from charles.noaa import parse_noaa_csv


def test_noaa_csv_and_trace():
    text = (
        "DATE,PRCP,PRCP_ATTRIBUTES,SNOW,SNWD,TMAX,TMIN,TAVG,AWND\n"
        '2024-01-01,0.00,"T,,Z,",0,1,40,20,30,5\n'
    )
    frame = parse_noaa_csv(text)
    assert bool(frame.loc[0, "precip_trace"])
    assert frame.loc[0, "precip_in"] == 0
    assert frame.loc[0, "tmax_f"] == 40


def test_empty_noaa_body():
    assert parse_noaa_csv("").empty
