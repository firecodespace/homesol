import base64
import math
import zlib

import numpy as np
import pytest

from homesol import site, utm
from homesol.google_solar import Raster, SolarDataUnavailable, Tile

MUMBAI = (72.8777, 19.0760)
ZONE = 43
PX = 0.5
N = 160  # an 80 m tile


def make_tile(heights: np.ndarray, flux: np.ndarray | None = None, mask: np.ndarray | None = None) -> Tile:
    east, north = utm.forward(*MUMBAI, ZONE)
    frame = Raster(heights, east - N * PX / 2, north + N * PX / 2, PX, PX, (ZONE, True))
    if flux is None:
        flux = np.full(heights.shape, 1500, dtype=np.float32)
    return Tile(heights.astype(np.float32), flux, mask, np.zeros((*heights.shape, 3), np.uint8), frame, PX)


def lnglat(tile: Tile, row: float, col: float) -> tuple[float, float]:
    return tuple(tile.corner_lnglat(col + 0.5, row + 0.5))


@pytest.fixture
def street():
    """Ground at 10 m; house A (6 m up) joined to taller house B; a tank on A; a tree; an unmarked shed."""
    heights = np.full((N, N), 10.0)
    mask = np.zeros((N, N), dtype=bool)
    heights[60:100, 40:80] = 16.0  # house A, 20 m x 20 m
    heights[60:100, 80:120] = 19.5  # house B, a floor higher, to the east
    heights[70:74, 50:54] = 18.0  # tank on A, 2 m x 2 m, 2 m tall
    mask[60:100, 40:120] = True
    rows, cols = np.mgrid[0:N, 0:N]
    dome = 22.0 - 0.03 * ((rows - 130) ** 2 + (cols - 50) ** 2)
    heights[105:155, 25:75] = np.maximum(heights[105:155, 25:75], dome[105:155, 25:75])  # a tall tree to the south
    heights[20:34, 90:120] = 15.0  # shed Google has not marked
    return make_tile(heights, mask=mask)


def test_components_are_split_by_gaps_and_by_height_steps():
    mask = np.zeros((6, 10), dtype=bool)
    mask[1:5, 1:4] = mask[1:5, 6:9] = True
    assert site._components(mask).max() == 2
    mask[1:5, 4:6] = True  # now one block...
    heights = np.zeros((6, 10))
    heights[:, 5:] = 3.0  # ...but with a 3 m step down the middle
    assert site._components(mask).max() == 1
    assert site._components(mask, heights, max_step=0.5).max() == 2


def test_a_tap_finds_one_flat_roof_and_stops_at_the_neighbours_step(street):
    surface = site.surface_at(street, *lnglat(street, 90, 60))
    assert isinstance(surface, site.Surface)
    assert surface.kind == "roof"
    assert surface.height_m == pytest.approx(6.0, abs=0.1)
    assert surface.tilt_deg < 1
    # House A is 20 m x 20 m less the 2 m x 2 m tank.
    assert surface.area_m2 == pytest.approx(400 - 4, abs=8)
    assert not surface.region[80, 100]  # not house B


def test_taps_on_ground_or_a_tree_are_not_roofs_but_an_unmarked_walled_building_is(street):
    assert site.surface_at(street, *lnglat(street, 10, 10))["kind"] == "ground"
    assert site.surface_at(street, *lnglat(street, 122, 50))["found"] is False  # the tree
    shed = site.surface_at(street, *lnglat(street, 27, 105))
    assert isinstance(shed, site.Surface) and shed.height_m == pytest.approx(5.0, abs=0.1)


def test_a_tap_follows_a_sloped_roof_face_up_to_its_ridge():
    # A gabled roof: ridge running east-west at row 80, eaves at rows 60 and 100, pitch about 27 degrees.
    heights = np.full((N, N), 10.0)
    rows = np.arange(N)[:, None]
    pitch = 0.5 * PX  # metres of rise per row
    roof = 15.0 + pitch * (20 - np.abs(rows - 80))
    heights[60:100, 40:120] = np.broadcast_to(roof, (N, N))[60:100, 40:120]
    mask = np.zeros((N, N), dtype=bool)
    mask[60:100, 40:120] = True
    tile = make_tile(heights, mask=mask)

    south_face = site.surface_at(tile, *lnglat(tile, 92, 80))
    assert isinstance(south_face, site.Surface)
    assert south_face.kind == "sloped_roof"
    assert south_face.tilt_deg == pytest.approx(math.degrees(math.atan(0.5)), abs=1.5)
    assert south_face.faces_deg == pytest.approx(180, abs=5)  # falls towards the south
    assert south_face.region[62:98, 45:115].mean() < 0.6  # only one face of the roof
    assert south_face.region[84:98, 45:115].mean() > 0.9


def test_outline_of_open_ground_ignores_the_building_inside_it():
    heights = np.full((N, N), 10.0)
    heights[60:80, 60:80] = 19.0  # a building at the corner of the plot
    tile = make_tile(heights)
    inside = np.zeros((N, N), dtype=bool)
    inside[30:80, 30:80] = True
    region, plane = site.surface_in_outline(tile.heights, inside)
    surface = site.describe(tile, region, plane)
    assert surface.kind == "ground"
    assert surface.area_m2 == pytest.approx((50 * 50 - 20 * 20) * PX * PX, abs=5)


def test_outline_on_a_hillside_is_sloped_ground_with_its_facing_direction():
    cols = np.arange(N)[None, :]
    heights = np.broadcast_to(100.0 + 0.3 * PX * cols, (N, N)).copy()  # rises to the east, 0.3 m per metre
    tile = make_tile(heights)
    inside = np.zeros((N, N), dtype=bool)
    inside[50:110, 50:110] = True
    region, plane = site.surface_in_outline(tile.heights, inside)
    surface = site.describe(tile, region, plane)
    assert surface.kind == "sloped_ground"
    assert surface.tilt_deg == pytest.approx(math.degrees(math.atan(0.3)), abs=0.5)
    assert surface.faces_deg == pytest.approx(270, abs=2)  # faces west, downhill


def test_obstructions_are_measured_named_and_placed(street):
    surface = site.surface_at(street, *lnglat(street, 90, 60))
    labels, found = site.find_obstructions(street, surface)

    by_kind = {o["kind"]: o for o in found}
    tank = by_kind["tank"]
    assert tank["on_surface"] and tank["height_above_m"] == pytest.approx(2.0, abs=0.1)
    assert tank["area_m2"] == pytest.approx(4, abs=1)

    neighbour = by_kind["building"]
    assert not neighbour["on_surface"]
    assert neighbour["height_above_m"] == pytest.approx(3.5, abs=0.1)
    assert neighbour["direction"] == "east" and neighbour["distance_m"] < 1.5

    tree = by_kind["tree"]
    assert tree["direction"] == "south" and 4 < tree["distance_m"] < 12
    assert tree["height_above_m"] == pytest.approx(5.5, abs=1)

    assert labels[90, 60] == 1 and labels[71, 51] == tank["id"] and labels[80, 100] == neighbour["id"]
    # The shed to the north-east is lower than the roof, so it is not an obstruction.
    assert labels[27, 105] == 0


def test_site_model_packs_rasters_the_app_can_decode(street):
    surface = site.surface_at(street, *lnglat(street, 90, 60))
    model = site.build(street, surface, site._region_outline(street, surface.region), "tap")

    def unpack(text: str, dtype: str) -> np.ndarray:
        return np.frombuffer(zlib.decompress(base64.b64decode(text)), dtype=dtype).reshape(N, N)

    heights = unpack(model["heights_cm"], "<u2") / 100 + model["height_floor_m"]
    assert heights[90, 60] == pytest.approx(16.0, abs=0.01) and heights[5, 5] == pytest.approx(10.0, abs=0.01)
    assert unpack(model["access"], "u1")[90, 60] == 250
    assert unpack(model["labels"], "u1")[90, 60] == 1

    assert model["surface"]["kind"] == "roof" and model["surface"]["floors"] == 2
    assert model["grid"]["pixel_m"] == PX and len(model["grid"]["corners"]) == 4
    top_left = model["grid"]["corners"][0]
    assert utm.forward(*top_left, ZONE) == pytest.approx((street.frame.left, street.frame.top), abs=0.01)
    assert len(model["outline"]) <= 12
    assert model["photo"].startswith("data:image/png;base64,")


def test_shaded_parts_of_the_surface_get_lower_access():
    heights = np.full((N, N), 10.0)
    heights[60:100, 40:80] = 16.0
    flux = np.full((N, N), 1500, dtype=np.float32)
    flux[60:100, 40:60] = 900  # west half shaded
    tile = make_tile(heights, flux=flux)
    surface = site.surface_at(tile, *lnglat(tile, 90, 70))
    model = site.build(tile, surface, [], "tap")
    access = np.frombuffer(zlib.decompress(base64.b64decode(model["access"])), dtype="u1").reshape(N, N)
    assert access[80, 50] == 150 and access[80, 70] == 250
    assert model["sunlight"]["share"] == pytest.approx(0.8, abs=0.01)


def test_missing_sunlight_data_is_reported_as_unavailable(street):
    street.flux = None
    surface = site.surface_at(street, *lnglat(street, 90, 60))
    with pytest.raises(SolarDataUnavailable):
        site.build(street, surface, [], "tap")
