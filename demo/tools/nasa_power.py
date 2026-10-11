"""NASA POWER sunlight climatology from NASA's own mirror on AWS Open Data.

The recording environment cannot reach power.larc.nasa.gov, but it can reach NASA's public S3
bucket `nasa-power`, which holds the same CERES SYN1deg climatology the API serves (1-degree
cells, monthly means in W/m²). This extracts the cells for a region and converts them to the
API's unit, kWh/m²/day (W/m² x 24 / 1000), so the browser's request can be answered with NASA's
values in the API's own JSON shape (see `route_nasa` in rec.cjs).

    python nasa_power.py out.json [--lat 5 37 --lon 67 98]
"""

import json
import sys

import xarray as xr

URL = "s3://nasa-power/syn1deg/temporal/power_syn1deg_climatology_temporal_utc.zarr"
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "ANN"]


def main() -> None:
    out = sys.argv[1]
    opt = lambda name, default: [float(v) for v in sys.argv[sys.argv.index(name) + 1 : sys.argv.index(name) + 3]] if name in sys.argv else default
    (lat0, lat1), (lon0, lon1) = opt("--lat", [5.0, 37.0]), opt("--lon", [67.0, 98.0])
    ds = xr.open_zarr(URL, storage_options={"anon": True})
    sw = ds["ALLSKY_SFC_SW_DWN"].sel(lat=slice(lat0, lat1), lon=slice(lon0, lon1)).load()
    cells = {}
    for lat in sw.lat.values:
        for lon in sw.lon.values:
            values = sw.sel(lat=lat, lon=lon).values  # 13 entries: 12 months, then the year
            cells[f"{lat:.1f},{lon:.1f}"] = {m: round(float(v) * 24 / 1000, 2) for m, v in zip(MONTHS, values)}
    json.dump({"source": URL, "attrs": {k: str(v) for k, v in ds.attrs.items() if k in ("title", "comment", "date_created")}, "cells": cells}, open(out, "w"))
    print(f"{out}: {len(cells)} cells")


if __name__ == "__main__":
    main()
