"""OpenStreetMap input for the encoder: Geofabrik extracts downloaded and converted on demand, and
queries over several of them at once (neighbouring extracts overlap at their borders, so rows are
deduplicated by OSM id).

A region is downloaded to temp/osm/<name>-latest.osm.pbf and converted with ogr2ogr to
temp/osm/<name>.gpkg (layers lines, points, multipolygons). The files are a cache: an extract
older than ASK_DAYS is downloaded again if the user says so (asked on a terminal), one older
than MAX_DAYS always. The region's boundary
(<name>.poly) gives the encoded area: the extract's own extent is larger (whole ways crossing the
border, ferry lines to Scandinavia).
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
REGIONS = {
    "polska": "europe/poland",
    **{v: f"europe/poland/{v}" for v in (
        "dolnoslaskie", "kujawsko-pomorskie", "lodzkie", "lubelskie", "lubuskie", "malopolskie",
        "mazowieckie", "opolskie", "podkarpackie", "podlaskie", "pomorskie", "slaskie",
        "swietokrzyskie", "warminsko-mazurskie", "wielkopolskie", "zachodniopomorskie")},   # countries.VOIVODESHIPS
    "serbia": "europe/serbia",
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
    poly = folder / f"{name}.poly"
    if fresh or not poly.is_file():
        _download(f"{GEOFABRIK}{REGIONS[name]}.poly", poly, log)
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


def _poly_box(path):
    """Box of an osmosis .poly file (lines of "lon lat" between section names and END)."""
    xs, ys = [], []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            xs.append(x)
            ys.append(y)
    return min(xs), min(ys), max(xs), max(ys)


def extent(gpkgs):
    """Union of the regions' boxes (lon0, lat0, lon1, lat1): from <name>.poly next to the
    GeoPackage, else the extent of its lines layer."""
    boxes = []
    for g in gpkgs:
        poly = Path(g).with_suffix(".poly")
        if poly.is_file():
            boxes.append(_poly_box(poly))
            continue
        db = sqlite3.connect(g)
        boxes.append(db.execute("SELECT min(minx), min(miny), max(maxx), max(maxy) FROM rtree_lines_geom").fetchone())
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


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
