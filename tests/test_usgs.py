import responses

from charles.http import create_session
from charles.usgs import ogc_items


@responses.activate
def test_pagination_and_numeric_conversion():
    url = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/daily/items"
    second = url + "?page=2"
    responses.add(
        responses.GET,
        url,
        json={
            "features": [
                {"properties": {"time": "2020-01-01T00:00:00Z", "value": "12.5",
                               "approval_status": "Approved"}}
            ],
            "links": [{"rel": "next", "href": second}],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        second,
        json={"features": [
            {"properties": {"time": "2020-01-02T00:00:00Z", "value": "18",
                           "approval_status": "Provisional"}}
        ], "links": []},
        status=200,
    )
    rows = ogc_items(create_session(), "daily", {"limit": 10000})
    assert [row["value"] for row in rows] == [12.5, 18.0]
    assert rows[1]["approval_status"] == "Provisional"


@responses.activate
def test_empty_result():
    url = "https://api.waterdata.usgs.gov/ogcapi/v1/collections/continuous/items"
    responses.add(responses.GET, url, json={"features": [], "links": []}, status=200)
    assert ogc_items(create_session(), "continuous", {}) == []
