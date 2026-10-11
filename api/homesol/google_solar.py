"""
Access to Google's Solar API and the raster files it serves.

For each covered place Google publishes a 3D surface model (heights), the
yearly sunlight reaching every point of it with shade already worked out, a
building mask and a photo. This module fetches and decodes them; `site.py`
turns them into a model of one property.
"""

import base64
import io
import logging
import math
import os
import struct
import time
import warnings
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import numpy as np
import tifffile

from . import utm

API = "https://solar.googleapis.com/v1"
NO_DATA = -9999
PIXEL_M = 0.25


class SolarDataUnavailable(Exception):
    """No usable Google data for this location (not covered, or no key configured)."""


@dataclass
class Raster:
    """One band of a north-up GeoTIFF with its placement on the ground."""

    data: np.ndarray
    #: Map coordinates of the top-left corner, and the size of one pixel.
    left: float
    top: float
    pixel_x: float
    pixel_y: float
    #: UTM zone and hemisphere, or None when coordinates are plain longitude/latitude.
    zone: tuple[int, bool] | None

    def to_map(self, lng: float, lat: float) -> tuple[float, float]:
        return utm.forward(lng, lat, *self.zone) if self.zone else (lng, lat)

    def to_lnglat(self, x: float, y: float) -> tuple[float, float]:
        return utm.inverse(x, y, *self.zone) if self.zone else (x, y)

    def pixel_of(self, x: float, y: float) -> tuple[float, float]:
        """Fractional (column, row) of a map coordinate."""
        return (x - self.left) / self.pixel_x, (self.top - y) / self.pixel_y

    def metres_per_pixel(self, lat: float) -> float:
        return self.pixel_x if self.zone else self.pixel_x * 111_320 * math.cos(math.radians(lat))


def _read_plain(content: bytes) -> np.ndarray:
    """Pixel values only. Google's mask files carry a no-data tag the reader warns about; it is harmless."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        logging.getLogger("tifffile").setLevel(logging.ERROR)
        return tifffile.imread(io.BytesIO(content))


def read_raster(content: bytes) -> Raster:
    with tifffile.TiffFile(io.BytesIO(content)) as tif:
        page = tif.pages[0]
        data = page.asarray()
        geo = page.geotiff_tags
    # Files place themselves either with a 4x4 transformation (what Google serves) or a
    # tiepoint plus pixel scale. Both describe a north-up grid here.
    matrix, scale, tie = geo.get("ModelTransformation"), geo.get("ModelPixelScale"), geo.get("ModelTiepoint")
    if matrix is not None:
        matrix = np.asarray(matrix, dtype=float).reshape(4, 4)
        if matrix[0, 1] or matrix[1, 0]:
            raise SolarDataUnavailable("Google's data for this location is rotated, which is not supported.")
        left, top, pixel_x, pixel_y = matrix[0, 3], matrix[1, 3], matrix[0, 0], -matrix[1, 1]
    elif scale and tie:
        left, top = tie[3] - tie[0] * scale[0], tie[4] + tie[1] * scale[1]
        pixel_x, pixel_y = scale[0], scale[1]
    else:
        raise SolarDataUnavailable("Google's data for this location has no position information.")
    epsg = geo.get("ProjectedCSTypeGeoKey")
    zone = utm.from_epsg(int(epsg)) if epsg else None
    return Raster(np.asarray(data), float(left), float(top), float(pixel_x), float(pixel_y), zone)


def _inside(xs: np.ndarray, ys: np.ndarray, polygon: list[tuple[float, float]]) -> np.ndarray:
    """Which points fall inside a polygon (even-odd rule), vectorised."""
    inside = np.zeros(xs.shape, dtype=bool)
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        crosses = (yi > ys) != (yj > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            inside ^= crosses & (xs < (xj - xi) * (ys - yi) / (yj - yi) + xi)
        j = i
    return inside


def _png(rgb: np.ndarray) -> bytes:
    """Encode an 8-bit RGB array as a PNG, without an imaging library."""
    rows, cols = rgb.shape[:2]
    raw = np.concatenate([np.zeros((rows, 1), dtype=np.uint8), rgb.reshape(rows, cols * 3)], axis=1).tobytes()

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", cols, rows, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def picture(content: bytes) -> dict | None:
    """
    Google's own photo of the area, placed on the map.

    Google's measurements line up with Google's imagery, which can sit a few
    metres off another provider's. Showing this photo under the outline keeps
    what the user sees and what was measured in the same place.
    """
    try:
        raster = read_raster(content)
    except SolarDataUnavailable:
        return None
    rgb = raster.data
    if rgb.ndim != 3:
        return None
    if rgb.shape[0] == 3:
        rgb = np.moveaxis(rgb, 0, 2)
    rgb = np.ascontiguousarray(rgb[..., :3].astype(np.uint8))
    rows, cols = rgb.shape[:2]
    right, bottom = raster.left + cols * raster.pixel_x, raster.top - rows * raster.pixel_y
    corners = [(raster.left, raster.top), (right, raster.top), (right, bottom), (raster.left, bottom)]
    return {
        "image": "data:image/png;base64," + base64.b64encode(_png(rgb)).decode(),
        #: Top-left, top-right, bottom-right, bottom-left as [lng, lat].
        "corners": [list(raster.to_lnglat(x, y)) for x, y in corners],
    }


def _layers(
    client: httpx.Client,
    key: str,
    lng: float,
    lat: float,
    radius_m: float,
    view: str = "IMAGERY_AND_ANNUAL_FLUX_LAYERS",
    pixel_m: float = PIXEL_M,
) -> dict:
    params = {
        "location.latitude": f"{lat:.6f}",
        "location.longitude": f"{lng:.6f}",
        "radiusMeters": min(175, math.ceil(radius_m)),
        "view": view,
        # The API's default asks for its best imagery only, which most of the world lacks.
        # BASE is the minimum accepted; better imagery is returned where it exists.
        "requiredQuality": "BASE",
        "pixelSizeMeters": pixel_m,
        "key": key,
    }
    for attempt in range(3):
        response = client.get(f"{API}/dataLayers:get", params=params)
        if response.status_code < 500 or attempt == 2:
            break
        time.sleep(0.4 * (attempt + 1))
    if response.status_code == 404:
        raise SolarDataUnavailable("Google has no 3D survey of this location yet.")
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", "")
        except ValueError:
            detail = ""
        raise SolarDataUnavailable(f"Google's Solar API is not answering ({response.status_code}). {detail}".strip())
    return response.json()


def _download(client: httpx.Client, key: str, url: str) -> bytes:
    # The URL already carries the file id; passing params would replace it.
    # Google's file server occasionally answers 502; the same request then succeeds.
    for attempt in range(3):
        tiff = client.get(f"{url}&key={key}")
        if tiff.status_code < 500 or attempt == 2:
            break
        time.sleep(0.4 * (attempt + 1))
    tiff.raise_for_status()
    return tiff.content


def _key() -> str:
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        raise SolarDataUnavailable("Measured 3D data is not switched on.")
    return key


PREVIEW_RADIUS_M = 110
PREVIEW_PIXEL_M = 0.5


def area_picture(lng: float, lat: float) -> dict:
    """Google's photo of the neighbourhood around a point, for the user to tap their roof on."""
    key = _key()
    with httpx.Client(timeout=40) as client:
        layers = _layers(client, key, lng, lat, PREVIEW_RADIUS_M, view="IMAGERY_LAYERS", pixel_m=PREVIEW_PIXEL_M)
        photo = picture(_download(client, key, layers["rgbUrl"])) if layers.get("rgbUrl") else None
    if photo is None:
        raise SolarDataUnavailable("Google returned no photo for this location.")
    return photo




@dataclass
class Tile:
    """Everything Google has for one square of ground, on one pixel grid."""

    #: Surface height in metres above sea level, including buildings and trees.
    heights: np.ndarray
    #: Yearly sunlight at each point, kWh per kW of panel per year, shade included.
    flux: np.ndarray | None
    #: True where Google marks a building.
    mask: np.ndarray | None
    rgb: np.ndarray | None
    #: Placement of the grid on the ground.
    frame: Raster
    pixel_m: float
    imagery_date: str | None = None
    imagery_quality: str | None = None

    def corner_lnglat(self, col: float, row: float) -> list[float]:
        """Map position of a grid corner; (0, 0) is the top-left of the top-left pixel."""
        f = self.frame
        return list(f.to_lnglat(f.left + col * f.pixel_x, f.top - row * f.pixel_y))

    def pixel_of(self, lng: float, lat: float) -> tuple[float, float]:
        return self.frame.pixel_of(*self.frame.to_map(lng, lat))


def fetch_tile(lng: float, lat: float, radius_m: float, pixel_m: float = PIXEL_M) -> Tile:
    """Download heights, sunlight, building mask and photo around a point."""
    key = _key()
    with httpx.Client(timeout=40) as client:
        layers = _layers(client, key, lng, lat, radius_m, pixel_m=pixel_m)
        names = ("dsmUrl", "annualFluxUrl", "maskUrl", "rgbUrl")
        with ThreadPoolExecutor(max_workers=4) as pool:
            files = {n: pool.submit(_download, client, key, layers[n]) for n in names if layers.get(n)}
            content = {n: f.result() for n, f in files.items()}
    if "dsmUrl" not in content:
        raise SolarDataUnavailable("Google has no height data for this location.")

    frame = read_raster(content["dsmUrl"])
    heights = (frame.data if frame.data.ndim == 2 else frame.data[0]).astype(np.float32)

    def plane(name: str) -> np.ndarray | None:
        if name not in content:
            return None
        data = _read_plain(content[name])
        data = data if data.ndim == 2 else (data[0] if data.shape[0] <= 4 else data[..., 0])
        return data if data.shape == heights.shape else None

    flux = plane("annualFluxUrl")
    mask = plane("maskUrl")
    rgb = None
    if "rgbUrl" in content:
        rgb = _read_plain(content["rgbUrl"])
        if rgb.ndim == 3 and rgb.shape[0] == 3:
            rgb = np.moveaxis(rgb, 0, 2)
        rgb = np.ascontiguousarray(rgb[..., :3].astype(np.uint8)) if rgb.ndim == 3 and rgb.shape[:2] == heights.shape else None

    date = layers.get("imageryDate") or {}
    return Tile(
        heights=heights,
        flux=flux.astype(np.float32) if flux is not None else None,
        mask=(mask > 0) if mask is not None else None,
        rgb=rgb,
        frame=frame,
        pixel_m=frame.metres_per_pixel(lat),
        imagery_date=f"{date['year']:04d}-{date['month']:02d}-{date['day']:02d}" if {"year", "month", "day"} <= date.keys() else None,
        imagery_quality=layers.get("imageryQuality"),
    )


def png_data_url(rgb: np.ndarray) -> str:
    return "data:image/png;base64," + base64.b64encode(_png(rgb)).decode()
