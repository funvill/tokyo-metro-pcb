"""Tokyo land and water from OpenStreetMap, as the board's exposed copper.

    python -X utf8 geo_tokyo.py [out.png]

Why this shape of source. Tokyo has both kinds of water, so both kinds of
source are used:

* **Tokyo Bay is a coastline**, mapped as `natural=coastline` lines, not as
  a polygon. Lesson B1 says to prefer polygons and warns that assembling
  coastline lines into land/sea faces is where the Vancouver attempt went
  wrong. The reason it went wrong there was that OSM's coastline *stopped*
  mid-region; here the bay's coastline crosses the whole frame, so the faces
  can be built and then classified by OSM's own convention (land on the
  left of a coastline way, water on the right). The classification is a
  vote over sample points, and `sea()` prints the vote so a wrong answer is
  visible rather than silent.
* **The rivers, canals and the Imperial Palace moats are polygons**
  (`natural=water` with `water=river|canal|moat`, ways and multipolygon
  relations), so they need no assembly at all.

Narrow water is widened rather than dropped. The Kanda river is about 30 m
across and the palace moats 50-100 m; at this scale that is a third of a
millimetre of copper, which would etch as a hairline or vanish. Named
waterways are drawn at MIN_DRAW_WIDTH_KM by buffering their centre lines
(osm/waterways.json), which is a deliberate cartographic exaggeration of
width - never of position, and never of the land (lesson A2).

Everything is cached in osm/ by fetch_osm.sh and committed, so this runs
offline and reproducibly.
"""
import io
import json
import math
import os
import sys

from shapely.geometry import LineString, MultiLineString, Point, Polygon, box
from shapely.ops import polygonize, unary_union

HERE = os.path.dirname(os.path.abspath(__file__))

# --- frame ------------------------------------------------------------------
# True scale, north up, no warp: Phase 0 settled on real proportions with the
# land moved rigidly to meet the schematic (lesson A2), so there is nothing
# here to bend.
#
# The frame is the station bounding box (lat 35.587..35.792,
# lon 139.613..139.959 over 221 stations) plus room for the outermost
# labels, and the board takes the frame's aspect rather than the other way
# round (lesson B3).
# The southern edge runs well past the last station on purpose. The land is
# placed by fitting it to the stations, so wherever the frame stops, the
# water stops - and a frame that ends at the southernmost station leaves a
# blank band along the bottom of the board where the bay should be. The
# cached water reaches 35.40, so there is data to use.
LAT0, LAT1 = 35.800, 35.500          # north .. south
LON0, LON1 = 139.600, 139.972        # west .. east
BOARD_W_MM = 400.0

LAT_MID = (LAT0 + LAT1) / 2
KX = 111.32 * math.cos(math.radians(LAT_MID))   # km per degree of longitude
KY = 110.57                                     # km per degree of latitude

W_KM = (LON1 - LON0) * KX
H_KM = (LAT0 - LAT1) * KY
FRAME = box(0, 0, W_KM, H_KM)
FRAME_NAME = "metro+toei"
MM_PER_KM = BOARD_W_MM / W_KM
BOARD_H_MM = H_KM * MM_PER_KM


def km(lat, lon):
    """Frame-relative km: x east from the west edge, y south from the north
    edge. True scale, so a kilometre is a kilometre everywhere."""
    return ((lon - LON0) * KX, (LAT0 - lat) * KY)


# --- what to draw -----------------------------------------------------------
# Flowing and navigable water, kept as polygons.
FLOW_KINDS = {"river", "canal", "moat", "harbour", "lake", "lagoon"}
MIN_FLOW_KM2 = 0.02          # smaller than this is a ditch or an ornamental pool
MIN_RIVER_WIDTH_KM = 0.02    # mean width 2*area/perimeter

# Water worth drawing that is not flowing: by name, never by area. An area
# threshold turns the map to confetti - greater Tokyo has 900+ ponds, 500
# reservoirs and 470 wastewater basins in this frame alone (lesson B1).
# Shinobazu pond is not mapped under that name: OSM has it as its three
# parts (ボート池 / 鵜の池 / 蓮池). The palace moats come in through
# water=moat below and need no names.
KEEP_WATER = {
    "ボート池", "鵜の池", "蓮池",   # Shinobazu pond, Ueno park
    "心字池",          # Hibiya park
    "大泉水",          # Koishikawa Korakuen
    "洗足池", "三四郎池",
}

# Water that must survive the smoothing whatever its size: the Imperial
# Palace moats are the Tokyo feature this board most wants, and they are
# 29-69 m wide - narrower than the 50 m nook the open/close removes, and
# each segment is well under MIN_PIECE_KM2. They are widened to a drawable
# width and unioned back in after smoothing.
KEEP_KINDS = {"moat"}

# Named waterways drawn at a minimum width from their centre lines. These
# are the waters the map is about: without them the middle of the board is
# blank copper-free FR4 where Tokyo's rivers should be.
KEEP_WATERWAYS = {
    "隅田川",      # Sumida river
    "荒川",        # Arakawa
    "神田川",      # Kanda river
    "日本橋川",    # Nihonbashi river
    "小名木川",    # Onagi canal
    "中川", "旧中川", "新中川", "江戸川", "旧江戸川",
    "目黒川", "古川", "渋谷川",
    "石神井川", "妙正寺川", "善福寺川",
    "北十間川", "横十間川", "大横川", "仙台堀川", "竪川",
    "亀島川", "月島川", "晴海運河", "朝潮運河",
    "多摩川",
    "外濠", "内濠",
}
MIN_DRAW_WIDTH_KM = 0.11     # ~1.4 mm of copper at this scale

SMOOTH_KM = 0.03             # simplify tolerance
OPEN_CLOSE_KM = 0.025        # drops nooks narrower than ~50 m
MIN_PIECE_KM2 = 0.04         # a disconnected piece of water must be this big
MIN_ISLAND_KM2 = 0.05        # smaller holes in the water are filled


def _elements(name):
    with io.open(os.path.join(HERE, "osm", name), encoding="utf-8") as f:
        return json.load(f)["elements"]


def _ring(geometry):
    return [km(p["lat"], p["lon"]) for p in geometry]


def _polygon(el):
    """One OSM element -> shapely polygon in frame km, or None.

    `out body geom` gives relations their member geometry; `out tags geom`
    does not, and multipolygon water silently vanishes (lesson A3).
    """
    if el["type"] == "way":
        r = _ring(el.get("geometry", []))
        if len(r) < 4 or r[0] != r[-1]:
            return None
        return Polygon(r).buffer(0)
    ways = [m for m in el.get("members", []) if m["type"] == "way" and "geometry" in m]
    outer = [LineString(_ring(m["geometry"])) for m in ways
             if m.get("role") != "inner" and len(m["geometry"]) >= 2]
    inner = [LineString(_ring(m["geometry"])) for m in ways
             if m.get("role") == "inner" and len(m["geometry"]) >= 2]
    if not outer:
        return None
    g = unary_union(list(polygonize(unary_union(outer))))
    if g.is_empty:
        return None
    if inner:
        holes = unary_union(list(polygonize(unary_union(inner))))
        if not holes.is_empty:
            g = g.difference(holes)
    return g.buffer(0)


# --- Tokyo Bay --------------------------------------------------------------
def sea(verbose=False):
    """The bay, built from `natural=coastline` and classified by OSM's
    land-on-the-left convention.

    Prints the vote: a sea face should win by a wide margin. A narrow or
    negative margin means the coastline does not cross the frame cleanly and
    the answer is not to be trusted.
    """
    lines = []
    for el in _elements("water.json"):
        if el.get("tags", {}).get("natural") != "coastline":
            continue
        pts = _ring(el.get("geometry", []))
        if len(pts) >= 2:
            lines.append(LineString(pts))
    if not lines:
        return Polygon()
    net = unary_union(lines + [FRAME.boundary])
    faces = [f for f in polygonize(net) if f.area > 0.001]
    if not faces:
        return Polygon()

    # Sample each coastline a little to its right (water) and left (land).
    off = 0.02          # 20 m
    right, left = [], []
    for ln in lines:
        for s in (0.25, 0.5, 0.75):
            d = ln.length * s
            p, q = ln.interpolate(d), ln.interpolate(min(d + 0.01, ln.length))
            dx, dy = q.x - p.x, q.y - p.y
            n = math.hypot(dx, dy)
            if n == 0:
                continue
            # OSM's convention is land on the left of the way's direction.
            # This frame has y south-positive, which is a reflection of
            # lat/lon, so handedness flips: the water side here is the
            # (-dy, dx) normal, not (dy, -dx). The vote below is what
            # proves it - with the sign wrong, the land wins by 212 votes
            # and 86% of the board turns to copper.
            right.append(Point(p.x - off * dy / n, p.y + off * dx / n))
            left.append(Point(p.x + off * dy / n, p.y - off * dx / n))
    scored = []
    for f in faces:
        r = sum(1 for p in right if f.contains(p))
        l = sum(1 for p in left if f.contains(p))
        scored.append((r - l, r, l, f))
    scored.sort(key=lambda s: -s[0])
    if verbose:
        print(f"  coastline: {len(lines)} ways, {len(faces)} faces")
        for score, r, l, f in scored[:6]:
            print(f"    face {f.area:8.2f} km2  water-side {r:4d}  land-side {l:4d}"
                  f"  vote {score:+5d}{'   <- sea' if score > 0 else ''}")
    out = unary_union([f for score, r, l, f in scored if score > 0])
    return out.intersection(FRAME)


# --- rivers, canals and moats ----------------------------------------------
def flow_raw():
    out = []
    for el in _elements("water.json"):
        t = el.get("tags", {})
        kind = t.get("water") or ("river" if t.get("waterway") == "riverbank" else None)
        keep_name = t.get("name") in KEEP_WATER
        if kind not in FLOW_KINDS and not keep_name:
            continue
        g = _polygon(el)
        if g is None or g.is_empty:
            continue
        if keep_name:
            out.append(g)
            continue
        if g.area < MIN_FLOW_KM2 or 2 * g.area / g.length < MIN_RIVER_WIDTH_KM:
            continue
        out.append(g)
    return unary_union(out) if out else Polygon()


def _widen(g, target):
    """Dilate a ribbon of water until its mean width reaches `target`.

    Mean width is 2 * area / perimeter. A 40 m moat at 11.9 mm/km is less
    than half a millimetre of copper: it would etch as a hairline, and the
    solder-mask opening under it would be thinner still.
    """
    if g.is_empty or g.length == 0:
        return g
    w = 2 * g.area / g.length
    if w >= target:
        return g
    return g.buffer((target - w) / 2, resolution=4)


def keep_raw():
    """Water kept whatever its size: the palace moats and the named ponds."""
    out = []
    for el in _elements("water.json"):
        t = el.get("tags", {})
        if t.get("water") not in KEEP_KINDS and t.get("name") not in KEEP_WATER:
            continue
        g = _polygon(el)
        if g is None or g.is_empty:
            continue
        out.append(_widen(g, MIN_DRAW_WIDTH_KM))
    return unary_union(out) if out else Polygon()


def waterways_raw():
    """Named river and canal centre lines, buffered to a drawable width."""
    out = []
    for el in _elements("waterways.json"):
        t = el.get("tags", {})
        if t.get("name") not in KEEP_WATERWAYS:
            continue
        pts = _ring(el.get("geometry", []))
        if len(pts) >= 2:
            out.append(LineString(pts))
    if not out:
        return Polygon()
    return unary_union(out).buffer(MIN_DRAW_WIDTH_KM / 2, resolution=4)


def _fill_small_holes(geom, min_km2):
    out = []
    for g in getattr(geom, "geoms", [geom]):
        if g.geom_type != "Polygon":
            continue
        out.append(Polygon(g.exterior, [r for r in g.interiors
                                        if Polygon(r).area >= min_km2]))
    return unary_union(out)


def water(smooth=True, verbose=False):
    bay = sea(verbose=verbose)
    flow = flow_raw().intersection(FRAME)
    ways = waterways_raw().intersection(FRAME)
    w = unary_union([bay, flow, ways])
    # Drop disconnected slivers, but never the bay.
    pieces = [g for g in getattr(w, "geoms", [w])
              if g.area >= MIN_PIECE_KM2 or (not bay.is_empty and g.intersects(bay))]
    w = unary_union(pieces)
    if smooth:
        w = w.buffer(-OPEN_CLOSE_KM).buffer(2 * OPEN_CLOSE_KM).buffer(-OPEN_CLOSE_KM)
        w = w.simplify(SMOOTH_KM, preserve_topology=True)
        w = _fill_small_holes(w, MIN_ISLAND_KM2)
        w = unary_union([g for g in getattr(w, "geoms", [w])
                         if g.area >= MIN_PIECE_KM2])
    # The moats and the named ponds go in after the smoothing, never
    # through it: every one of them is narrower than the nook the
    # open/close removes and smaller than the piece threshold, so passing
    # them through would delete the Imperial Palace.
    keep = keep_raw().intersection(FRAME).simplify(SMOOTH_KM, preserve_topology=True)
    w = unary_union([w, keep]).intersection(FRAME)
    return w


# --- preview ----------------------------------------------------------------
def render(path, water_geom, stations=None, lines=None, dpi=110, labels=True):
    """Preview PNG in the board's colours: ENIG-gold water on green mask."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

    fig, ax = plt.subplots(figsize=(18, 18 * H_KM / W_KM), dpi=dpi)
    ax.set_facecolor("#2f5442")
    for g in getattr(water_geom, "geoms", [water_geom]):
        if g.geom_type != "Polygon":
            continue
        x, y = g.exterior.xy
        ax.fill(x, y, color="#f2d43a", lw=0, zorder=1)
        for r in g.interiors:
            x, y = r.xy
            ax.fill(x, y, color="#2f5442", lw=0, zorder=1)
    for colour, path_ids in lines or []:
        pts = [stations[s][:2] for s in path_ids if s in stations]
        ax.plot([p[0] for p in pts], [p[1] for p in pts],
                color=colour, lw=1.8, solid_capstyle="round", zorder=2)
    for sid, (x, y, name) in (stations or {}).items():
        ax.plot(x, y, "o", ms=3.5, mfc="white", mec="#222222", mew=0.6, zorder=3)
        if labels:
            ax.text(x + 0.12, y - 0.12, name, fontsize=4.2, color="white",
                    zorder=4, ha="left", va="bottom")
    ax.set_xlim(0, W_KM)
    ax.set_ylim(H_KM, 0)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    plt.subplots_adjust(0, 0, 1, 1)
    plt.savefig(path, dpi=dpi)
    plt.close(fig)


def load_stations():
    with io.open(os.path.join(HERE, "tokyo_station_latlon.json"), encoding="utf-8") as f:
        latlon = json.load(f)
    with io.open(os.path.join(HERE, "tokyo_stations.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with io.open(os.path.join(HERE, "tokyo_lines.json"), encoding="utf-8") as f:
        lines = json.load(f)
    stations = {}
    for sid, (lat, lon) in latlon.items():
        x, y = km(lat, lon)
        stations[sid] = (x, y, meta.get(sid, {}).get("name", sid))
    paths = [(l["colour"], p) for l in lines.values() for p in l["paths"]]
    return stations, paths


if __name__ == "__main__":
    print(f"frame '{FRAME_NAME}' {W_KM:.1f} x {H_KM:.1f} km")
    print(f"board {BOARD_W_MM:.0f} x {BOARD_H_MM:.0f} mm at {MM_PER_KM:.2f} mm/km")
    w = water(verbose=True)
    n = len([g for g in getattr(w, "geoms", [w])])
    print(f"water: {n} piece(s), {w.area:.1f} km2 of {W_KM * H_KM:.0f} "
          f"({100 * w.area / (W_KM * H_KM):.0f}% of the board)")

    stations, paths = load_stations()
    outside = [s for s, (x, y, _) in stations.items()
               if not (0 <= x <= W_KM and 0 <= y <= H_KM)]
    wet = [stations[s][2] for s, (x, y, _) in stations.items()
           if w.contains(Point(x, y))]
    print(f"stations: {len(stations)}; outside the frame: {outside or 'none'}")
    print(f"stations in water: {wet or 'none'}")

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        HERE, "..", "test-results", "geo-preview.png")
    render(out, w, stations, paths)
    print("wrote", os.path.normpath(out))
