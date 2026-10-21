"""Cut the board down without redrawing the map.

    python -X utf8 crop_board.py ../input/tokyo-schematic-sq340.json 340x298 \
        ../input/tokyo-schematic-crop.json [--margin 8]

Rebuilding at a smaller board size does **not** crop anything: the layout
fits itself to whatever board it is given, so a shorter board just draws the
same map smaller, and the proportion of bay at the bottom is unchanged. To
actually remove the bottom of the map, the scale has to stay put and the
board edge has to move in - which is what this does.

It keeps everything above the new edge exactly where it is, clips the water
to the new outline, drops any station that falls off (and takes it out of
the line paths, the chain and the labels), pulls the mounting holes in, and
moves the wordmark up if the crop would have cut it.

Stations are the thing to watch: the map's bottom edge is open bay in the
south-east but the Asakusa line runs down to Nishi-magome in the south-west,
so there is a floor on how much can go before LEDs start being lost. The
tool refuses to drop anything unless --drop-stations is given.
"""
import argparse
import io
import json
import os

from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union


def ring_with_holes(poly, scale):
    pts = list(poly.exterior.coords)[:-1]
    for ring in poly.interiors:
        hole = list(ring.coords)[:-1]
        # The seam must be the SHORTEST chord between the two rings, which
        # means searching both of them. Bridging to hole[0] - whichever
        # vertex shapely happened to start the ring at - makes the seam an
        # arbitrary chord, and a hole cut round an LED is entered through
        # its middle: the seam ran 3.9 mm across Tsukishima and straight
        # over LED20's pads. It is zero width so it does not print and
        # shapely's buffer(0) collapses it, which is why every check here
        # passed, but KiCad's DRC reads it as real boundary and called it a
        # short. Nearest-pair arrives at the rim instead of crossing it.
        i, j = min(
            ((k, m) for k in range(len(pts)) for m in range(len(hole))),
            key=lambda km: (pts[km[0]][0] - hole[km[1]][0]) ** 2 +
                           (pts[km[0]][1] - hole[km[1]][1]) ** 2)
        bridged = hole[j:] + hole[:j] + [hole[j]]
        pts = pts[:i + 1] + bridged + [pts[i]] + pts[i + 1:]
    return [[round(x / scale, 2), round(y / scale, 2)] for x, y in pts]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("size", help="new board size in mm, e.g. 340x298")
    ap.add_argument("out")
    ap.add_argument("--margin", type=float, default=8.0,
                    help="keep this much board below the lowest station")
    ap.add_argument("--drop-stations", action="store_true",
                    help="allow the crop to remove stations that fall off")
    args = ap.parse_args()

    with io.open(args.src, encoding="utf-8") as f:
        d = json.load(f)
    B = d["board_scale"]
    W2, H2 = (float(v) for v in args.size.lower().split("x"))
    W1, H1 = d["canvas_mm"] * B, d["canvas_h_mm"] * B
    print(f"{W1:.0f} x {H1:.0f} mm -> {W2:.0f} x {H2:.0f} mm "
          f"({H1 - H2:.0f} mm off the bottom, {W1 - W2:.0f} off the right)")

    lost = sorted(sid for sid, s in d["stations"].items()
                  if s["y"] * B > H2 - args.margin or s["x"] * B > W2 - args.margin)
    if lost and not args.drop_stations:
        names = ", ".join(d["stations"][s]["name"] for s in lost)
        raise SystemExit(f"{len(lost)} station(s) would be cut: {names}\n"
                         f"re-run with --drop-stations, or crop less")
    gone = {}
    for sid in lost:
        print(f"  dropping {d['stations'][sid]['name']} "
              f"(y = {d['stations'][sid]['y'] * B:.1f} mm)")
        gone[sid] = (d["stations"][sid]["x"] * B, d["stations"][sid]["y"] * B)
        del d["stations"][sid]
    keep = set(d["stations"])

    for line in d["lines"]:
        paths = []
        for path in line["paths"]:
            run = []
            for sid in path:
                if sid in keep:
                    run.append(sid)
                elif len(run) > 1:
                    paths.append(run); run = []
                else:
                    run = []
            if len(run) > 1:
                paths.append(run)
        # A line that loses a station to the crop runs on off the board
        # edge rather than stopping dead, the same as a line cut by the
        # data crop. The stub aims at where the dropped station was and is
        # trimmed to the new edge below.
        new_stubs = []
        for sid, pos in gone.items():
            for path in line["paths"]:
                if sid not in path:
                    continue
                i = path.index(sid)
                for j in (i - 1, i + 1):
                    if 0 <= j < len(path) and path[j] in keep:
                        st = d["stations"][path[j]]
                        new_stubs.append(((st["x"] * B, st["y"] * B), pos))
        line["paths"] = paths
        if new_stubs:
            line.setdefault("stubs", [])
            for here, there in new_stubs:
                line["stubs"].append(
                    [[round(here[0] / B, 3), round(here[1] / B, 3)],
                     [round(there[0] / B, 3), round(there[1] / B, 3)]])
        if line.get("shape"):
            line["shape"] = {k: v for k, v in line["shape"].items()
                             if all(s in keep for s in k.split("|"))}
        if line.get("stubs"):
            stubs = []
            for (x0, y0), (x1, y1) in line["stubs"]:
                x0, y0, x1, y1 = (x0 * B, y0 * B, x1 * B, y1 * B)
                # trim the stub to the new edge
                for lim, cur, other in ((H2, y1, y0), (W2, x1, x0)):
                    if cur > lim and cur != other:
                        t = (lim - other) / (cur - other)
                        x1, y1 = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                if 0 <= x0 <= W2 and 0 <= y0 <= H2:
                    stubs.append([[round(x0 / B, 3), round(y0 / B, 3)],
                                  [round(x1 / B, 3), round(y1 / B, 3)]])
            line["stubs"] = stubs
    d["lines"] = [l for l in d["lines"] if l["paths"] or l.get("stubs")]

    d["chain"] = [s for s in d.get("chain", []) if s in keep]

    frame = box(0, 0, W2, H2)
    geo = []
    for g in d["geo"]:
        poly = Polygon([(x * B, y * B) for x, y in g["points"]]).buffer(0)
        cut = poly.intersection(frame)
        if cut.is_empty:
            continue
        for piece in getattr(cut, "geoms", [cut]):
            if piece.geom_type == "Polygon" and piece.area >= 1.0:
                geo.append({"name": g["name"], "type": g["type"],
                            "points": ring_with_holes(piece, B)})
    print(f"  water: {len(d['geo'])} pieces -> {len(geo)}")
    d["geo"] = geo

    inset = d["mounting_holes"][0][0] if d["mounting_holes"] else 4.0
    d["mounting_holes"] = [[x, y] for x in (inset, W2 - inset)
                           for y in (inset, H2 - inset)]

    # build_tokyo cut a clearance disc out of the water at each mounting
    # hole - but at the UNCROPPED corners. Moving the board edge in moves
    # the holes, and nothing re-cut at the new positions, so a corner that
    # now lands in the bay was drilled straight through the copper pour:
    # 60.8 of the 63.5 mm2 keepout at (316, 276) was solid copper, and it
    # is where two of the board's DRC shorts came from.
    HOLE_CLEAR_MM = 4.5
    holed = []
    for g in d["geo"]:
        if g["type"] not in ("water", "lake"):
            holed.append(g)
            continue
        poly = Polygon([(x * B, y * B) for x, y in g["points"]]).buffer(0)
        for hx, hy in d["mounting_holes"]:
            poly = poly.difference(Point(hx, hy).buffer(HOLE_CLEAR_MM, 16))
        if poly.is_empty:
            continue
        for piece in getattr(poly, "geoms", [poly]):
            if piece.geom_type == "Polygon" and piece.area >= 1.0:
                holed.append({"name": g["name"], "type": g["type"],
                              "points": ring_with_holes(piece, B)})
    cut_n = len(holed) - sum(1 for g in d["geo"] if g["type"] in ("water", "lake"))
    d["geo"] = holed

    # Both splits above - the frame intersection and the mounting-hole
    # difference - can break one polygon into several, and each piece kept
    # the parent's name. export_art derives its block uuid from that name
    # (uuid5 of "water:NAME:LAYER"), so two pieces called water-0 produced
    # two board items with the SAME uuid. That is a malformed KiCad file,
    # it collapses the art manifest's {uuid: key} to one entry for two
    # blocks, and mask_under_silk keys its drawings by uuid in a dict, so
    # one of the pair was silently dropped and its solder-mask opening was
    # never cut back under the silkscreen - leaving front silk over a bare
    # copper opening, which the fab clips away. The first piece keeps the
    # plain name so existing hand work still matches; extras are suffixed.
    seen = {}
    for g in d["geo"]:
        n = g["name"]
        seen[n] = seen.get(n, 0) + 1
        if seen[n] > 1:
            g["name"] = f"{n}-{seen[n] - 1}"
    dups = [n for n, c in seen.items() if c > 1]
    if dups:
        print(f"  renamed split pieces so every geo name is unique: "
              f"{', '.join(f'{n} x{seen[n]}' for n in dups)}")
    print(f"  mounting holes cleared from the water "
          f"({len(d['mounting_holes'])} holes, {HOLE_CLEAR_MM} mm)")

    for a in d.get("annotations", []):
        th = 1.25 * a.get("size", 14.0)
        if a["y"] * B + th / 2 > H2 - 4:
            a["y"] = round((H2 - 4 - th / 2) / B, 2)
            print(f"  moved the wordmark up to y = {a['y'] * B:.0f} mm")

    d["canvas_mm"] = W2 / B
    d["canvas_h_mm"] = H2 / B
    with io.open(args.out, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    print(f"wrote {os.path.basename(args.out)}: {len(d['stations'])} LEDs")


if __name__ == "__main__":
    main()
