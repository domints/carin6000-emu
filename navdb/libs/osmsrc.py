"""OpenStreetMap input for the encoder: Geofabrik extracts downloaded and converted on demand, and
queries over several of them at once (neighbouring extracts overlap at their borders, so rows are
deduplicated by OSM id).

A region is downloaded to temp/osm/<name>-latest.osm.pbf and converted with ogr2ogr to
temp/osm/<name>.gpkg (layers lines, points, multipolygons). The files are a cache: an extract
older than ASK_DAYS is downloaded again if the user says so (asked on a terminal), one older
than MAX_DAYS always. The encoded area comes from the countries' boundaries in the extracts
(libs/osmplaces.Borders): an extract's own extent is larger (whole ways crossing the border,
ferry lines to Scandinavia).
"""
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

GEOFABRIK = "https://download.geofabrik.de/"
ASK_DAYS, MAX_DAYS = 7, 30
REGIONS = {               # extract name (cache file name) -> Geofabrik path
    "polska": "europe/poland",
    "slovenia": "europe/slovenia",
    "croatia": "europe/croatia",
    "bosnia-herzegovina": "europe/bosnia-herzegovina",
    "montenegro": "europe/montenegro",
    "serbia": "europe/serbia",
    "kosovo": "europe/kosovo",
    "macedonia": "europe/macedonia",
    "albania": "europe/albania",
}


def _download(url, path, log):
    tmp = path.with_suffix(".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, 0.0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if sys.stderr.isatty() and time.monotonic() - last > 0.5:
                last = time.monotonic()
                pct = f"{100 * done // total:3d}%" if total else f"{done >> 20} MB"
                print(f"\r  {path.name}: {pct}\033[K", end="", file=sys.stderr, flush=True)
    if sys.stderr.isatty():
        print("\r\033[K", end="", file=sys.stderr)
    tmp.rename(path)
    log(f"downloaded {path.name} ({done / 1e6:.0f} MB)")


def _stale(pbf, log):
    """Should the cached extract be downloaded again?"""
    if not pbf.is_file():
        return True
    days = (time.time() - pbf.stat().st_mtime) / 86400
    if days > MAX_DAYS:
        log(f"{pbf.name} is {days:.0f} days old (> {MAX_DAYS}): downloading a fresh one")
        return True
    if days > ASK_DAYS:
        if not sys.stdin.isatty():
            log(f"{pbf.name} is {days:.0f} days old; using it (no terminal to ask)")
            return False
        answer = input(f"{pbf.name} is {days:.0f} days old. Download a fresh one? [y/N] ")
        return answer.strip().lower() in ("y", "yes", "t", "tak")
    return False


def fetch(name, folder, log=print):
    """GeoPackage of a region (downloaded and converted when needed)."""
    if name not in REGIONS:
        raise SystemExit(f"unknown region {name}; known: {', '.join(REGIONS)}")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pbf = folder / f"{name}-latest.osm.pbf"
    gpkg = folder / f"{name}.gpkg"
    fresh = _stale(pbf, log)
    if fresh:
        log(f"downloading {GEOFABRIK}{REGIONS[name]}-latest.osm.pbf")
        _download(f"{GEOFABRIK}{REGIONS[name]}-latest.osm.pbf", pbf, log)
    if not gpkg.is_file() or gpkg.stat().st_mtime < pbf.stat().st_mtime:
        if not shutil.which("ogr2ogr"):
            raise SystemExit("ogr2ogr (GDAL) is needed to read OSM files; install gdal")
        log(f"converting {pbf.name} -> {gpkg.name} (ogr2ogr)")
        tmp = gpkg.with_suffix(".tmp.gpkg")
        tmp.unlink(missing_ok=True)
        subprocess.run(["ogr2ogr", "-f", "GPKG", str(tmp), str(pbf), "lines", "points", "multipolygons",
                        "-gt", "65536"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tmp.rename(gpkg)
    return gpkg


def rows(gpkgs, sql, params=()):
    """The rows of a query over every GeoPackage; a row whose first column (the OSM id) was seen in
    an earlier file is skipped."""
    if isinstance(gpkgs, (str, Path)):
        gpkgs = [gpkgs]
    seen = set()
    for g in gpkgs:
        db = sqlite3.connect(g)
        for row in db.execute(sql, params):
            if len(gpkgs) > 1:
                if row[0] in seen:
                    continue
                seen.add(row[0])
            yield row


STRIPES = 32           # fixed, so the output does not depend on the number of workers


def prows(gpkgs, sql, params, func):
    """func(rows) for vertical stripes of the query (by the feature's minx, so no feature is in
    two stripes) in worker processes; the lists func returns, joined in stripe order. sql uses
    the alias r for the R-tree and ends with a condition."""
    from .par import pmap
    x0, x1 = params[0], params[1]          # bbox lon0 / lon1 come first (r.maxx >= ?, r.minx <= ?)
    xs = [x0 + (x1 - x0) * i / STRIPES for i in range(STRIPES + 1)]
    xs[0], xs[-1] = -1e9, 1e9
    jobs = list(zip(xs, xs[1:]))
    part = lambda st: func(rows(gpkgs, sql + " AND r.minx >= ? AND r.minx < ?", tuple(params) + st))
    return [x for out in pmap(part, jobs, 2) for x in out]

