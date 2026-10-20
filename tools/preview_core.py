"""Zoom in on one station, in the line colours, to judge the dense core.

    python -X utf8 preview_core.py ../input/tokyo-schematic.json otemachi \
        ../test-results/schematic-core.png [--half 55x42]

`preview_map.py` draws what the board will etch, in white silkscreen on one
page. This draws the same data in the operators' line colours over a crop,
which is the view the central cluster has to be judged in (lesson B4: the
tight cluster decides everything).
"""
import argparse
import io
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("centre", help="station id to centre on")
    ap.add_argument("out")
    ap.add_argument("--half", default="55x42", help="half-width x half-height, mm")
    ap.add_argument("--dpi", type=int, default=120)
    args = ap.parse_args()

    hw, hh = (float(v) for v in args.half.lower().split("x"))
    with io.open(args.data, encoding="utf-8") as f:
        d = json.load(f)
    B = d["board_scale"]
    S = {k: (v["x"] * B, v["y"] * B, v["name"]) for k, v in d["stations"].items()}
    if args.centre not in S:
        raise SystemExit(f"no station {args.centre!r}")
    cx, cy = S[args.centre][:2]

    fig, ax = plt.subplots(figsize=(16, 16 * hh / hw), dpi=args.dpi)
    ax.set_facecolor("#2f5442")
    for g in d["geo"]:
        pts = [(x * B, y * B) for x, y in g["points"]]
        ax.fill([p[0] for p in pts], [p[1] for p in pts],
                color="#f2d43a", lw=0, zorder=1)
    for line in d["lines"]:
        shape = line.get("shape", {})
        for path in line["paths"]:
            for a, b in zip(path, path[1:]):
                if a == b:
                    continue
                via = [(x * B, y * B) for x, y in shape.get(f"{a}|{b}", [])]
                pts = [S[a][:2]] + via + [S[b][:2]]
                ax.plot([q[0] for q in pts], [q[1] for q in pts],
                        color=line["color"], lw=3.2, solid_capstyle="round", zorder=2)
    for sid, (x, y, name) in S.items():
        if abs(x - cx) < hw + 8 and abs(y - cy) < hh + 8:
            ax.plot(x, y, "o", ms=7, mfc="white", mec="#1a1a1a", mew=1.1, zorder=3)
            ax.text(x + 1.0, y - 1.0, name, fontsize=7, color="white", zorder=4)
    ax.set_xlim(cx - hw, cx + hw)
    ax.set_ylim(cy + hh, cy - hh)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    plt.subplots_adjust(0, 0, 1, 1)
    plt.savefig(args.out, dpi=args.dpi)
    print("wrote", os.path.normpath(args.out))


if __name__ == "__main__":
    main()
