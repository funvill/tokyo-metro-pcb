"""Board-accurate PNG preview of vancouver.json without KiCad.

Draws exactly what export_art.py will put on the board - water and
copper furniture in gold, routes / rings / labels / leaders in white silk
- using the same geometry helpers (citymap.prepared_geo, label_anchor,
display_lines, leader_segment), so the label layout can be iterated here
and only committed to the .kicad_pcb once it reads well.

Usage:
    python preview_map.py ../input/vancouver.json ../test-results/preview.png [--scale 2.0] [--collisions]
"""
import argparse
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, PathPatch
from matplotlib.path import Path

import citymap
import fanning
import check_fit
import export_art

GOLD, SILK, MASK = "#e8c93a", "#f4f4f4", "#2f5442"
PT_PER_MM = 72 / 25.4
LINESPACING = 1.15   # one place: the renderer draws with it and the
                     # capsule's height is computed from it
# The board's real label face, so the preview crowds exactly as the board
# will. citymap.CHAR_W is measured from this font; drawing the preview in
# anything else makes the label pass look better or worse than it is.
import matplotlib.font_manager as _fm, os as _os
_FONT_TTF = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "..", "fonts", "ArchivoNarrow-SemiBold.ttf")
if _os.path.exists(_FONT_TTF):
    _fm.fontManager.addfont(_FONT_TTF)
    FONT = _fm.FontProperties(fname=_FONT_TTF).get_name()
else:
    FONT = "DejaVu Sans Mono"   # closest stock match to KiCad's stroke font width


def font_pt(size_mm):
    # KiCad's "size" is roughly the cap height; matplotlib's is the em box
    return size_mm * PT_PER_MM * 1.35


def draw_poly(ax, pts, color, z):
    ax.add_patch(PathPatch(Path(pts + [pts[0]], closed=True), facecolor=color,
                           edgecolor="none", zorder=z))


def render(city, scale, out, collisions=False, dpi=300, fan=0.0, fan_gap=0.8,
           core_r=0.0, core_w=0.35, core_gap=0.40, halo=0.0,
           pill_border=0.0, pad_halo=0.0):
    W, H = city.canvas_mm * scale, city.height * scale
    fig = plt.figure(figsize=(W / 25.4, H / 25.4), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.set_facecolor(MASK)
    ax.set_axis_off()
    avoid = export_art.avoid_points(city, scale)
    geo = citymap.prepared_geo(city, scale, avoid)
    for g in geo:
        pts = [tuple(p) for p in g["points"]]
        if g["type"] in ("water", "lake"):
            draw_poly(ax, pts, GOLD, 1)
        elif g["type"] == "line":
            col = GOLD if g.get("copper") else SILK
            w = g.get("width", 0.3)
            xs, ys = zip(*pts)
            dash = g.get("dash")
            ls = {"dot": (0, (1.0, 1.8)), "dash": (0, (4.4, 2.8)),
                  "dashdot": (0, (7, 2.5, 1, 2.5))}.get(dash, "solid")
            ax.plot(xs, ys, color=col, lw=w * PT_PER_MM, ls=ls, zorder=2,
                    solid_capstyle="butt")
        elif g["type"] == "park":
            xs, ys = zip(*(pts + [pts[0]]))
            ax.plot(xs, ys, color=SILK, lw=0.15 * PT_PER_MM, zorder=2)
    # routes. A line may ask to be drawn heavier than the rest - the
    # Shinkansen is not a metro line - and a line cut off by the board edge
    # carries stubs that run on off it.
    weight = {l.id: getattr(l, "weight", 1.0) for l in city.lines}
    spans = {}
    if fan > 0:
        # The centre of the congestion is the busiest station, not the
        # middle of the board.
        deg = {}
        for lid, p1, p2, a, b in citymap.segments(city):
            deg[a] = deg.get(a, 0) + 1
            deg[b] = deg.get(b, 0) + 1
        hub = max(deg, key=deg.get) if deg and core_r > 0 else None
        hx, hy = ((city.stations[hub].x * scale, city.stations[hub].y * scale)
                  if hub else (0.0, 0.0))

        def in_core(p):
            return (core_r > 0
                    and math.hypot(p[0] * scale - hx, p[1] * scale - hy) <= core_r)

        def gap_fn(p1, p2):
            mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            return core_gap if in_core(mid) else 1.0

        routes, spans = fanning.build(city, fan, fan_gap, gap_fn)
        for lid, pts in routes:
            if len(pts) < 2:
                continue
            w = export_art.ROUTE_W * weight.get(lid, 1.0)
            if core_r <= 0:
                ax.plot([x * scale for x, _ in pts], [y * scale for _, y in pts],
                        color=SILK, lw=w * PT_PER_MM, zorder=3,
                        solid_capstyle="round", solid_joinstyle="round")
                continue
            # split at the core boundary so only the inside thins
            run, inside = [pts[0]], in_core(pts[0])
            for q in pts[1:]:
                if in_core(q) == inside:
                    run.append(q)
                    continue
                run.append(q)
                ax.plot([x * scale for x, _ in run], [y * scale for _, y in run],
                        color=SILK, lw=w * (core_w if inside else 1.0) * PT_PER_MM,
                        zorder=3, solid_capstyle="round", solid_joinstyle="round")
                run, inside = [q], not inside
            if len(run) >= 2:
                ax.plot([x * scale for x, _ in run], [y * scale for _, y in run],
                        color=SILK, lw=w * (core_w if inside else 1.0) * PT_PER_MM,
                        zorder=3, solid_capstyle="round", solid_joinstyle="round")
    else:
        for lid, p1, p2, a, b in citymap.segments(city):
            ax.plot([p1[0] * scale, p2[0] * scale], [p1[1] * scale, p2[1] * scale],
                    color=SILK,
                    lw=export_art.ROUTE_W * weight.get(lid, 1.0) * PT_PER_MM,
                    zorder=3, solid_capstyle="round")
    for line in city.lines:
        for (x0, y0), (x1, y1) in line.stubs:
            ax.plot([x0 * scale, x1 * scale], [y0 * scale, y1 * scale],
                    color=SILK, lw=export_art.ROUTE_W * line.weight * PT_PER_MM,
                    zorder=3, solid_capstyle="butt")
    # A fanned lane passes to one side of the station rather than through
    # it, so without this the track stops short either side of the pad -
    # which is exactly what it did at Ikebukuro. The tick is the bar an
    # interchange is drawn with on a real map, and it is what the lanes
    # meet.
    for sid, (ang, lo, hi) in spans.items():
        st = city.stations.get(sid)
        if st is None:
            continue
        nx, ny = -math.sin(ang), math.cos(ang)
        pad = export_art.ROUTE_W * 0.5
        ax.plot([(st.x + nx * (lo - pad)) * scale, (st.x + nx * (hi + pad)) * scale],
                [(st.y + ny * (lo - pad)) * scale, (st.y + ny * (hi + pad)) * scale],
                color=SILK, lw=export_art.ROUTE_W * PT_PER_MM, zorder=3,
                solid_capstyle="round")

    # stations: ring + pad
    for st in list(city.stations.values()) + city.extras:
        x, y = st.x * scale, st.y * scale
        r, w = ((export_art.RING_R_INT, export_art.RING_W_INT) if st.interchange
                else (export_art.RING_R, export_art.RING_W))
        ax.add_patch(Circle((x, y), r, fill=False, ec=SILK, lw=w * PT_PER_MM, zorder=4))
        ax.add_patch(plt.Rectangle((x - 0.8, y - 0.75), 1.6, 1.5, fc=GOLD, ec="none", zorder=4))
    # labels + leaders
    drawn_text = []
    for st in list(city.stations.values()) + city.extras:
        lx, ly = citymap.label_anchor(st, scale)
        text = "\n".join(citymap.display_lines(st))
        ha = {"start": "left", "end": "right"}.get(st.label["anchor"], "center")
        t = ax.text(lx, ly, text, fontsize=font_pt(citymap.TEXT_H), color=SILK,
                    rotation=-st.label["angle"], rotation_mode="anchor", ha=ha,
                    va="center", family=FONT, linespacing=LINESPACING,
                    multialignment="center", zorder=5)
        drawn_text.append((st, t))
        seg = citymap.leader_segment(st, scale)
        if seg:
            ax.plot([seg[0][0], seg[1][0]], [seg[0][1], seg[1][1]], color=SILK,
                    lw=0.15 * PT_PER_MM, zorder=5)

    # A border of clear space behind any label that crosses a route.
    # The map is white silkscreen on white silkscreen, so a name lying on a
    # line is simply gone. Cutting the LINE away behind the text is what a
    # printed map does, and on the board it is the same move: the route
    # silkscreen is knocked out, and whatever is underneath - the substrate,
    # or the bare copper of the water - shows through. That is why the halo
    # is filled per-surface rather than in one flat colour.
    if halo > 0:
        from shapely.geometry import Polygon as _Poly, LineString as _Line
        from shapely.ops import unary_union as _uu
        strokes = [
            _Line([(p1[0] * scale, p1[1] * scale), (p2[0] * scale, p2[1] * scale)])
            .buffer(export_art.ROUTE_W * weight.get(lid, 1.0) / 2 + 0.02)
            for lid, p1, p2, _a, _b in citymap.segments(city)]
        # The stubs that run off the board edge are drawn separately from
        # citymap.segments, so they were never in this union - which is why
        # the Shinkansen's stub ran straight over the capsules at Shinagawa
        # Seaside instead of being cut by them.
        for _ln in city.lines:
            for (sx0, sy0), (sx1, sy1) in _ln.stubs:
                strokes.append(_Line([(sx0 * scale, sy0 * scale),
                                      (sx1 * scale, sy1 * scale)])
                               .buffer(export_art.ROUTE_W * _ln.weight / 2 + 0.02))
        routes_geom = _uu(strokes)
        def pill(corners, pad, radius=None):
            """A capsule around a label: one corner radius, any line count.

            The radius is half a SINGLE line's height plus the border. On a
            one-line name that is half the capsule's height, so the inner
            rectangle collapses to a line and the result is a stadium. On a
            two-line name the radius stays the same instead of growing to
            half the whole block - which is what made the ends curve inward
            across the first and last lines and crowd the text in "Tokyo
            International / Cruise Terminal".

            The inner rectangle is built arithmetically rather than by a
            negative buffer: shrinking by exactly half the height yields an
            empty polygon, and the fallback drew a square-cornered box.
            """
            pts = list(corners)
            if len(pts) > 4 and pts[0] == pts[-1]:
                pts = pts[:-1]
            if len(pts) != 4:
                return _Poly(corners).buffer(pad, join_style=1)
            cx = sum(p[0] for p in pts) / 4.0
            cy = sum(p[1] for p in pts) / 4.0
            e01 = math.dist(pts[0], pts[1])
            e12 = math.dist(pts[1], pts[2])
            if e01 < 1e-9 or e12 < 1e-9:
                return _Poly(corners).buffer(pad, join_style=1)
            ux = (pts[1][0] - pts[0][0]) / e01
            uy = (pts[1][1] - pts[0][1]) / e01
            vx = (pts[2][0] - pts[1][0]) / e12
            vy = (pts[2][1] - pts[1][1]) / e12
            r = (min(e01, e12) / 2.0 + pad) if radius is None else radius
            r = max(r, pad)
            inset = r - pad                      # how far in from the text
            a = max(0.0, e01 / 2.0 - inset)
            b = max(0.0, e12 / 2.0 - inset)
            inner = [(cx + ux * sa * a + vx * sb * b,
                      cy + uy * sa * a + vy * sb * b)
                     for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            if a < 1e-9 and b < 1e-9:
                from shapely.geometry import Point as _Pt
                return _Pt(cx, cy).buffer(r)
            if b < 1e-9:
                return _Line([inner[0], inner[1]]).buffer(r, cap_style=1,
                                                          join_style=1)
            return _Poly(inner).buffer(r, join_style=1)

        # The LED pad gets the same treatment. 202 of 248 pads are more
        # than half covered by a route, and silkscreen cannot print on the
        # pad's mask opening anyway - so ink drawn across a pad is ink that
        # will not exist on the board. Cutting it is both truer and clearer.
        pad_cuts = []
        if pad_halo > 0:
            for stn in list(city.stations.values()) + city.extras:
                pad_cuts.append(_Poly([
                    (stn.x * scale - 0.8, stn.y * scale - 0.75),
                    (stn.x * scale + 0.8, stn.y * scale - 0.75),
                    (stn.x * scale + 0.8, stn.y * scale + 0.75),
                    (stn.x * scale - 0.8, stn.y * scale + 0.75),
                ]).buffer(pad_halo, join_style=1))

        # Fit the capsule to the CORE TYPE AREA of the text that was really
        # drawn, not to citymap.label_box's model of it. Two things go wrong
        # with the model: its width is an average advance per character, so
        # the slack lands on whichever end the label is anchored from; and
        # matplotlib reports one constant height for every label - the
        # font's full line box, descender space included - so a name with no
        # descender rides high in it and the capsule looks top-heavy.
        #
        # The band from baseline to cap height is what transit maps align on
        # (Cameron Booth calls it the core type area). Using it makes every
        # single-line capsule the same height whether the name has a
        # descender or not, and centres the ink in it.
        from matplotlib.textpath import TextPath as _TP
        from matplotlib.font_manager import FontProperties as _FP
        fig.canvas.draw()
        rend = fig.canvas.get_renderer()
        inv = ax.transData.inverted()
        _fp = _FP(family=FONT)
        _size = font_pt(citymap.TEXT_H)
        PT_MM = 72.0 / 25.4
        _capx = _TP((0, 0), "H", size=_size, prop=_fp).get_extents()
        cap_h = (_capx.y1 - _capx.y0) / PT_MM

        boxes, cutters = [], []
        for st, tobj in drawn_text:
            lines = citymap.display_lines(st)
            if st.label.get("angle"):
                # a rotated text's window extent is an axis-aligned box, so
                # it cannot be measured this way; fall back to the model
                corners = citymap.label_box(st, citymap.TEXT_H, scale)
            else:
                bb = tobj.get_window_extent(rend)
                (x0, y0) = inv.transform((bb.x0, bb.y0))
                (x1, y1) = inv.transform((bb.x1, bb.y1))
                lo_x, hi_x = min(x0, x1), max(x0, x1)
                mid_y = (y0 + y1) / 2.0
                ink = _TP((0, 0), max(lines, key=len), size=_size,
                          prop=_fp).get_extents()
                adv = (hi_x - lo_x) * PT_MM
                lo_x += max(0.0, ink.x0) / PT_MM          # left side bearing
                hi_x -= max(0.0, adv - ink.x1) / PT_MM    # right side bearing
                line_gap = LINESPACING * _size / PT_MM
                band = cap_h + (len(lines) - 1) * line_gap
                lo_y, hi_y = mid_y - band / 2.0, mid_y + band / 2.0
                corners = [(lo_x, lo_y), (hi_x, lo_y), (hi_x, hi_y), (lo_x, hi_y)]
            b = _Poly(corners)
            if not b.is_valid or b.area <= 0:
                continue
            pl = pill(corners, halo, radius=cap_h / 2.0 + halo)
            boxes.append(pl)
            if b.intersects(routes_geom):
                cutters.append(pl)
        if boxes:
            allcut = cutters + pad_cuts
            wet = _uu([_Poly([(x * scale, y * scale) for x, y in g["points"]]).buffer(0)
                       for g in (geo or [])
                       if g["type"] in ("water", "lake")]) if geo else None
            n = 0
            if allcut:
                union = _uu(allcut)
                # Inside a capsule everything goes: the route silkscreen AND
                # the water's mask opening. Filling with the water's gold
                # where it happened to overlap left a label sitting in a
                # yellow lozenge; the capsule should read the same wherever
                # it falls, and on the board a masked capsule is what gives
                # the white text something to print on.
                cut = union.intersection(_uu([routes_geom] + ([wet] if wet else [])))
                for g in getattr(cut, "geoms", [cut]):
                    if g.geom_type != "Polygon" or g.is_empty:
                        continue
                    pts = list(g.exterior.coords)
                    ax.add_patch(PathPatch(Path(pts, closed=True), facecolor=MASK,
                                           edgecolor="none", zorder=3.5))
                    n += 1

            # the pill's own outline, so the name reads as sitting in a
            # capsule rather than in a hole chewed out of the line
            if pill_border > 0:
                for g in boxes:
                    for q in getattr(g, "geoms", [g]):
                        if q.geom_type != "Polygon" or q.is_empty:
                            continue
                        xs, ys = zip(*q.exterior.coords)
                        ax.plot(xs, ys, color=SILK,
                                lw=pill_border * PT_PER_MM, zorder=3.6,
                                solid_capstyle="round", solid_joinstyle="round")
            print(f"  capsules on {len(boxes)} label(s); "
                  f"{len(cutters)} cut the route, {n} piece(s)"
                  + (f", outlined at {pill_border} mm" if pill_border > 0 else ""))

    for a in city.annotations:
        col = GOLD if a.get("copper") else SILK
        ha = {"center": "center", "end": "right"}.get(a.get("anchor"), "left")
        ax.text(a["x"] * scale, a["y"] * scale, a["text"], fontsize=font_pt(a.get("size", 1.4)),
                color=col, ha=ha, va="center", family=FONT, zorder=5,
                fontweight="bold" if a.get("bold") else "normal",
                rotation=-a.get("angle", 0))
    if collisions:
        for col_ in check_fit.find_collisions(city, scale):
            if col_.kind == "label-geo":
                continue
            pts = [tuple(p) for p in col_.poly]
            ax.add_patch(PathPatch(Path(pts + [pts[0]], closed=True), facecolor="#ff3030",
                                   alpha=0.45, edgecolor="#ff3030", lw=0.5, zorder=6))
    fig.savefig(out, dpi=dpi, facecolor=MASK)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--collisions", action="store_true")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--route-w", type=float, default=None, metavar="MM",
                    help="route stroke width, overriding export_art.ROUTE_W")
    ap.add_argument("--fan", type=float, default=0.0, metavar="MM",
                    help="fan shared corridors into parallel strokes. Two "
                         "segments are the same corridor when both ends "
                         "agree to within this distance")
    ap.add_argument("--fan-gap", type=float, default=0.8, metavar="MM",
                    help="centre-to-centre spacing of the fanned strokes")
    ap.add_argument("--wrap-over", type=int, default=None, metavar="N",
                    help="set a name on two lines past N characters. It is "
                         "a RENDER-time property - the data file stores no "
                         "wrap - so this has to match whatever auto_label "
                         "was run with, or the labels are drawn in boxes "
                         "they were not placed for")
    ap.add_argument("--halo", type=float, default=citymap.LABEL_HALO,
                    metavar="MM",
                    help="knock the route silkscreen out behind any label "
                         "that crosses it, leaving this much clear border. "
                         "White text on a white line is unreadable; cutting "
                         "the line is what a printed map does")
    ap.add_argument("--pad-halo", type=float, default=0.0, metavar="MM",
                    help="knock the route silkscreen out around each LED "
                         "pad, leaving this much clear. Silkscreen will not "
                         "print over the pad's mask opening, so a route "
                         "drawn across a pad is ink the board will not have")
    ap.add_argument("--pill-border", type=float, default=0.0, metavar="MM",
                    help="draw the pill's own outline at this width, so the "
                         "name reads as sitting in a capsule rather than in "
                         "a hole chewed out of the route")
    ap.add_argument("--core-radius", type=float, default=0.0, metavar="MM",
                    help="radius of the congested centre, about the busiest "
                         "station. Inside it the stroke and the lane pitch "
                         "both shrink")
    ap.add_argument("--core-w", type=float, default=0.35, metavar="F",
                    help="stroke width inside the core, as a fraction")
    ap.add_argument("--core-gap", type=float, default=0.40, metavar="F",
                    help="lane pitch inside the core, as a fraction. It has "
                         "to shrink with the stroke: thinning the line and "
                         "leaving the pitch alone keeps the band exactly as "
                         "wide, only fainter")
    args = ap.parse_args()
    if args.wrap_over:
        citymap.WRAP_OVER = args.wrap_over
    if args.route_w is not None:
        export_art.ROUTE_W = args.route_w
    city = citymap.load(args.data)
    render(city, args.scale, args.out, args.collisions, args.dpi,
           fan=args.fan, fan_gap=args.fan_gap, core_r=args.core_radius,
           core_w=args.core_w, core_gap=args.core_gap, halo=args.halo,
           pill_border=args.pill_border,
           pad_halo=args.pad_halo)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
