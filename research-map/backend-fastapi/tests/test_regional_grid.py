from __future__ import annotations

from shapely.geometry import box

from app.providers import _regional_points


def test_regional_points_cover_bbox_and_flag_water_nodes():
    water = box(107.0, 20.5, 107.3, 20.8)          # water only in part of the region
    points = _regional_points((106.5, 20.3, 107.5, 21.0), 0.125, water)
    lons = sorted({p[0] for p in points}); lats = sorted({p[1] for p in points})
    assert lons[0] == 106.5 and lons[-1] == 107.5 and len(lons) == 9
    assert lats[0] == 20.3 and lats[-1] == 20.925 and len(lats) == 6   # never past the bbox edge
    wet = [p for p in points if p[2]]
    assert 0 < len(wet) < len(points)
    assert all(106.875 <= lon <= 107.375 for lon, lat, _ in wet)       # cells touching the water box only


def test_regional_points_without_mask_are_all_water():
    points = _regional_points((107.0, 20.5, 107.25, 20.75), 0.125, None)
    assert len(points) == 9 and all(p[2] for p in points)


def _hourly(start, **series):
    from datetime import timedelta
    times = [(start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00") for h in range(48)]
    return {"time": times, **{name: [value] * 48 for name, value in series.items()}}


def test_regional_context_has_heat_layers_sst_on_water_and_air_everywhere():
    import asyncio
    from datetime import datetime, timezone

    import httpx

    from app.providers import fetch_open_meteo_context

    start = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    def handler(request: httpx.Request) -> httpx.Response:
        n = len(request.url.params["latitude"].split(","))
        if "marine" in request.url.host:
            hourly = _hourly(start, wave_height=0.4, wave_direction=90, wave_period=4, ocean_current_velocity=0.5,
                             ocean_current_direction=180, sea_level_height_msl=0.2, sea_surface_temperature=27.5)
        else:
            hourly = _hourly(start, wind_speed_10m=10, wind_direction_10m=45, wind_gusts_10m=15, precipitation=0, temperature_2m=24.0)
        return httpx.Response(200, json=[{"latitude": 20.5, "longitude": 107.0, "hourly": hourly}] * n)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_open_meteo_context(20.7, 107.0, 60, client, bbox=[107.0, 20.5, 107.25, 20.75],
                                                  region_step=0.125, region_water=box(107.0, 20.5, 107.1, 20.6))

    layers = {layer["layer"]: layer for layer in asyncio.run(run())}
    sst, air = layers["sst"], layers["air_temp"]
    assert sst["kind"] == air["kind"] == "scalar_grid"
    assert len(air["geojson"]["features"]) == 9                       # every node: air temperature is real over land
    assert 0 < len(sst["geojson"]["features"]) < 9                    # SST only where the cell touches water
    assert {f["properties"]["value"] for f in sst["geojson"]["features"]} == {27.5}
    assert sst["raster"]["step_deg"] == 0.125 and sst["provenance"]["product_id"] == "open-meteo-marine"
