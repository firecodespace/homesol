"""Latitude/longitude to and from UTM metres on the WGS84 ellipsoid (Krüger series)."""

import math

A = 6378137.0
F = 1 / 298.257223563
K0 = 0.9996
N = F / (2 - F)
A_BAR = A / (1 + N) * (1 + N**2 / 4 + N**4 / 64)
ALPHA = (N / 2 - 2 * N**2 / 3 + 5 * N**3 / 16, 13 * N**2 / 48 - 3 * N**3 / 5, 61 * N**3 / 240)
BETA = (N / 2 - 2 * N**2 / 3 + 37 * N**3 / 96, N**2 / 48 + N**3 / 15, 17 * N**3 / 480)
DELTA = (2 * N - 2 * N**2 / 3 - 2 * N**3, 7 * N**2 / 3 - 8 * N**3 / 5, 56 * N**3 / 15)
E = math.sqrt(F * (2 - F))


def zone_for(lng: float) -> int:
    return int((lng + 180) // 6) + 1


def from_epsg(epsg: int) -> tuple[int, bool]:
    """UTM zone and hemisphere (True for north) of a WGS84 UTM EPSG code."""
    if 32601 <= epsg <= 32660:
        return epsg - 32600, True
    if 32701 <= epsg <= 32760:
        return epsg - 32700, False
    raise ValueError(f"EPSG:{epsg} is not a WGS84 UTM zone.")


def forward(lng: float, lat: float, zone: int, north: bool = True) -> tuple[float, float]:
    """Easting and northing in metres."""
    phi, lam = math.radians(lat), math.radians(lng - (zone * 6 - 183))
    t = math.sinh(math.atanh(math.sin(phi)) - E * math.atanh(E * math.sin(phi)))
    xi = math.atan2(t, math.cos(lam))
    eta = math.atanh(math.sin(lam) / math.sqrt(1 + t * t))
    x = eta + sum(a * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, a in enumerate(ALPHA, 1))
    y = xi + sum(a * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, a in enumerate(ALPHA, 1))
    return 500_000 + K0 * A_BAR * x, (0 if north else 10_000_000) + K0 * A_BAR * y


def inverse(easting: float, northing: float, zone: int, north: bool = True) -> tuple[float, float]:
    """Longitude and latitude in degrees."""
    xi = (northing - (0 if north else 10_000_000)) / (K0 * A_BAR)
    eta = (easting - 500_000) / (K0 * A_BAR)
    xi0 = xi - sum(b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(BETA, 1))
    eta0 = eta - sum(b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(BETA, 1))
    chi = math.asin(math.sin(xi0) / math.cosh(eta0))
    lat = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(DELTA, 1))
    lng = (zone * 6 - 183) + math.degrees(math.atan2(math.sinh(eta0), math.cos(xi0)))
    return lng, math.degrees(lat)
