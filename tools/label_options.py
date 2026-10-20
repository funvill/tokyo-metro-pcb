"""Render the same dense area under several label strategies, side by side.

The optimiser converges by pass two - five passes and ninety thousand
iterations return the identical placement - so the leftover collisions are
not a symptom of too little search. They are the floor the scoring rules
reach. Moving that floor means changing what a fault costs, and the only
honest way to choose between those costs is to look at them.

    python label_options.py ../test-results a=../input/tokyo.json \\
        b=../input/lab-b.json ...
"""
import argparse
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

import citymap
import preview_map as pv


TEXT_BY_KEY = {}


def metrics(city, s=2.0):
    boxes = {sid: Polygon(citymap.label_box(st, citymap.TEXT_H, s))
             for sid, st in city.stations.items()}
    ids = list(boxes)
    lab = sum(1 for i, a in enumerate(ids) for b in ids[i + 1:]
              if boxes[a].intersects(boxes[b]))
    tracks = unary_union([
        LineString([(p1[0] * s, p1[1] * s), (p2[0] * s, p2[1] * s)]).buffer(0.5)
        for _, p1, p2, _, _ in citymap.segments(city)])
    over = sum(1 for sid in ids if boxes[sid].intersects(tracks))
    lead = sum(1 for st in city.stations.values() if st.label.get("leader"))
    rot = sum(1 for st in city.stations.values() if st.label.get("angle", 0))
    return lab, over, lead, rot


def panel(path, out, centre_sid, half):
    city = citymap.load(path)
    s = 2.0
    st = city.stations[centre_sid]
    cx, cy = st.x * s, st.y * s
    fig = plt.figure(figsize=(2 * half / 25.4, 2 * half / 25.4), dpi=190)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy + half, cy - half)
    ax.set_facecolor(pv.MASK)
    fig.patch.set_facecolor(pv.MASK)
    ax.set_axis_off()

    import json
    raw = json.load(open(path, encoding="utf-8"))
    for g in raw.get("geo", []):
        if g["type"] in ("water", "lake"):
            pts = [(x * s, y * s) for x, y in g["points"]]
            ax.add_patch(PathPatch(Path(pts + [pts[0]], closed=True),
                                   facecolor=pv.GOLD, edgecolor="none", zorder=1))
    for lid, p1, p2, a, b in citymap.segments(city):
        ax.plot([p1[0] * s, p2[0] * s], [p1[1] * s, p2[1] * s],
                color=pv.SILK, lw=0.75 * pv.PT_PER_MM, zorder=3,
                solid_capstyle="round")
    for stn in list(city.stations.values()) + city.extras:
        ax.add_patch(plt.Rectangle((stn.x * s - 0.8, stn.y * s - 0.75), 1.6, 1.5,
                                   fc=pv.GOLD, ec="none", zorder=5))
        seg = citymap.leader_segment(stn, s)
        if seg:
            ax.plot([seg[0][0], seg[1][0]], [seg[0][1], seg[1][1]],
                    color=pv.SILK, lw=0.14 * pv.PT_PER_MM, zorder=4)
        lx, ly = citymap.label_anchor(stn, s)
        ax.text(lx, ly, "\n".join(citymap.display_lines(stn)),
                color=pv.SILK, fontsize=pv.font_pt(citymap.TEXT_H) * 0.78,
                ha={"start": "left", "end": "right", "middle": "center",
                    "center": "center"}.get(stn.label.get("anchor", "start"), "left"),
                va="center", rotation=-stn.label.get("angle", 0),
                rotation_mode="anchor", zorder=6, linespacing=0.95)
    fig.savefig(out, dpi=190, facecolor=pv.MASK)
    plt.close(fig)
    return metrics(city)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("outdir")
    ap.add_argument("variants", nargs="+", metavar="KEY=PATH:TITLE")
    ap.add_argument("--centre", default="tokyo")
    ap.add_argument("--half", type=float, default=34.0)
    args = ap.parse_args()

    rows = []
    for spec in args.variants:
        key, rest = spec.split("=", 1)
        path, _, title = rest.partition(":")
        if "@" in key:
            key, th = key.split("@", 1)
            citymap.TEXT_H = float(th)
        else:
            citymap.TEXT_H = 1.1
        if not os.path.exists(path):
            print(f"  {key}: {path} missing, skipped")
            continue
        out = os.path.join(args.outdir, f"lab-{key}.png")
        m = panel(path, out, args.centre, args.half)
        rows.append((key, out, title or key, m))
        print(f"  {key}  on-label {m[0]:3d} | on-track {m[1]:3d} | "
              f"leaders {m[2]:3d} | rotated {m[3]:3d}   {title}")

    if not rows:
        return
    from PIL import Image, ImageDraw, ImageFont
    ims = [Image.open(r[1]).convert("RGB") for r in rows]
    w0, h0 = ims[0].size
    BAR = 74
    cols = 2
    nrow = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (w0 * cols + 24, (h0 + BAR) * nrow + 24), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    try:
        f1 = ImageFont.truetype("../fonts/ArchivoNarrow-SemiBold.ttf", 30)
        f2 = ImageFont.truetype("../fonts/ArchivoNarrow-SemiBold.ttf", 22)
    except Exception:
        f1 = f2 = ImageFont.load_default()
    for i, (key, _, title, m) in enumerate(rows):
        x = (i % cols) * (w0 + 24)
        y = (i // cols) * (h0 + BAR + 24)
        d.text((x + 8, y + 8), f"{key}   {title}", fill=(255, 220, 90), font=f1)
        d.text((x + 8, y + 44),
               f"{m[1]} labels on a route   {m[0]} on another label   "
               f"{m[2]} leaders   {m[3]} rotated",
               fill=(200, 200, 200), font=f2)
        sheet.paste(ims[i], (x, y + BAR))
    out = os.path.join(args.outdir, "label-options.png")
    sheet.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
