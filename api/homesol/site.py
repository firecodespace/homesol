"""
A model of one property, built from Google's 3D survey.

Given a tapped point or a hand-drawn outline, this finds the surface panels
would sit on (a flat roof, a sloped roof, open ground or a hillside), measures
it, finds everything standing on it and around it that could cast a shadow,
and packs the height and sunlight rasters the app simulates shade and lays out
panels with.

Everything here is geometry on the height data. No model is asked to look at
a picture, so the same input always gives the same answer.
"""

import base64
import math
import zlib
from collections import deque
from dataclasses import dataclass

import numpy as np

from .google_solar import NO_DATA, SolarDataUnavailable, Tile, _inside, fetch_tile, png_data_url

#: Largest height change between neighbouring points of one continuous surface, per metre travelled.
SURFACE_SLOPE_LIMIT = 1.2
#: First pass of finding a surface from a tap keeps points this close to the tapped height.
LEVEL_BAND_M = 0.4
#: Later passes keep points this close to the plane fitted through the surface, so slopes are followed.
PLANE_BAND_M = 0.5
#: Points of a hand-drawn outline this close to its fitted plane belong to the surface.
OUTLINE_BAND_M = 0.75
#: A surface lower than this above nearby ground is ground, not a roof.
ROOF_MIN_HEIGHT_M = 1.5
#: A surface tilted more than this is called sloped.
SLOPED_TILT_DEG = 8.0
#: Height change just past a surface's edge that counts as a wall.
WALL_DROP_M = 1.2
#: A raised surface Google has not marked as a building is still a roof if this much of its edge is wall.
ROOF_WALL_SHARE = 0.7
#: Ground is looked for within this distance of the surface, so a distant dip does not inflate heights.
GROUND_SEARCH_M = 12.0
#: Smallest area worth outlining as a roof.
MIN_SURFACE_M2 = 8.0
#: Something on the surface counts as a structure when it stands this far above it.
STRUCTURE_MIN_M = 0.5
#: Something beside the surface counts as an obstruction when it rises this far above it.
NEIGHBOUR_MIN_M = 1.0
#: Notches in the surface's edge up to this wide are treated as part of it, so a stair room at the
#: edge of a roof counts as standing on the roof.
EDGE_NOTCH_M = 2.5
#: Obstructions that never rise this many degrees above the surface's horizon cannot shade it usefully.
MIN_ELEVATION_DEG = 6.0
#: A neighbour no larger and no taller than this, with this much of its edge against the surface,
#: is a structure standing on the surface's own building.
EDGE_STRUCTURE_MAX_M2 = 60.0
EDGE_STRUCTURE_MAX_HEIGHT_M = 5.0
EDGE_STRUCTURE_TOUCH = 0.4
#: An unmarked neighbour whose top strays less than this from a plane is a building, not a tree.
FLAT_TOP_ROUGHNESS_M = 0.5
MAX_OBSTRUCTIONS = 40
FLOOR_HEIGHT_M = 3.0
TAP_RADIUS_M = 60.0
#: How far beyond the surface to model, so neighbours that shade it are included.
SURROUND_M = 45.0
MAX_RADIUS_M = 110.0
#: Above this radius the tile is fetched at half resolution to keep it a manageable size.
FINE_RADIUS_M = 65.0

COMPASS = ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"]


def compass(bearing: float) -> str:
    return COMPASS[round((bearing % 360) / 45) % 8]


# --- small raster tools -------------------------------------------------------------------------


def _shift(mask: np.ndarray, dr: int, dc: int) -> np.ndarray:
    out = np.zeros_like(mask)
    rows, cols = mask.shape
    out[max(dr, 0) : rows + min(dr, 0), max(dc, 0) : cols + min(dc, 0)] = mask[
        max(-dr, 0) : rows + min(-dr, 0), max(-dc, 0) : cols + min(-dc, 0)
    ]
    return out


_NEIGHBOURS8 = [(dr, dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)]
_NEIGHBOURS4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _dilate(mask: np.ndarray, times: int = 1) -> np.ndarray:
    for _ in range(times):
        mask = np.any([_shift(mask, dr, dc) for dr, dc in _NEIGHBOURS8], axis=0)
    return mask


def _erode(mask: np.ndarray, times: int = 1) -> np.ndarray:
    for _ in range(times):
        mask = np.all([_shift(mask, dr, dc) for dr, dc in _NEIGHBOURS8], axis=0)
    return mask


def _tidy(region: np.ndarray) -> np.ndarray:
    """Close pinholes and drop single-pixel threads so the outline is clean."""
    return _dilate(_erode(_erode(_dilate(region))))


def _crop(mask: np.ndarray, pad: int) -> tuple[slice, slice]:
    rows, cols = np.nonzero(mask)
    return (
        slice(max(0, rows.min() - pad), min(mask.shape[0], rows.max() + pad + 1)),
        slice(max(0, cols.min() - pad), min(mask.shape[1], cols.max() + pad + 1)),
    )


def _components(mask: np.ndarray, heights: np.ndarray | None = None, max_step: float | None = None) -> np.ndarray:
    """
    Label the connected pieces of a mask, 1..n, with 0 outside it.

    With `heights`, two neighbours are only connected when their heights differ
    by at most `max_step`, which splits adjoining buildings of different heights.
    """
    labels = np.where(mask, np.arange(1, mask.size + 1, dtype=np.int64).reshape(mask.shape), 0)
    links = []
    for dr, dc in _NEIGHBOURS4:
        linked = mask & _shift(mask, dr, dc)
        if heights is not None:
            linked &= np.abs(heights - np.roll(heights, (dr, dc), axis=(0, 1))) <= max_step
        links.append((dr, dc, linked))
    big = np.iinfo(np.int64).max
    while True:
        before = labels
        for dr, dc, linked in links:
            neighbour = np.where(linked, _shift_values(labels, dr, dc), big)
            labels = np.where(mask, np.minimum(labels, neighbour), 0)
        if np.array_equal(labels, before):
            break
    _, compact = np.unique(labels, return_inverse=True)
    return compact.reshape(mask.shape) if labels.min() == 0 else compact.reshape(mask.shape) + 1


def _shift_values(values: np.ndarray, dr: int, dc: int) -> np.ndarray:
    out = np.zeros_like(values)
    rows, cols = values.shape
    out[max(dr, 0) : rows + min(dr, 0), max(dc, 0) : cols + min(dc, 0)] = values[
        max(-dr, 0) : rows + min(-dr, 0), max(-dc, 0) : cols + min(-dc, 0)
    ]
    return out


def _fill_holes(region: np.ndarray) -> np.ndarray:
    """The region plus everything it fully encloses."""
    outside = np.zeros_like(region)
    outside[0, :] = outside[-1, :] = outside[:, 0] = outside[:, -1] = True
    outside &= ~region
    while True:
        grown = outside | (np.any([_shift(outside, dr, dc) for dr, dc in _NEIGHBOURS4], axis=0) & ~region)
        if np.array_equal(grown, outside):
            return ~outside
        outside = grown


def _outline(region: np.ndarray) -> list[tuple[float, float]]:
    """Outer boundary of a pixel region as (column, row) corner points, largest loop only."""
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
        keep = [False] * len(segment)
        keep[0] = keep[-1] = True
        stack = [(0, len(segment) - 1)]
        while stack:
            first, last = stack.pop()
            (x1, y1), (x2, y2) = segment[first], segment[last]
            length = math.hypot(x2 - x1, y2 - y1) or 1e-9
            worst, index = 0.0, -1
            for i in range(first + 1, last):
                x, y = segment[i]
                distance = abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / length
                if distance > worst:
                    worst, index = distance, i
            if worst > tolerance:
                keep[index] = True
                stack += [(first, index), (index, last)]
        return [p for p, k in zip(segment, keep) if k]

    # Split the loop at its two most distant points so each half is an open line.
    far = max(range(len(points)), key=lambda i: math.dist(points[0], points[i]))
    return reduce(points[: far + 1])[:-1] + reduce(points[far:] + [points[0]])[:-1]


# --- finding the surface ------------------------------------------------------------------------


def fit_plane(heights: np.ndarray, region: np.ndarray) -> np.ndarray:
    """Least-squares plane through a region: height = a * column + b * row + c."""
    rows, cols = np.nonzero(region)
    design = np.c_[cols, rows, np.ones(len(rows))]
    plane, *_ = np.linalg.lstsq(design, heights[region].astype(float), rcond=None)
    return plane


def plane_heights(plane: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    rows, cols = np.mgrid[0 : shape[0], 0 : shape[1]]
    return plane[0] * cols + plane[1] * rows + plane[2]


def _grow(heights: np.ndarray, seed: tuple[int, int], allowed: np.ndarray, step: float) -> np.ndarray:
    """Spread outwards from a pixel across allowed neighbours whose height changes gently."""
    rows, cols = heights.shape
    region = np.zeros(heights.shape, dtype=bool)
    region[seed] = True
    queue = deque([seed])
    while queue:
        r, c = queue.popleft()
        here = heights[r, c]
        for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
            if 0 <= rr < rows and 0 <= cc < cols and not region[rr, cc] and allowed[rr, cc]:
                if abs(heights[rr, cc] - here) <= step:
                    region[rr, cc] = True
                    queue.append((rr, cc))
    return region


def grow_surface(heights: np.ndarray, seed: tuple[int, int], pixel_m: float) -> tuple[np.ndarray, np.ndarray]:
    """
    The continuous surface under a tapped pixel, and the plane through it.

    The first pass keeps to the tapped height, which finds a flat roof and stops
    at a neighbour's step or a tree. Each later pass fits a plane through what
    was found and keeps to that plane instead, so on a sloped roof or hillside
    the surface spreads up and down the slope while still stopping at walls.
    """
    step = SURFACE_SLOPE_LIMIT * pixel_m
    valid = np.isfinite(heights) & (heights > NO_DATA + 1)
    region = _grow(heights, seed, valid & (np.abs(heights - heights[seed]) <= LEVEL_BAND_M), step)
    plane = np.array([0.0, 0.0, float(heights[seed])])
    for _ in range(5):
        if region.sum() < 12:
            break
        plane = fit_plane(heights, region)
        allowed = valid & (np.abs(heights - plane_heights(plane, heights.shape)) <= PLANE_BAND_M)
        if not allowed[seed]:
            break
        grown = _grow(heights, seed, allowed, step)
        settled = grown.sum() <= region.sum() * 1.03
        region = grown
        if settled:
            break
    return region, plane


def surface_in_outline(heights: np.ndarray, inside: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    The surface a hand-drawn outline is about, and the plane through it.

    An outline drawn by hand is loose: it takes in the stair room on the roof,
    a strip of ground beside the building, a neighbour's corner. The surface is
    the outline's dominant plane, and everything well above or below is left out.
    """
    valid = inside & np.isfinite(heights) & (heights > NO_DATA + 1)
    if valid.sum() < 12:
        raise SolarDataUnavailable("Google has no height data inside this outline.")
    # Start from the fullest half-metre band of heights, then follow whatever plane it lies on.
    levels, counts = np.unique(np.round(heights[valid] * 2) / 2, return_counts=True)
    level = float(levels[counts.argmax()])
    chosen = valid & (np.abs(heights - level) <= 1.0)
    if chosen.sum() < 0.3 * valid.sum():
        chosen = valid
    plane = fit_plane(heights, chosen)
    for _ in range(6):
        residual = np.abs(heights - plane_heights(plane, heights.shape))
        keep = valid & (residual <= OUTLINE_BAND_M)
        if keep.sum() < 12 or np.array_equal(keep, chosen):
            break
        chosen = keep
        plane = fit_plane(heights, chosen)
    return chosen, plane


def height_above_ground(heights: np.ndarray, surface: np.ndarray, plane: np.ndarray, pixel_m: float) -> float:
    """
    How far a surface stands above the ground beside it; zero when it is the ground.

    Ground continues smoothly into its surroundings, even on a hillside, so the
    land around it lies on the same plane. A roof has ground well below its
    plane somewhere nearby. The surface counts as raised when at least a
    twentieth of what surrounds it lies clearly below its plane, which still
    works in a dense street where only one side is open.
    """
    valid = np.isfinite(heights) & (heights > NO_DATA + 1)
    window = _crop(surface, math.ceil(GROUND_SEARCH_M / pixel_m))
    around = valid[window] & ~surface[window]
    if around.sum() < 20:
        return 0.0
    nearby = heights[window][around]
    drop = -float(np.percentile(nearby - plane_heights(plane, heights.shape)[window][around], 5))
    if drop < ROOF_MIN_HEIGHT_M:
        return max(0.0, drop)
    # For a raised surface, report the height of its middle above the low ground nearby.
    return max(drop if abs(plane[0]) + abs(plane[1]) < 1e-9 else 0.0, float(np.median(heights[surface]) - np.percentile(nearby, 5)))


def wall_share(heights: np.ndarray, region: np.ndarray, pixel_m: float) -> float:
    """
    Share of a surface's edge that ends in a sharp change of height.

    A roof ends at walls: step a little way past its edge and the height has
    jumped. A tree canopy falls away gradually. On real streets roofs score
    above 0.7 and canopies below 0.5.
    """
    reach = max(1, round(0.75 / pixel_m))
    outside = ~region
    edge = np.zeros_like(region)
    steep = np.zeros_like(region)
    for dr, dc in _NEIGHBOURS4:
        edge |= region & _shift(outside, dr, dc)
        beyond_outside = _shift(outside, dr * reach, dc * reach)
        beyond_height = np.roll(heights, (dr * reach, dc * reach), axis=(0, 1))
        steep |= beyond_outside & (np.abs(beyond_height - heights) >= WALL_DROP_M)
    return float((edge & steep).sum() / max(1, edge.sum()))


@dataclass
class Surface:
    region: np.ndarray
    plane: np.ndarray
    #: "roof", "sloped_roof", "ground" or "sloped_ground".
    kind: str
    #: Height of the surface above the ground beside it.
    height_m: float
    tilt_deg: float
    #: Compass bearing the surface faces (the downhill direction); meaningful when sloped.
    faces_deg: float
    area_m2: float


def describe(tile: Tile, region: np.ndarray, plane: np.ndarray) -> Surface:
    px = tile.pixel_m
    height = height_above_ground(tile.heights, region, plane, px)
    # Rows run south, so a positive row coefficient is a surface falling towards the north.
    rise_east, rise_north = plane[0] / px, -plane[1] / px
    tilt = math.degrees(math.atan(math.hypot(rise_east, rise_north)))
    faces = math.degrees(math.atan2(-rise_east, -rise_north)) % 360
    raised = height >= ROOF_MIN_HEIGHT_M
    sloped = tilt >= SLOPED_TILT_DEG
    kind = ("sloped_roof" if sloped else "roof") if raised else ("sloped_ground" if sloped else "ground")
    # A tilted surface is larger than its footprint on the map.
    area = float(region.sum()) * px * px / math.cos(math.radians(tilt))
    return Surface(region, plane, kind, height, tilt, faces, area)


# --- what stands on and around the surface ------------------------------------------------------


def _nearest_gap(a: np.ndarray, b: np.ndarray, pixel_m: float) -> float:
    """Shortest distance in metres between two pixel masks, from a sample of their edges."""

    def edge_points(mask: np.ndarray) -> np.ndarray:
        edge = mask & ~_erode(mask)
        points = np.argwhere(edge if edge.any() else mask)
        return points[:: max(1, len(points) // 300)]

    pa, pb = edge_points(a), edge_points(b)
    distances = np.hypot(pa[:, None, 0] - pb[None, :, 0], pa[:, None, 1] - pb[None, :, 1])
    return float(distances.min()) * pixel_m


def _name_structure(area: float, top: float) -> tuple[str, str]:
    if top < 1.2:
        return "wall", "Low wall or raised edge"
    if area < 6:
        return "tank", "Water tank or small structure"
    if area > 40:
        return "upper_level", "Higher part of the building"
    if top >= 1.8:
        return "room", "Rooftop room (stairs or lift)"
    return "structure", "Rooftop structure"


def _touch_share(piece: np.ndarray, region: np.ndarray) -> float:
    """Share of a piece's edge that lies against the surface."""
    edge = piece & ~np.all([_shift(piece, dr, dc) for dr, dc in _NEIGHBOURS4], axis=0)
    region = region[: piece.shape[0], : piece.shape[1]]
    return float((edge & _dilate(region, 2)).sum() / max(1, edge.sum()))


def _roughness(heights: np.ndarray, piece: np.ndarray) -> float:
    """How far a piece's heights stray from a flat plane, in metres. Roofs are near zero; tree canopies are not."""
    if piece.sum() < 6:
        return 0.0
    return float(np.sqrt(np.mean((heights[piece] - plane_heights(fit_plane(heights, piece), heights.shape)[piece]) ** 2)))


def _box_blur(values: np.ndarray) -> np.ndarray:
    padded = np.pad(values, 1, mode="edge")
    return sum(padded[1 + dr : 1 + dr + values.shape[0], 1 + dc : 1 + dc + values.shape[1]] for dr, dc in _NEIGHBOURS8) / 9


def find_obstructions(tile: Tile, surface: Surface) -> tuple[np.ndarray, list[dict]]:
    """
    Everything that could cast a shadow on the surface, measured from the height data.

    Returns a label raster (0 nothing, 1 the surface, 2.. each obstruction) and
    one record per obstruction with its outline, height and position.
    """
    heights, px = tile.heights, tile.pixel_m
    region = surface.region
    # "Above the surface" is measured from its plane, held within the surface's own height range so
    # a tilted plane is not extrapolated far beyond the surface.
    low, high = np.percentile(heights[region], [2, 98])
    reference = np.clip(plane_heights(surface.plane, heights.shape), low, high)
    above = heights - reference
    valid = np.isfinite(heights) & (heights > NO_DATA + 1)

    notch = max(1, round(EDGE_NOTCH_M / px))
    window = _crop(region, notch + 2)
    footprint = np.zeros_like(region)
    footprint[window] = _fill_holes(_erode(_dilate(region[window], notch), notch) | region[window])

    labels = np.zeros(heights.shape, dtype=np.uint8)
    labels[region] = 1
    rows, cols = np.nonzero(region)
    centre = (rows.mean(), cols.mean())
    found: list[dict] = []

    def record(piece: np.ndarray, scale: int, on_surface: bool) -> dict | None:
        """Measure one obstruction given as a mask on a grid `scale` times coarser than the tile."""
        pixel = px * scale
        area = float(piece.sum()) * pixel * pixel
        piece_above = above[::scale, ::scale][: piece.shape[0], : piece.shape[1]][piece]
        top = float(np.percentile(piece_above, 90))
        r, c = np.nonzero(piece)
        # Bearing and distance from the middle of the surface to the middle of the obstruction.
        north = (centre[0] - (r.mean() + 0.5) * scale) * px
        east = ((c.mean() + 0.5) * scale - centre[1]) * px
        gap = 0.0 if on_surface else _nearest_gap(piece, region[::scale, ::scale][: piece.shape[0], : piece.shape[1]], pixel)
        loop = _simplify(_outline(piece), tolerance=0.5 / pixel)
        if len(loop) < 3:
            return None
        return {
            "on_surface": on_surface,
            "outline": [tile.corner_lnglat(x * scale, y * scale) for x, y in loop],
            "height_above_m": round(top, 1),
            "area_m2": round(area, 1),
            "distance_m": round(gap, 1),
            "bearing_deg": round(math.degrees(math.atan2(east, north)) % 360),
            "direction": compass(math.degrees(math.atan2(east, north))),
            #: How far above the surface's horizon it rises, seen from the nearest edge.
            "elevation_deg": round(math.degrees(math.atan2(top, max(gap, pixel))), 1),
        }

    # Structures standing on the surface: inside its footprint, above its plane.
    standing = footprint & ~region & valid & (above > STRUCTURE_MIN_M)
    if standing.any():
        pieces = _components(standing)
        for k in range(1, int(pieces.max()) + 1):
            piece = pieces == k
            item = record(piece, 1, True)
            if item is None or item["area_m2"] < 0.75:
                continue
            item["kind"], item["name"] = _name_structure(item["area_m2"], item["height_above_m"])
            found.append({**item, "_mask": piece, "_scale": 1})

    # Neighbours: taller things outside the footprint, split where their height steps.
    scale = 2 if px < 0.4 else 1
    coarse = heights[::scale, ::scale]
    rising = (above[::scale, ::scale] > NEIGHBOUR_MIN_M) & valid[::scale, ::scale] & ~footprint[::scale, ::scale]
    neighbours: list[dict] = []
    if rising.any():
        # Splitting uses lightly smoothed heights, so a spiky tree canopy stays one piece while the
        # metres-high step between two buildings still divides them.
        pieces = _components(rising, _box_blur(coarse), max_step=0.75)
        sizes = np.bincount(pieces.ravel())
        coarse_mask = tile.mask[::scale, ::scale] if tile.mask is not None else None
        # The largest pieces are measured first; small scraps beyond the first eighty are not worth it.
        for k in np.argsort(sizes)[::-1][:81]:
            if k == 0 or sizes[k] * (px * scale) ** 2 < 6:
                continue
            piece = pieces == k
            item = record(piece, scale, False)
            if item is None or item["elevation_deg"] < MIN_ELEVATION_DEG:
                continue
            # Google's mask confirms a building. Without it, a flat top means a building it missed
            # and a bumpy one means a tree.
            marked = coarse_mask is not None and float(coarse_mask[piece].mean()) >= 0.5
            if marked or _roughness(coarse, piece) <= FLAT_TOP_ROUGHNESS_M:
                item["kind"], item["name"] = "building", "Neighbouring building"
            elif item["area_m2"] > 150:
                # Too big and uneven to be one tree: several buildings, or buildings and trees, that
                # the height data runs together.
                item["kind"], item["name"] = "surroundings", "Taller buildings or trees"
            else:
                item["kind"], item["name"] = "tree", "Tree or vegetation"
            neighbours.append({**item, "_mask": piece, "_scale": scale})
    # A stair room or penthouse at the roof's edge is not enclosed by the surface, so it was found
    # as a neighbour. It belongs to the roof when it is small, low and wrapped by the surface.
    for item in neighbours:
        small = item["area_m2"] <= EDGE_STRUCTURE_MAX_M2 and item["height_above_m"] <= EDGE_STRUCTURE_MAX_HEIGHT_M
        if small and _touch_share(item["_mask"], region[::scale, ::scale]) >= EDGE_STRUCTURE_TOUCH:
            item["on_surface"], item["distance_m"] = True, 0.0
            item["kind"], item["name"] = _name_structure(item["area_m2"], item["height_above_m"])
    found += [n for n in neighbours if n["on_surface"]]
    neighbours = [n for n in neighbours if not n["on_surface"]]
    neighbours.sort(key=lambda o: -o["elevation_deg"])
    found += neighbours[: MAX_OBSTRUCTIONS - len(found)]

    for index, item in enumerate(found):
        item["id"] = index + 2
        piece, scale = item.pop("_mask"), item.pop("_scale")
        if scale > 1:
            piece = np.repeat(np.repeat(piece, scale, axis=0), scale, axis=1)[: labels.shape[0], : labels.shape[1]]
            full = np.zeros_like(region)
            full[: piece.shape[0], : piece.shape[1]] = piece
            piece = full
        labels[piece & (labels == 0)] = item["id"]
    return labels, found


# --- packing the model for the app --------------------------------------------------------------


def _pack(values: np.ndarray) -> str:
    return base64.b64encode(zlib.compress(np.ascontiguousarray(values).tobytes(), 6)).decode()


def build(tile: Tile, surface: Surface, outline: list[list[float]], found_by: str) -> dict:
    """The site model sent to the app: rasters on one grid, the surface, and its obstructions."""
    if tile.flux is None:
        raise SolarDataUnavailable("Google has no sunlight data for this location.")
    heights = tile.heights
    rows, cols = heights.shape
    valid = np.isfinite(heights) & (heights > NO_DATA + 1)
    lit = np.isfinite(tile.flux) & (tile.flux > 0)

    # An open, unshaded surface nearby sets the scale; the surface's own best spot guards against
    # a tile where everything else is steeper or brighter than this surface can be.
    on_surface = surface.region & lit
    if not on_surface.any():
        raise SolarDataUnavailable("Google has no sunlight data on this surface.")
    open_sky = float(max(np.percentile(tile.flux[lit], 95), np.percentile(tile.flux[on_surface], 99)))
    access = np.where(lit, np.clip(tile.flux / open_sky, 0, 1) * 250, 255).astype(np.uint8)

    labels, obstructions = find_obstructions(tile, surface)
    floor = float(heights[valid].min())
    centimetres = np.where(valid, np.clip((heights - floor) * 100, 0, 65534), 65535).astype("<u2")

    edge = surface.region
    return {
        "grid": {
            "rows": rows,
            "cols": cols,
            "pixel_m": round(tile.pixel_m, 4),
            #: Top-left, top-right, bottom-right, bottom-left of the grid as [lng, lat].
            "corners": [tile.corner_lnglat(0, 0), tile.corner_lnglat(cols, 0), tile.corner_lnglat(cols, rows), tile.corner_lnglat(0, rows)],
        },
        #: Rasters, row by row from the top-left, zlib-compressed then base64.
        "heights_cm": _pack(centimetres),  # uint16 little-endian, centimetres above `height_floor_m`; 65535 = no data
        "height_floor_m": round(floor, 2),
        "access": _pack(access),  # uint8, share of open-sky sunlight x 250; 255 = no data
        "labels": _pack(labels),  # uint8, 0 nothing, 1 the surface, 2.. obstruction ids
        "photo": png_data_url(tile.rgb) if tile.rgb is not None else None,
        "outline": outline,
        "surface": {
            "kind": surface.kind,
            "area_m2": round(surface.area_m2, 1),
            "height_m": round(surface.height_m, 1),
            "floors": max(1, round(surface.height_m / FLOOR_HEIGHT_M)) if "roof" in surface.kind else 0,
            "tilt_deg": round(surface.tilt_deg, 1),
            "faces_deg": round(surface.faces_deg),
            "faces": compass(surface.faces_deg),
            "found_by": found_by,
            #: True when the surface runs past the edge of the data, so it is incomplete.
            "cut_off": bool(edge[0].any() or edge[-1].any() or edge[:, 0].any() or edge[:, -1].any()),
        },
        "obstructions": obstructions,
        "sunlight": {
            "surface": round(float(tile.flux[on_surface].mean())),
            "open_sky": round(open_sky),
            "share": round(float(np.clip(tile.flux[on_surface] / open_sky, 0, 1).mean()), 3),
        },
        "imagery_date": tile.imagery_date,
        "imagery_quality": tile.imagery_quality,
    }


def _region_outline(tile: Tile, region: np.ndarray) -> list[list[float]]:
    loop = _simplify(_outline(region), tolerance=0.4 / tile.pixel_m)
    return [tile.corner_lnglat(x, y) for x, y in loop]


def surface_at(tile: Tile, lng: float, lat: float) -> Surface | dict:
    """The surface under a tapped point, or the reason there is no roof there."""
    col, row = tile.pixel_of(lng, lat)
    seed = (int(row), int(col))
    if not (0 <= seed[0] < tile.heights.shape[0] and 0 <= seed[1] < tile.heights.shape[1]):
        raise SolarDataUnavailable("That point is outside the area Google returned.")
    region, plane = grow_surface(tile.heights, seed, tile.pixel_m)
    surface = describe(tile, region, plane)
    if "ground" in surface.kind:
        return {"found": False, "kind": "ground", "height_m": round(surface.height_m, 1)}
    # Google's building mask misses many buildings, so it confirms a roof but cannot rule one out.
    marked = tile.mask is not None and float(tile.mask[region].mean()) >= 0.5
    if marked:
        region = region & tile.mask
    elif wall_share(tile.heights, region, tile.pixel_m) < ROOF_WALL_SHARE:
        return {"found": False, "kind": "not_building", "height_m": round(surface.height_m, 1)}
    region = _tidy(region)
    if region.sum() * tile.pixel_m**2 < MIN_SURFACE_M2:
        return {"found": False, "kind": "too_small", "height_m": round(surface.height_m, 1)}
    return describe(tile, region, fit_plane(tile.heights, region))


def from_tap(lng: float, lat: float) -> dict:
    """Find the roof under a tapped point and model the property around it."""
    tile = fetch_tile(lng, lat, TAP_RADIUS_M)
    surface = surface_at(tile, lng, lat)
    if isinstance(surface, dict):
        return surface
    edge = surface.region
    if edge[0].any() or edge[-1].any() or edge[:, 0].any() or edge[:, -1].any():
        # The roof runs off the data. Fetch again, centred on the roof and wide enough to hold it.
        rows, cols = np.nonzero(edge)
        centre = tile.corner_lnglat(cols.mean(), rows.mean())
        reach = max(np.ptp(rows), np.ptp(cols)) * tile.pixel_m * 0.75
        radius = min(MAX_RADIUS_M, reach + SURROUND_M)
        tile = fetch_tile(centre[0], centre[1], radius, 0.25 if radius <= FINE_RADIUS_M else 0.5)
        surface = surface_at(tile, lng, lat)
        if isinstance(surface, dict):
            return surface
    return {"found": True, **build(tile, surface, _region_outline(tile, surface.region), "tap")}


def from_outline(outline: list[tuple[float, float]]) -> dict:
    """Model the property inside a hand-drawn outline."""
    lng = sum(p[0] for p in outline) / len(outline)
    lat = sum(p[1] for p in outline) / len(outline)
    reach = max(
        math.hypot((p[0] - lng) * 111_320 * math.cos(math.radians(lat)), (p[1] - lat) * 110_540) for p in outline
    )
    radius = min(MAX_RADIUS_M, reach + SURROUND_M)
    tile = fetch_tile(lng, lat, radius, 0.25 if radius <= FINE_RADIUS_M else 0.5)

    rows, cols = tile.heights.shape
    col_idx, row_idx = np.meshgrid(np.arange(cols) + 0.5, np.arange(rows) + 0.5)
    corners = [tile.pixel_of(x, y) for x, y in outline]
    inside = _inside(col_idx, row_idx, corners)
    if not inside.any():
        raise SolarDataUnavailable("This outline is outside the area Google returned.")
    region, plane = surface_in_outline(tile.heights, inside)
    surface = describe(tile, region, plane)
    return {"found": True, **build(tile, surface, [list(p) for p in outline], "outline")}
