import io

import numpy as np
import pytest
import tifffile

from homesol import google_solar, utm

MUMBAI = (72.8777, 19.0760)
ZONE = 43
PIXEL = 0.5


GEO_KEYS = (34735, "H", 16, (1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 32600 + ZONE))


def geotiff(data: np.ndarray, left: float, top: float, placement: str = "transformation") -> bytes:
    """A north-up, tiled, deflate-compressed UTM GeoTIFF like the ones the Solar API serves."""
    if placement == "transformation":
        # The form Google's files use: a 4x4 matrix from (column, row) to (easting, northing).
        position = [(34264, "d", 16, (PIXEL, 0, 0, left, 0, -PIXEL, 0, top, 0, 0, 0, 0, 0, 0, 0, 1))]
    else:
        position = [(33550, "d", 3, (PIXEL, PIXEL, 0.0)), (33922, "d", 6, (0.0, 0.0, 0.0, left, top, 0.0))]
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, data, compression="deflate", tile=(64, 64), extratags=[*position, GEO_KEYS])
    return buffer.getvalue()


@pytest.fixture
def scene():
    """A 60 m tile: open ground at 1500, a 10 m square roof whose west half is shaded to 900."""
    east, north = utm.forward(*MUMBAI, ZONE)
    left, top = east - 30, north + 30
    flux = np.full((120, 120), 1500, dtype=np.float32)
    flux[50:70, 50:60] = 900  # west half of the roof
    flux[0:5, :] = google_solar.NO_DATA
    dsm = np.full((120, 120), 12.0, dtype=np.float32)  # ground at 12 m above sea level
    dsm[50:70, 50:70] = 21.0  # the roof, 9 m up
    dsm[20:40, 80:100] = 60.0  # a tower nearby
    corners = [(east - 5, north - 5), (east + 5, north - 5), (east + 5, north + 5), (east - 5, north + 5)]
    roof = [utm.inverse(x, y, ZONE) for x, y in corners]
    return google_solar.read_raster(geotiff(flux, left, top)), google_solar.read_raster(geotiff(dsm, left, top)), roof


def test_raster_is_placed_on_the_ground_from_its_tags(scene):
    flux, _, _ = scene
    east, north = utm.forward(*MUMBAI, ZONE)
    assert flux.zone == (ZONE, True)
    assert flux.pixel_of(east, north) == pytest.approx((60, 60))


def test_both_ways_of_placing_a_raster_agree():
    data = np.ones((120, 120), dtype=np.float32)
    by_matrix = google_solar.read_raster(geotiff(data, 271560.0, 2117875.5))
    by_tiepoint = google_solar.read_raster(geotiff(data, 271560.0, 2117875.5, placement="tiepoint"))
    for raster in (by_matrix, by_tiepoint):
        assert (raster.left, raster.top, raster.pixel_x, raster.pixel_y) == (271560.0, 2117875.5, 0.5, 0.5)


def test_sun_map_covers_the_roof_and_shows_the_shaded_half(scene):
    flux, dsm, roof = scene
    result = google_solar.analyse(flux, dsm, roof)

    assert len(result["cells"]) == 400  # 10 m x 10 m at 0.5 m
    assert result["cell_size_m"] == 0.5
    assert result["open_sky_sunlight"] == 1500
    assert result["yearly_sunlight"] == 1200

    by_side = {"west": [], "east": []}
    for cell in result["cells"]:
        centre_lng = sum(p[0] for p in cell["polygon"]) / 4
        by_side["west" if centre_lng < MUMBAI[0] else "east"].append(cell["access"])
    assert set(by_side["west"]) == {0.6} and set(by_side["east"]) == {1.0}


def test_cells_sit_where_the_roof_is(scene):
    flux, dsm, roof = scene
    cells = google_solar.analyse(flux, dsm, roof)["cells"]
    lngs = [p[0] for c in cells for p in c["polygon"]]
    lats = [p[1] for c in cells for p in c["polygon"]]
    assert min(lngs) == pytest.approx(min(p[0] for p in roof), abs=1e-6)
    assert max(lats) == pytest.approx(max(p[1] for p in roof), abs=1e-6)


def test_roof_height_is_measured_above_nearby_ground(scene):
    flux, dsm, roof = scene
    assert google_solar.analyse(flux, dsm, roof)["roof_height_m"] == 9.0


def test_large_roofs_are_merged_into_fewer_cells(scene):
    flux, dsm, _ = scene
    east, north = utm.forward(*MUMBAI, ZONE)
    big = [utm.inverse(east + dx, north + dy, ZONE) for dx, dy in [(-28, -25), (28, -25), (28, 25), (-28, 25)]]
    result = google_solar.analyse(flux, dsm, big)
    assert len(result["cells"]) <= google_solar.MAX_CELLS
    assert result["cell_size_m"] == 1.5


def test_a_roof_outside_the_data_is_reported_as_unavailable(scene):
    flux, dsm, _ = scene
    elsewhere = [(72.90, 19.10), (72.9001, 19.10), (72.9001, 19.1001)]
    with pytest.raises(google_solar.SolarDataUnavailable):
        google_solar.analyse(flux, dsm, elsewhere)


def test_no_key_means_unavailable_not_an_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(google_solar.SolarDataUnavailable):
        google_solar.fetch([(72.8, 19.1), (72.8001, 19.1), (72.8001, 19.1001)])


@pytest.fixture
def street():
    """Two joined flat roofs at different heights, a rooftop tank, a tree and open ground."""
    east, north = utm.forward(*MUMBAI, ZONE)
    left, top = east - 30, north + 30
    heights = np.full((120, 120), 10.0, dtype=np.float32)
    mask = np.zeros((120, 120), dtype=bool)
    heights[40:80, 20:60] = 16.0  # house A, 6 m up
    heights[40:80, 60:100] = 19.5  # house B, joined to A but a floor higher
    heights[50:56, 30:36] = 18.0  # water tank on A
    mask[40:80, 20:100] = True
    # A tree canopy: as high as a roof, but a dome that falls away gradually with no walls.
    rows, cols = np.mgrid[0:120, 0:120]
    dome = 17.0 - 0.012 * ((rows - 100) ** 2 + (cols - 35) ** 2)
    heights[84:117, 19:52] = np.maximum(heights[84:117, 19:52], dome[84:117, 19:52])
    heights[20:34, 70:100] = 15.0  # a shed Google has not marked as a building
    raster = google_solar.read_raster(geotiff(heights, left, top))

    def at(row: int, col: int) -> tuple[float, float]:
        return utm.inverse(left + (col + 0.5) * PIXEL, top - (row + 0.5) * PIXEL, ZONE)

    return raster, mask, at


def test_a_tap_outlines_one_roof_and_stops_at_the_neighbours_step(street):
    raster, mask, at = street
    found = google_solar.find_surface(raster, mask, *at(70, 40))
    assert found["found"] and not found["cut_off"]
    assert found["height_m"] == 6.0 and found["floors"] == 2
    # House A is 20 m x 20 m less the 3 m x 3 m tank.
    assert found["area_m2"] == pytest.approx(400 - 9, abs=6)
    lngs = [p[0] for p in found["roof"]]
    assert max(lngs) == pytest.approx(at(60, 59.5)[0], abs=2e-6)
    assert len(found["roof"]) <= 12


def test_a_tap_on_a_tree_or_on_open_ground_is_not_a_roof(street):
    raster, mask, at = street
    tree = google_solar.find_surface(raster, mask, *at(100, 35))
    assert tree["found"] is False and tree["kind"] == "not_building"
    assert google_solar.find_surface(raster, mask, *at(10, 10))["kind"] == "ground"


def test_a_walled_building_missing_from_googles_mask_is_still_a_roof(street):
    raster, mask, at = street
    shed = google_solar.find_surface(raster, mask, *at(27, 85))
    assert shed["found"] and shed["height_m"] == 5.0
    assert shed["area_m2"] == pytest.approx(7 * 15, abs=4)


def test_outline_of_open_ground_is_reported_as_ground_and_ignores_buildings_inside_it():
    east, north = utm.forward(*MUMBAI, ZONE)
    left, top = east - 30, north + 30
    heights = np.full((120, 120), 10.0, dtype=np.float32)
    heights[60:80, 60:80] = 19.0  # a building at the corner of the plot
    flux = np.full((120, 120), 1500, dtype=np.float32)
    plot = [utm.inverse(left + c * PIXEL, top - r * PIXEL, ZONE) for r, c in [(30, 30), (30, 80), (80, 80), (80, 30)]]
    result = google_solar.analyse(
        google_solar.read_raster(geotiff(flux, left, top)), google_solar.read_raster(geotiff(heights, left, top)), plot
    )
    assert result["surface"] == "ground"
    assert result["structures_m2"] == pytest.approx(100, abs=3)
    assert result["surface_area_m2"] == pytest.approx(625 - 100, abs=6)


def test_photo_is_a_valid_png_placed_at_the_tile_corners():
    import base64
    import zlib

    east, north = utm.forward(*MUMBAI, ZONE)
    rgb = np.zeros((40, 60, 3), dtype=np.uint8)
    rgb[..., 0] = 200
    photo = google_solar.picture(geotiff(rgb, east, north))

    png = base64.b64decode(photo["image"].split(",")[1])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(png[16:20], "big") == 60 and int.from_bytes(png[20:24], "big") == 40
    idat = png[png.index(b"IDAT") + 4 : png.index(b"IEND") - 8]
    pixels = zlib.decompress(idat)
    assert pixels[:4] == bytes([0, 200, 0, 0])  # filter byte, then the first red pixel

    top_left, _, bottom_right, _ = photo["corners"]
    assert top_left == pytest.approx(list(MUMBAI), abs=1e-6)
    assert utm.forward(*bottom_right, ZONE) == pytest.approx((east + 30, north - 20), abs=0.01)
