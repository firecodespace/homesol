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


def test_both_ways_of_placing_a_raster_agree():
    data = np.ones((120, 120), dtype=np.float32)
    by_matrix = google_solar.read_raster(geotiff(data, 271560.0, 2117875.5))
    by_tiepoint = google_solar.read_raster(geotiff(data, 271560.0, 2117875.5, placement="tiepoint"))
    for raster in (by_matrix, by_tiepoint):
        assert (raster.left, raster.top, raster.pixel_x, raster.pixel_y) == (271560.0, 2117875.5, 0.5, 0.5)


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


def test_no_key_means_unavailable_not_an_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    with pytest.raises(google_solar.SolarDataUnavailable):
        google_solar.fetch_tile(72.8, 19.1, 50)
