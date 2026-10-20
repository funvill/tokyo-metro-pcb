"""Cut the real track alignment into per-leg via points.

A schematic map draws a straight hop between adjacent stations. A realistic
one draws the rails: the Oedo Line's loop under Shinjuku, the Marunouchi
Line's hairpin at Korakuen, the Arakawa tram winding through Oji, the
Yurikamome spiralling up onto the Rainbow Bridge. That shape is in
OpenStreetMap as the way members of each route relation, and this turns it
into the `shape` field the board already understands.

Method, per line:
  * take the route relation's way members, merge them into as few continuous
    lines as possible
  * for each pair of adjacent stations, find the merged line that carries
    both, and take the piece between them
  * reject a piece that is far longer than the straight hop, which is what
    projecting onto a loop gives you when it goes the wrong way round

    python make_alignments.py osm/tracks.json station_latlon.json \\
        alignments.json
"""
import io
import json
import os
import math
import sys
from collections import defaultdict

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

# ref -> our line id. The directional and through-service duplicates all
# carry the same ref, so one relation per ref is picked by way count.
REF = {
    "A": "asakusa", "C": "chiyoda", "E": "oedo", "F": "fukutoshin",
    "G": "ginza", "H": "hibiya", "I": "mita", "JY": "yamanote",
    "M": "marunouchi", "N": "namboku", "R": "rinkai", "S": "shinjuku",
    "SA": "arakawa", "T": "tozai", "U": "yurikamome", "Y": "yurakucho",
    "Z": "hanzomon",
}
SHINKANSEN = "shinkansen"
DETOUR_MAX = 2.6        # a leg's rails may wander this much further than the
                        # straight hop before the match is called wrong
SIMPLIFY_DEG = 0.00012  # about 13 m


def merged_lines(rel, ways):
    segs = []
    for m in rel.get("members", []):
        if m["type"] != "way" or m.get("role") not in ("", None):
            continue
        g = ways.get(m["ref"])
        if g and len(g) > 1:
            segs.append(LineString([(lon, lat) for lat, lon in g]))
    if not segs:
        return []
    merged = linemerge(MultiLineString(segs))
    return list(getattr(merged, "geoms", [merged]))


def leg_shape(lines, a, b):
    """The rails between two stations, or None."""
    pa, pb = Point(a[1], a[0]), Point(b[1], b[0])
    straight = pa.distance(pb)
    if straight < 1e-9:
        return None
    best = None
    for ln in lines:
        da, db = ln.project(pa), ln.project(pb)
        # the station must actually be near this line, not merely projectable
        if ln.interpolate(da).distance(pa) > straight * 0.6:
            continue
        if ln.interpolate(db).distance(pb) > straight * 0.6:
            continue
        lo, hi = (da, db) if da <= db else (db, da)
        piece = substring(ln, lo, hi)
        if piece.is_empty or piece.length < 1e-12:
            continue
        pts = list(piece.coords)
        if da > db:
            pts = pts[::-1]
        ratio = piece.length / straight
        if ratio > DETOUR_MAX:
            continue
        if best is None or ratio < best[0]:
            best = (ratio, pts)
    return best[1] if best else None


def main():
    src, stations_path, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    data = json.load(io.open(src, encoding="utf-8"))
    ways = {e["id"]: [(p["lat"], p["lon"]) for p in e.get("geometry", [])]
            for e in data["elements"] if e["type"] == "way"}
    rels = [e for e in data["elements"] if e["type"] == "relation"]

    # one relation per line: the one with the most way members
    pick = {}
    for r in rels:
        t = r.get("tags", {})
        ref = t.get("ref", "")
        name = t.get("name", "")
        lid = REF.get(ref)
        if lid is None and "新幹線" in name:
            lid = SHINKANSEN
        if lid is None:
            continue
        n = sum(1 for m in r.get("members", [])
                if m["type"] == "way" and m.get("role") in ("", None))
        if lid not in pick or n > pick[lid][0]:
            pick[lid] = (n, r)

    latlon = json.load(io.open(stations_path, encoding="utf-8"))
    board = json.load(io.open("tokyo.json", encoding="utf-8"))

    out, stats = {}, []
    for lid, (_, rel) in sorted(pick.items()):
        lines = merged_lines(rel, ways)
        if not lines:
            continue
        paths = next((l["paths"] for l in board["lines"] if l["id"] == lid), [])
        got = miss = 0
        for path in paths:
            for a, b in zip(path, path[1:]):
                if a not in latlon or b not in latlon:
                    miss += 1
                    continue
                pts = leg_shape(lines, latlon[a], latlon[b])
                if not pts or len(pts) < 3:
                    miss += 1
                    continue
                # Cutting a leg out of a merged line can leave a point the
                # line runs out to and comes straight back from - a 176
                # degree reversal that draws as a stub hanging in mid air
                # beside the station, as it did next to Osaki. Real track
                # never reverses; the Yurikamome's spiral onto the Rainbow
                # Bridge turns about 125 degrees and must survive, so the
                # threshold sits well above it.
                sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                                "..", "tools"))
                import despike as _ds
                pts, _n = _ds.despike(list(pts), 135.0)
                simple = LineString(pts).simplify(SIMPLIFY_DEG)
                coords = [[round(y, 6), round(x, 6)] for x, y in simple.coords]
                if len(coords) < 3:
                    miss += 1
                    continue
                out.setdefault(lid, {})[f"{a}|{b}"] = coords
                got += 1
        stats.append((lid, got, miss, len(lines)))

    for lid, got, miss, n in stats:
        print(f"  {lid:12s} {got:3d} legs on real rails, {miss:3d} without "
              f"({n} merged run{'s' if n != 1 else ''})")
    total_got = sum(s[1] for s in stats)
    total_miss = sum(s[2] for s in stats)
    print(f"total: {total_got} legs with a real alignment, {total_miss} left straight")
    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", dst)


if __name__ == "__main__":
    main()
