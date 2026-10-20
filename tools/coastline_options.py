"""Render the same bay four ways, so the coastline treatment can be chosen.

The research is blunt about this one: a coastline traced from reality and set
against a strictly octolinear network reads as an error in the *network*, and
readers trust the coastline over the stations (Verbeeck 2008; Berendt, Rauh &
Barkowsky 1997, via Wu et al., A Survey on Transit Map Layout, CGF 2020).
Jug Cerovic's Tokyo map and the MTA's 2025 New York redesign both keep a
recognisable shoreline silhouette without keeping it accurate.

Against that, a realistic landscape was asked for. So the four options are
rendered side by side rather than argued about:

    a  traced        the real shoreline, as now
    b  smoothed      the same shape, fewer vertices and softer
    c  octolinear    simplified onto the 45 degree grid the tracks use
    d  schematic     heavily reduced, a silhouette only

Usage:
    python coastline_options.py ../input/tokyo-core.json ../test-results
"""
import argparse
import math
import os

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

SNAP = math.radians(45.0)


def octolinear_ring(ring, step):
    """Redraw a ring so every edge runs at a multiple of 45 degrees.

    Each edge becomes a dogleg of two octolinear segments that start and end
    where the real edge does, so the shape stays put while its edges join
    the grid. Doing it per edge rather than per vertex is what keeps the
    coastline recognisable - snapping vertices to a grid instead collapses
    the narrow channels.
    """
    pts = list(ring)
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if math.hypot(dx, dy) < step:
            out.append(b)
            continue
        ang = math.atan2(dy, dx)
        lo = math.floor(ang / SNAP) * SNAP
        hi = lo + SNAP
        # the corner where the two allowed directions meet
        d1 = (math.cos(lo), math.sin(lo))
        d2 = (math.cos(hi), math.sin(hi))
        den = d1[0] * d2[1] - d1[1] * d2[0]
        if abs(den) < 1e-9:
            out.append(b)
            continue
        t = (dx * d2[1] - dy * d2[0]) / den
        out.append((a[0] + d1[0] * t, a[1] + d1[1] * t))
        out.append(b)
    return out


def variant(water, name):
    if name == "a":
        return water
    if name == "b":
        return water.simplify(0.6, preserve_topology=True).buffer(
            0.8, join_style=1).buffer(-0.8, join_style=1)
    if name == "c":
        simple = water.simplify(1.2, preserve_topology=True)
        polys = []
        for g in getattr(simple, "geoms", [simple]):
            if g.geom_type != "Polygon" or g.is_empty:
                continue
            shell = octolinear_ring(list(g.exterior.coords), 1.5)
            holes = [octolinear_ring(list(r.coords), 1.5) for r in g.interiors
                     if len(r.coords) > 4]
            try:
                p = Polygon(shell, holes).buffer(0)
            except Exception:
                continue
            if not p.is_empty:
                polys.append(p)
        return unary_union(polys) if polys else simple
    if name == "d":
        return (water.buffer(2.5, join_style=2).buffer(-2.5, join_style=2)
                .simplify(3.0, preserve_topology=True))
    raise ValueError(name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("outdir")
    ap.add_argument("--scale", type=float, default=2.0)
    args = ap.parse_args()

    import json
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path

    import citymap
    import preview_map as pv

    raw = json.load(open(args.data, encoding="utf-8"))
    city = citymap.load(args.data)
    s = args.scale
    water = unary_union([p for p in
                         (Polygon([(x * s, y * s) for x, y in g["points"]]).buffer(0)
                          for g in raw.get("geo", [])
                          if g["type"] in ("water", "lake"))
                         if not p.is_empty])

    # the bay, bottom right
    X0, Y0, X1, Y1 = 150.0, 150.0, 320.0, 280.0
    titles = {"a": "a  traced (as now)", "b": "b  smoothed",
              "c": "c  octolinear", "d": "d  schematic"}
    paths = []
    for key in ("a", "b", "c", "d"):
        w = variant(water, key)
        fig = plt.figure(figsize=((X1 - X0) / 25.4, (Y1 - Y0) / 25.4), dpi=170)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(X0, X1)
        ax.set_ylim(Y1, Y0)
        ax.set_facecolor(pv.MASK)
        fig.patch.set_facecolor(pv.MASK)
        ax.set_axis_off()
        for g in getattr(w, "geoms", [w]):
            if g.geom_type != "Polygon":
                continue
            pts = list(g.exterior.coords)
            ax.add_patch(PathPatch(Path(pts, closed=True), facecolor=pv.GOLD,
                                   edgecolor="none", zorder=1))
            for r in g.interiors:
                ax.add_patch(PathPatch(Path(list(r.coords), closed=True),
                                       facecolor=pv.MASK, edgecolor="none",
                                       zorder=2))
        for lid, p1, p2, a, b in citymap.segments(city):
            ax.plot([p1[0] * s, p2[0] * s], [p1[1] * s, p2[1] * s],
                    color=pv.SILK, lw=0.75 * pv.PT_PER_MM, zorder=3,
                    solid_capstyle="round")
        for st in list(city.stations.values()) + city.extras:
            ax.add_patch(plt.Rectangle((st.x * s - 0.8, st.y * s - 0.75), 1.6, 1.5,
                                       fc=pv.GOLD, ec="none", zorder=4))
        out = os.path.join(args.outdir, f"coast-{key}.png")
        fig.savefig(out, dpi=170, facecolor=pv.MASK)
        plt.close(fig)
        paths.append((out, titles[key],
                      sum(len(g.exterior.coords) for g in getattr(w, "geoms", [w])
                          if g.geom_type == "Polygon")))
        print(f"  {titles[key]:22s} {paths[-1][2]:5d} outline points")

    # one sheet, labelled
    from PIL import Image, ImageDraw, ImageFont
    ims = [Image.open(p).convert("RGB") for p, _, _ in paths]
    w0, h0 = ims[0].size
    BAR = 48
    sheet = Image.new("RGB", (w0 * 2 + 24, (h0 + BAR) * 2 + 24), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("../fonts/ArchivoNarrow-SemiBold.ttf", 30)
    except Exception:
        f = ImageFont.load_default()
    for i, (im, (_, title, n)) in enumerate(zip(ims, paths)):
        x = (i % 2) * (w0 + 24)
        y = (i // 2) * (h0 + BAR + 24)
        d.text((x + 8, y + 10), f"{title}   -   {n} outline points",
               fill=(255, 220, 90), font=f)
        sheet.paste(im, (x, y + BAR))
    out = os.path.join(args.outdir, "coast-options.png")
    sheet.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
