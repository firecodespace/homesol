"""
Measured rooftop sun from Google's Solar API.

Google publishes, for each covered building, a 3D surface model and the yearly
sunlight reaching every point of it with shade from surrounding buildings and
trees already worked out. Where that exists, it replaces hand-marked
obstructions as the source of the roof's sun map.
"""

import base64
import io
import logging
import math
import os
import struct
import warnings
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx
import numpy as np
import tifffile

from . import utm

API = "https://solar.googleapis.com/v1"
NO_DATA = -9999
PIXEL_M = 0.25
#: Pixels within this height of the surface's own level belong to it; the rest are
#: rooftop structures above it or ground and lower roofs below it.
LEVEL_BAND_M = 1.5
#: A surface lower than this above nearby ground is open land, not a roof.
ROOF_MIN_HEIGHT_M = 1.5
#: Largest height step between neighbouring pixels of one continuous surface.
SURFACE_STEP_M = 0.3
#: How far a surface may drift from the tapped height, which allows gently sloped roofs.
SURFACE_DRIFT_M = 2.0
TAP_RADIUS_M = 60
#: Height change just past a surface's edge that counts as a wall.
WALL_DROP_M = 1.2
#: A raised surface Google has not marked as a building is still a roof if this much of its edge is wall.
ROOF_WALL_SHARE = 0.7
#: How far beyond the roof to fetch, so nearby ground is included for the height estimate.
MARGIN_M = 25
MAX_CELLS = 2500
FLOOR_HEIGHT_M = 3.0


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


#: Ground is looked for within this distance of the surface, so a distant dip does not inflate heights.
GROUND_SEARCH_M = 12


def _ground_level(heights: np.ndarray, valid: np.ndarray, surface: np.ndarray, pixel_m: float) -> float:
    """Height of the ground beside a surface: the low end of what surrounds it."""
    rows, cols = np.nonzero(surface)
    pad = math.ceil(GROUND_SEARCH_M / pixel_m)
    r0, r1 = max(0, rows.min() - pad), min(heights.shape[0], rows.max() + pad + 1)
    c0, c1 = max(0, cols.min() - pad), min(heights.shape[1], cols.max() + pad + 1)
    around = valid[r0:r1, c0:c1] & ~surface[r0:r1, c0:c1]
    if around.sum() < 20:
        around = valid[r0:r1, c0:c1]
    return float(np.percentile(heights[r0:r1, c0:c1][around], 5))


def analyse(flux: Raster, dsm: Raster | None, roof: list[tuple[float, float]]) -> dict:
    """
    Sun map of an outlined area from Google's yearly-sunlight and height rasters.

    The outline is first sorted by height. Its dominant level is the surface
    panels would sit on: a roof, or open ground if that level is near ground
    height. Pixels well above that level (stair rooms, tanks) or below it
    (ground beside the building, a lower terrace) are left out, so a loosely
    drawn outline still describes one surface.

    Each cell's `access` is its yearly sunlight as a share of what an open,
    unshaded spot nearby receives, the same scale the hand-marked shading uses.
    """
    roof_map = [flux.to_map(lng, lat) for lng, lat in roof]
    rows, cols = flux.data.shape[-2:]
    values = flux.data if flux.data.ndim == 2 else flux.data[0]

    col_idx, row_idx = np.meshgrid(np.arange(cols), np.arange(rows))
    xs = flux.left + (col_idx + 0.5) * flux.pixel_x
    ys = flux.top - (row_idx + 0.5) * flux.pixel_y
    valid = np.isfinite(values) & (values > 0)
    outlined = _inside(xs, ys, roof_map) & valid
    if not outlined.any():
        raise SolarDataUnavailable("Google has no sunlight data on this spot.")

    lat = sum(p[1] for p in roof) / len(roof)
    pixel_m = flux.metres_per_pixel(lat)
    pixel_area = pixel_m * pixel_m

    surface, level_height, above_m2, below_m2 = None, None, 0.0, 0.0
    on_surface = outlined
    heights = None
    if dsm is not None:
        heights = dsm.data if dsm.data.ndim == 2 else dsm.data[0]
        if heights.shape != values.shape:
            heights = None
    if heights is not None:
        h_valid = np.isfinite(heights) & (heights > NO_DATA + 1)
        inside = outlined & h_valid
        if inside.any():
            # The dominant level is the fullest half-metre band of heights in the outline.
            bins = np.round(heights[inside] * 2) / 2
            levels, counts = np.unique(bins, return_counts=True)
            level = float(levels[counts.argmax()])
            at_level = inside & (np.abs(heights - level) <= LEVEL_BAND_M)
            # A sloped roof spreads across many bands; if the band holds too little, keep everything.
            if at_level.sum() >= 0.4 * inside.sum():
                on_surface = at_level
                above_m2 = float((inside & (heights > level + LEVEL_BAND_M)).sum() * pixel_area)
                below_m2 = float((inside & (heights < level - LEVEL_BAND_M)).sum() * pixel_area)
            level_height = float(np.median(heights[on_surface])) - _ground_level(heights, h_valid, on_surface, pixel_m)
            surface = "roof" if level_height >= ROOF_MIN_HEIGHT_M else "ground"

    # An open, unshaded surface nearby sets the scale; the surface's own best spot guards against
    # a tile where everything else is steeper or brighter than a flat roof can be.
    open_sky = float(max(np.percentile(values[valid], 95), np.percentile(values[on_surface], 99)))

    step = max(1, math.ceil(math.sqrt(on_surface.sum() / MAX_CELLS)))
    cells = []
    for r0 in range(0, rows, step):
        for c0 in range(0, cols, step):
            block = on_surface[r0 : r0 + step, c0 : c0 + step]
            if block.sum() * 2 < block.size:
                continue
            mean = float(values[r0 : r0 + step, c0 : c0 + step][block].mean())
            x0, x1 = flux.left + c0 * flux.pixel_x, flux.left + (c0 + step) * flux.pixel_x
            y0, y1 = flux.top - r0 * flux.pixel_y, flux.top - (r0 + step) * flux.pixel_y
            corners = [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]
            cells.append(
                {
                    "polygon": [list(flux.to_lnglat(x, y)) for x, y in corners],
                    "access": round(min(1.0, mean / open_sky), 3),
                }
            )

    return {
        "cells": cells,
        "cell_size_m": round(step * pixel_m, 3),
        "surface_area_m2": round(float(on_surface.sum() * pixel_area), 1),
        "yearly_sunlight": round(float(values[on_surface].mean())),
        "open_sky_sunlight": round(open_sky),
        "surface": surface,
        "roof_height_m": round(level_height, 1) if level_height is not None else None,
        #: Area inside the outline standing above the surface (stair rooms, tanks), and lying below it.
        "structures_m2": round(above_m2, 1),
        "lower_m2": round(below_m2, 1),
    }


def _grow(heights: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """The continuous surface around a pixel: neighbours joined while the height changes gently."""
    rows, cols = heights.shape
    seed_height = heights[seed]
    region = np.zeros(heights.shape, dtype=bool)
    region[seed] = True
    queue = deque([seed])
    while queue:
        r, c = queue.popleft()
        here = heights[r, c]
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < rows and 0 <= cc < cols and not region[rr, cc]:
                there = heights[rr, cc]
                if abs(there - here) <= SURFACE_STEP_M and abs(there - seed_height) <= SURFACE_DRIFT_M:
                    region[rr, cc] = True
                    queue.append((rr, cc))
    return region


def _shift(mask: np.ndarray, dr: int, dc: int) -> np.ndarray:
    out = np.zeros_like(mask)
    rows, cols = mask.shape
    out[max(dr, 0) : rows + min(dr, 0), max(dc, 0) : cols + min(dc, 0)] = mask[
        max(-dr, 0) : rows + min(-dr, 0), max(-dc, 0) : cols + min(-dc, 0)
    ]
    return out


def _tidy(region: np.ndarray) -> np.ndarray:
    """Close pinholes and drop single-pixel threads so the outline is clean."""
    neighbours = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
    grown = np.any([_shift(region, dr, dc) for dr, dc in neighbours], axis=0)
    closed = np.all([_shift(grown, dr, dc) for dr, dc in neighbours], axis=0)
    opened = np.all([_shift(closed, dr, dc) for dr, dc in neighbours], axis=0)
    return np.any([_shift(opened, dr, dc) for dr, dc in neighbours], axis=0)


def _outline(region: np.ndarray) -> list[tuple[float, float]]:
    """Outer boundary of a pixel region as (column, row) corner points, largest loop only."""
    rows, cols = region.shape
    padded = np.pad(region, 1)
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for r, c in zip(*np.nonzero(region)):
        r, c = int(r), int(c)
        # Each side facing outside becomes an edge, walked clockwise around the pixel.
        if not padded[r, c + 1]:
            edges.setdefault((c, r), []).append((c + 1, r))
        if not padded[r + 1, c + 2]:
            edges.setdefault((c + 1, r), []).append((c + 1, r + 1))
        if not padded[r + 2, c + 1]:
            edges.setdefault((c + 1, r + 1), []).append((c, r + 1))
        if not padded[r + 1, c]:
            edges.setdefault((c, r + 1), []).append((c, r))

    best: list[tuple[int, int]] = []
    best_area = 0.0
    while edges:
        start = next(iter(edges))
        loop, point = [start], start
        while True:
            targets = edges.get(point)
            if not targets:
                break
            nxt = targets.pop()
            if not targets:
                del edges[point]
            if nxt == start:
                break
            loop.append(nxt)
            point = nxt
        area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(loop, loop[1:] + loop[:1]))) / 2
        if area > best_area:
            best, best_area = loop, area
    return [(float(x), float(y)) for x, y in best]


def _simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas-Peucker on a closed loop."""
    if len(points) < 4:
        return points

    def reduce(segment: list[tuple[float, float]]) -> list[tuple[float, float]]:
        (x1, y1), (x2, y2) = segment[0], segment[-1]
        length = math.hypot(x2 - x1, y2 - y1) or 1e-9
        distances = [abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / length for x, y in segment[1:-1]]
        if not distances or max(distances) <= tolerance:
            return [segment[0], segment[-1]]
        split = distances.index(max(distances)) + 1
        return reduce(segment[: split + 1])[:-1] + reduce(segment[split:])

    # Split the loop at its two most distant points so each half is an open line.
    far = max(range(len(points)), key=lambda i: math.dist(points[0], points[i]))
    return reduce(points[: far + 1])[:-1] + reduce(points[far:] + [points[0]])[:-1]


def _wall_share(heights: np.ndarray, region: np.ndarray, pixel_m: float) -> float:
    """
    Share of a surface's edge that ends in a sharp change of height.

    A roof ends at walls: step a little way past its edge and the height has
    jumped. A tree canopy falls away gradually. On real Indian streets roofs
    score above 0.7 and canopies below 0.5.
    """
    reach = max(1, round(0.75 / pixel_m))
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    outside = ~region
    edge = np.zeros_like(region)
    steep = np.zeros_like(region)
    for dr, dc in directions:
        edge |= region & _shift(outside, dr, dc)
        beyond_outside = _shift(outside, dr * reach, dc * reach)
        beyond_height = np.roll(heights, (dr * reach, dc * reach), axis=(0, 1))
        steep |= beyond_outside & (np.abs(beyond_height - heights) >= WALL_DROP_M)
    return float((edge & steep).sum() / max(1, edge.sum()))


def find_surface(dsm: Raster, mask: np.ndarray | None, lng: float, lat: float) -> dict:
    """
    The roof under a tapped point, found from the height data.

    Flat roofs are level surfaces bounded by a drop to the ground or a step to a
    neighbour, so growing outwards from the tap while the height stays level
    traces one roof even in a terrace of joined buildings. A tree canopy is
    also a raised surface, so the result must either be marked as a building
    in Google's mask or end in walls on most sides.
    """
    heights = dsm.data if dsm.data.ndim == 2 else dsm.data[0]
    col, row = dsm.pixel_of(*dsm.to_map(lng, lat))
    seed = (int(row), int(col))
    if not (0 <= seed[0] < heights.shape[0] and 0 <= seed[1] < heights.shape[1]):
        raise SolarDataUnavailable("That point is outside the area Google returned.")

    pixel_m = dsm.metres_per_pixel(lat)
    valid = np.isfinite(heights) & (heights > NO_DATA + 1)
    region = _grow(heights, seed)
    height = float(np.median(heights[region])) - _ground_level(heights, valid, region, pixel_m)

    if height < ROOF_MIN_HEIGHT_M:
        return {"found": False, "kind": "ground", "height_m": round(height, 1)}
    # Google's building mask misses many buildings, so it confirms a roof but cannot rule one out.
    masked = mask is not None and mask.shape == region.shape and float(mask[region].mean()) >= 0.5
    if masked:
        region &= mask
    elif _wall_share(heights, region, pixel_m) < ROOF_WALL_SHARE:
        return {"found": False, "kind": "not_building", "height_m": round(height, 1)}

    region = _tidy(region)
    if region.sum() * pixel_m * pixel_m < 8:
        return {"found": False, "kind": "too_small", "height_m": round(height, 1)}

    loop = _simplify(_outline(region), tolerance=0.4 / pixel_m)
    outline = [dsm.to_lnglat(dsm.left + x * dsm.pixel_x, dsm.top - y * dsm.pixel_y) for x, y in loop]
    cut_off = bool(region[0].any() or region[-1].any() or region[:, 0].any() or region[:, -1].any())
    return {
        "found": True,
        "roof": [list(p) for p in outline],
        "area_m2": round(float(region.sum() * pixel_m * pixel_m), 1),
        "height_m": round(height, 1),
        "floors": max(1, round(height / FLOOR_HEIGHT_M)),
        #: True when the surface runs past the edge of the data, so the outline is incomplete.
        "cut_off": cut_off,
    }


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
    response = client.get(
        f"{API}/dataLayers:get",
        params={
            "location.latitude": f"{lat:.6f}",
            "location.longitude": f"{lng:.6f}",
            "radiusMeters": min(175, math.ceil(radius_m)),
            "view": view,
            # India is covered at BASE quality only; the API's default would reject it.
            "requiredQuality": "BASE",
            "pixelSizeMeters": pixel_m,
            "key": key,
        },
    )
    if response.status_code == 404:
        raise SolarDataUnavailable("Google has no 3D survey of this location yet.")
    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("message", response.text[:200])
        raise SolarDataUnavailable(f"Google's Solar API refused the request: {detail}")
    return response.json()


def _download(client: httpx.Client, key: str, url: str) -> bytes:
    # The URL already carries the file id; passing params would replace it.
    tiff = client.get(f"{url}&key={key}")
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


def roof_at(lng: float, lat: float) -> dict:
    """Find the roof under a tapped map point."""
    key = _key()
    with httpx.Client(timeout=40) as client:
        layers = _layers(client, key, lng, lat, TAP_RADIUS_M, view="IMAGERY_LAYERS")
        with ThreadPoolExecutor(max_workers=2) as pool:
            dsm_file = pool.submit(_download, client, key, layers["dsmUrl"])
            mask_file = pool.submit(_download, client, key, layers["maskUrl"]) if layers.get("maskUrl") else None
            dsm = read_raster(dsm_file.result())
            mask = _read_plain(mask_file.result()) > 0 if mask_file else None
    return find_surface(dsm, mask, lng, lat)


def fetch(roof: list[tuple[float, float]]) -> dict:
    """Measured sun map for an area given as [lng, lat] corners."""
    key = _key()
    lng = sum(p[0] for p in roof) / len(roof)
    lat = sum(p[1] for p in roof) / len(roof)
    reach = max(
        math.hypot((p[0] - lng) * 111_320 * math.cos(math.radians(lat)), (p[1] - lat) * 110_540) for p in roof
    )
    with httpx.Client(timeout=40) as client:
        layers = _layers(client, key, lng, lat, reach + MARGIN_M)
        with ThreadPoolExecutor(max_workers=3) as pool:
            flux_file = pool.submit(_download, client, key, layers["annualFluxUrl"])
            dsm_file = pool.submit(_download, client, key, layers["dsmUrl"]) if layers.get("dsmUrl") else None
            rgb_file = pool.submit(_download, client, key, layers["rgbUrl"]) if layers.get("rgbUrl") else None
            flux = read_raster(flux_file.result())
            dsm = read_raster(dsm_file.result()) if dsm_file else None
            photo = picture(rgb_file.result()) if rgb_file else None

    result = analyse(flux, dsm, roof)
    result["picture"] = photo
    date = layers.get("imageryDate") or {}
    result["imagery_date"] = (
        f"{date['year']:04d}-{date['month']:02d}-{date['day']:02d}" if {"year", "month", "day"} <= date.keys() else None
    )
    result["imagery_quality"] = layers.get("imageryQuality")
    if result["surface"] == "roof":
        result["floors"] = max(1, round(result["roof_height_m"] / FLOOR_HEIGHT_M))
    return result
