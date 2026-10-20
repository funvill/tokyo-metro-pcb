"""Drop the isolated specks of water.

A handful of small polygons survive the land fit a long way from any river
or the bay - 2 to 30 mm2, fifty to a hundred millimetres from the main
water. On the board they read as dirt rather than as geography, and three
of them sit around the TOKYO wordmark.

The test is both small AND far: a piece touching the main body is part of
the river system however small it is (two of them are 0.4 and 0.6 mm away
and must stay), while a piece on its own at the far side of the board is a
pond nobody will recognise.

    python drop_ponds.py ../input/tokyo.json [--max-area 40] [--min-dist 20]
"""
import argparse
import io
import json

from shapely.geometry import Polygon


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max-area", type=float, default=40.0, metavar="MM2",
                    help="only pieces smaller than this can be dropped")
    ap.add_argument("--min-dist", type=float, default=20.0, metavar="MM",
                    help="... and only if they are at least this far from "
                         "the main body of water")
    args = ap.parse_args()

    d = json.load(io.open(args.path, encoding="utf-8"))
    s = d.get("board_scale", 2.0)
    wet = [(i, g) for i, g in enumerate(d.get("geo", []))
           if g["type"] in ("water", "lake")]
    shapes = {}
    for i, g in wet:
        p = Polygon([(x * s, y * s) for x, y in g["points"]]).buffer(0)
        if not p.is_empty:
            shapes[i] = p
    if not shapes:
        print("no water")
        return
    main_i = max(shapes, key=lambda i: shapes[i].area)
    drop = []
    for i, p in shapes.items():
        if i == main_i:
            continue
        dist = p.distance(shapes[main_i])
        if p.area < args.max_area and dist >= args.min_dist:
            drop.append((i, p.area, dist, d["geo"][i].get("name", "")))
    for i, area, dist, name in sorted(drop, key=lambda r: r[1]):
        print(f"  dropping {name or i}: {area:.1f} mm2, {dist:.0f} mm from the main water")
    keep = set(range(len(d["geo"]))) - {i for i, *_ in drop}
    d["geo"] = [g for i, g in enumerate(d["geo"]) if i in keep]
    with io.open(args.path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"dropped {len(drop)} isolated piece(s); {len(d['geo'])} geo shapes left")


if __name__ == "__main__":
    main()
