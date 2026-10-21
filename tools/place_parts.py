"""Choose front-side positions for the parts that are not stations: the
decoupling capacitors and the mounting holes. Writes <outdir>/parts.csv for
port_board.py.

Capacitors sit on the front with the LEDs (single-sided assembly), so each
one needs a spot that is clear of every label, route, LED, other part and -
because its pads are copper - the bare-copper water. They are spread evenly
along the LED chain, each beside the nearest LED that has such a spot.

Usage:
    python place_parts.py ../input/tokyo.json ../hardware --scale 2.0
"""
import argparse
import csv
import json
import math
import os

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

import citymap
import export_placement as ep

DEFAULT_CAPS = 52                # make_schematic: 13 rows x --caps-per-row 4.
                                 # One per row was bulk, not decoupling: the
                                 # far LED sat nineteen pitches of trace from
                                 # it and the east of the board was 74 mm from
                                 # the nearest cap. These are spread along the
                                 # chain, so they land across the whole map.
DEFAULT_ROWS = DEFAULT_CAPS
CAP_L, CAP_W = 2.0, 1.1          # 0402 courtyard, mm
RINGS = [3.0, 3.6, 4.4, 5.4]     # candidate distances from the LED centre, mm
LED_CLEAR = 2.2                  # keep a cap this far from any LED centre
WATER_CLEAR = 0.5
LABEL_CLEAR = 0.3
ROUTE_HALF_W = 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("outdir")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--rows", type=int, default=DEFAULT_ROWS,
                    help="decoupling capacitors; must match the number of ROWn symbols make_schematic wrote")
    args = ap.parse_args()
    caps = [f"ROW{i}" for i in range(args.rows)]
    raw = json.load(open(args.data, encoding="utf-8"))
    city = citymap.load(args.data)
    s = args.scale
    W, H = city.canvas_mm * s, city.height * s
    chain = ep.load_chain(args.data, city)
    pos = {st.id: (st.x * s, st.y * s) for st in list(city.stations.values()) + city.extras}

    obstacles = [Point(p).buffer(LED_CLEAR) for p in pos.values()]
    for st in list(city.stations.values()) + city.extras:
        obstacles.append(Polygon(citymap.label_box(st, citymap.TEXT_H, s)).buffer(LABEL_CLEAR))
        seg = citymap.leader_segment(st, s)
        if seg:
            obstacles.append(LineString(seg).buffer(0.4))
    for _, p1, p2, _, _ in citymap.segments(city):
        obstacles.append(LineString([(p1[0] * s, p1[1] * s), (p2[0] * s, p2[1] * s)])
                         .buffer(ROUTE_HALF_W))
    for g in raw.get("geo", []):
        if g["type"] == "water":
            obstacles.append(Polygon([(x * s, y * s) for x, y in g["points"]])
                             .buffer(0).buffer(WATER_CLEAR))
    for a in raw.get("annotations", []):
        w = len(a["text"]) * 0.95 * a["size"]
        obstacles.append(box(a["x"] * s - w / 2 - 1, a["y"] * s - a["size"],
                             a["x"] * s + w / 2 + 1, a["y"] * s + a["size"]))
    holes = raw.get("mounting_holes", [])
    obstacles += [Point(p).buffer(4.5) for p in holes]
    blocked = unary_union(obstacles)
    inside = box(1.5, 1.5, W - 1.5, H - 1.5)

    rows = [{"ref": f"H{i + 1}", "x_mm": x, "y_mm": y, "rotation": 0, "near": ""}
            for i, (x, y) in enumerate(holes)]
    placed = []
    for i, ref in enumerate(caps):
        centre = round((i + 0.5) * len(chain) / len(caps))
        found = None
        # nearest LEDs in chain order first: centre, +1, -1, +2, ...
        for k in sorted(range(len(chain)), key=lambda j: abs(j - centre)):
            lx, ly = pos[chain[k]]
            for ring in RINGS:
                for deg in range(0, 360, 30):
                    cx = lx + ring * math.cos(math.radians(deg))
                    cy = ly + ring * math.sin(math.radians(deg))
                    for rot in (0, 90):
                        hw, hh = (CAP_L / 2, CAP_W / 2) if rot == 0 else (CAP_W / 2, CAP_L / 2)
                        body = box(cx - hw, cy - hh, cx + hw, cy + hh)
                        if (inside.contains(body) and not body.intersects(blocked)
                                and all(body.distance(p) > 1.0 for p in placed)):
                            found = (cx, cy, rot, chain[k], body)
                            break
                    if found:
                        break
                if found:
                    break
            if found:
                break
        assert found, f"no clear spot for {ref}"
        placed.append(found[4])
        rows.append({"ref": ref, "x_mm": round(found[0], 2), "y_mm": round(found[1], 2),
                     "rotation": found[2], "near": found[3]})
        print(f"  {ref}: ({found[0]:.1f}, {found[1]:.1f}) rot {found[2]} beside {found[3]}")

    out = os.path.join(args.outdir, "parts.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ref", "x_mm", "y_mm", "rotation", "near"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} parts to {out}")


if __name__ == "__main__":
    main()
