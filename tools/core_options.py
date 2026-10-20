"""Render the congested centre four ways, so the treatment can be chosen.

The centre is not merely busy, it is geometrically over-subscribed. The
widest corridor carries 8 lines, which at a 0.85 mm lane pitch is an 11.9 mm
band, while the median gap between stations there is 3.8 mm. The band is
three times wider than the space between the things it has to connect, so no
amount of tuning makes it read: something has to give.

TfL's standard puts the floor at a station pitch of 10x, where x is the route
line width (Line diagram standard, Issue 4, 2025). At our 0.75 mm line that
would be 7.5 mm. We have 3.8 mm, so by that measure the lines are twice as
thick as the spacing can carry.

The four ways out, rendered rather than argued:

    a  as now        0.75 mm lines, every lane fanned
    b  thin centre   lines taper to 0.35 mm inside the core radius
    c  one trunk     the core bundle merges to a single stroke
    d  wider centre  the centre is enlarged by the solver (separate build)

Usage:
    python core_options.py ../input/tokyo-core.json ../test-results \
        [--expanded ../input/tokyo-expand.json]
"""
import argparse
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path

import citymap
import fanning
import preview_map as pv

CORE_R = 40.0


def draw(ax, city, s, mode, cx, cy, fan=1.2, gap=0.85, base_w=0.75,
         core_w=0.47, core_gap=0.55):
    raw_w = {l.id: getattr(l, "weight", 1.0) for l in city.lines}

    def in_core(p):
        return math.hypot(p[0] * s - cx, p[1] * s - cy) <= CORE_R

    if mode == "c":
        # merge in the core: draw each corridor once, centred, and fan only
        # outside it
        routes, spans = fanning.build(city, fan, gap)
        seen = set()
        for lid, pts in routes:
            if len(pts) < 2:
                continue
            ax.plot([x * s for x, _ in pts], [y * s for _, y in pts],
                    color=pv.SILK, lw=base_w * raw_w.get(lid, 1.0) * pv.PT_PER_MM,
                    zorder=3, solid_capstyle="round")
        # overdraw the core with unfanned centrelines
        for lid, p1, p2, a, b in citymap.segments(city):
            if not (in_core(p1) and in_core(p2)):
                continue
            key = (round(p1[0], 2), round(p1[1], 2), round(p2[0], 2), round(p2[1], 2))
            if key in seen:
                continue
            seen.add(key)
            ax.plot([p1[0] * s, p2[0] * s], [p1[1] * s, p2[1] * s],
                    color=pv.SILK, lw=base_w * 1.6 * pv.PT_PER_MM, zorder=4,
                    solid_capstyle="round")
        return spans

    # In the centre the pitch shrinks with the stroke, so the band narrows
    # instead of merely getting fainter: 8 lanes at 0.85 mm is an 11.9 mm
    # band, at 0.47 mm it is 6.6 mm, which the 3.8 mm station spacing can
    # nearly carry.
    def gap_fn(p1, p2):
        if mode not in ("b", "e"):
            return 1.0
        mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        return core_gap if in_core(mid) else 1.0

    routes, spans = fanning.build(city, fan, gap, gap_fn)
    for lid, pts in routes:
        if len(pts) < 2:
            continue
        w = base_w * raw_w.get(lid, 1.0)
        if mode in ("b", "e"):
            # split the polyline at the core boundary so only the inside thins
            run, inside = [pts[0]], in_core(pts[0])
            for q in pts[1:]:
                if in_core(q) == inside:
                    run.append(q)
                    continue
                run.append(q)
                ww = w * (core_w if inside else 1.0)
                ax.plot([x * s for x, _ in run], [y * s for _, y in run],
                        color=pv.SILK, lw=ww * pv.PT_PER_MM, zorder=3,
                        solid_capstyle="round")
                run, inside = [q], not inside
            if len(run) >= 2:
                ww = w * (core_w if inside else 1.0)
                ax.plot([x * s for x, _ in run], [y * s for _, y in run],
                        color=pv.SILK, lw=ww * pv.PT_PER_MM, zorder=3,
                        solid_capstyle="round")
        else:
            ax.plot([x * s for x, _ in pts], [y * s for _, y in pts],
                    color=pv.SILK, lw=w * pv.PT_PER_MM, zorder=3,
                    solid_capstyle="round")
    return spans


def panel(path, out, title, mode, box=None, core_w=0.47, core_gap=0.55):
    city = citymap.load(path)
    s = 2.0
    st = city.stations["tokyo"]
    cx, cy = st.x * s, st.y * s
    half = 46.0
    X0, Y0, X1, Y1 = cx - half, cy - half, cx + half, cy + half
    fig = plt.figure(figsize=(2 * half / 25.4, 2 * half / 25.4), dpi=180)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(X0, X1)
    ax.set_ylim(Y1, Y0)
    ax.set_facecolor(pv.MASK)
    fig.patch.set_facecolor(pv.MASK)
    ax.set_axis_off()

    import json
    rawd = json.load(open(path, encoding="utf-8"))
    for g in rawd.get("geo", []):
        if g["type"] in ("water", "lake"):
            pts = [(x * s, y * s) for x, y in g["points"]]
            ax.add_patch(PathPatch(Path(pts + [pts[0]], closed=True),
                                   facecolor=pv.GOLD, edgecolor="none", zorder=1))
    spans = draw(ax, city, s, mode, cx, cy, core_w=core_w, core_gap=core_gap)
    for sid, (ang, lo, hi) in spans.items():
        stn = city.stations.get(sid)
        if stn is None:
            continue
        nx, ny = -math.sin(ang), math.cos(ang)
        ax.plot([(stn.x + nx * lo) * s, (stn.x + nx * hi) * s],
                [(stn.y + ny * lo) * s, (stn.y + ny * hi) * s],
                color=pv.SILK, lw=0.75 * pv.PT_PER_MM, zorder=4,
                solid_capstyle="round")
    for stn in list(city.stations.values()) + city.extras:
        ax.add_patch(plt.Rectangle((stn.x * s - 0.8, stn.y * s - 0.75), 1.6, 1.5,
                                   fc=pv.GOLD, ec="none", zorder=5))
    for stn in list(city.stations.values()) + city.extras:
        lx, ly = citymap.label_anchor(stn, s)
        ax.text(lx, ly, "\n".join(citymap.display_lines(stn)),
                color=pv.SILK, fontsize=pv.font_pt(citymap.TEXT_H) * 0.72,
                ha={"start": "left", "end": "right", "middle": "center"}
                   .get(stn.label.get("anchor", "start"), "left"),
                va="center", rotation=-stn.label.get("angle", 0),
                rotation_mode="anchor", zorder=6, linespacing=0.95)
    fig.savefig(out, dpi=180, facecolor=pv.MASK)
    plt.close(fig)
    print(f"  {title}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("outdir")
    ap.add_argument("--expanded", default=None)
    args = ap.parse_args()

    jobs = [
        ("b", args.data, "b  thin only  -  0.35 mm lines, lane pitch left at 0.85", "b", 0.47, 1.0),
        ("e", args.data, "e  thin + tight lanes  -  pitch drops with the stroke", "b", 0.47, 0.55),
        ("f", args.data, "f  tighter still  -  0.26 mm lines, 0.34 mm pitch", "b", 0.35, 0.40),
    ]
    if args.expanded and os.path.exists(args.expanded):
        jobs.append(("g", args.expanded,
                     "g  e + enlarged centre  -  both levers together", "b", 0.47, 0.55))

    outs = []
    for key, path, title, mode, cw, cg in jobs:
        out = os.path.join(args.outdir, f"core-{key}.png")
        panel(path, out, title, mode, core_w=cw, core_gap=cg)
        outs.append((out, title))

    from PIL import Image, ImageDraw, ImageFont
    ims = [Image.open(p).convert("RGB") for p, _ in outs]
    w0, h0 = ims[0].size
    BAR = 46
    cols = 2
    rows = (len(ims) + 1) // 2
    sheet = Image.new("RGB", (w0 * cols + 24, (h0 + BAR) * rows + 24), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("../fonts/ArchivoNarrow-SemiBold.ttf", 28)
    except Exception:
        f = ImageFont.load_default()
    for i, (im, (_, title)) in enumerate(zip(ims, outs)):
        x = (i % cols) * (w0 + 24)
        y = (i // cols) * (h0 + BAR + 24)
        d.text((x + 8, y + 10), title, fill=(255, 220, 90), font=f)
        sheet.paste(im, (x, y + BAR))
    out = os.path.join(args.outdir, "core-options.png")
    sheet.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
