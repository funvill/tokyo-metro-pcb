"""The capsule behind every station label - one definition, two consumers.

preview_map draws these and export_art etches them, and when the two had
their own idea of the shape the optimiser spent a long time solving a board
nobody was drawing. The halo has been 0.12 while the render used 0.26; the
line spacing has been 1.76 while the render used 1.71; the collision check
scored a bare text box while the drawing had a capsule round it. All of
those were the same bug wearing different clothes, so the geometry lives
here and both callers import it.

A capsule is a rounded rectangle whose corner radius is half a SINGLE
line's cap height plus the border, whatever the line count. On a one-line
name that equals half the capsule's height, so it degenerates into a
stadium. On a two-line name the radius stays the same rather than growing
to half the whole block - which would curve the ends inward across the
first and last lines and crowd the text.
"""
import math
import os

from shapely.geometry import LineString, Point, Polygon

import citymap

LINESPACING = 1.15      # as preview_map draws multi-line text
_CAP_H = None


def _font_pt(size_mm):
    return size_mm * (72.0 / 25.4) * 1.35


def cap_height(text_h=None):
    """Baseline-to-cap-height of the label face, in mm.

    The core type area: aligning on it rather than on the font's full line
    box is what stops a name without a descender riding high in its
    capsule.
    """
    global _CAP_H
    text_h = citymap.TEXT_H if text_h is None else text_h
    if _CAP_H is None:
        try:
            from matplotlib.textpath import TextPath
            from matplotlib.font_manager import FontProperties
            ttf = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "fonts", "ArchivoNarrow-SemiBold.ttf")
            ext = TextPath((0, 0), "H", size=_font_pt(text_h),
                           prop=FontProperties(fname=ttf)).get_extents()
            _CAP_H = (ext.y1 - ext.y0) / (72.0 / 25.4)
        except Exception:
            _CAP_H = text_h * 0.93        # measured value, as a fallback
    return _CAP_H


def text_box(st, scale, text_h=None):
    """The label's core type area in board mm, as four corners.

    Width comes from citymap.text_width, which measures the real face;
    height is one cap band per line plus the pitch between them.
    """
    text_h = citymap.TEXT_H if text_h is None else text_h
    lines = citymap.display_lines(st)
    w = max(citymap.text_width(t, text_h) for t in lines)
    gap = LINESPACING * _font_pt(text_h) / (72.0 / 25.4)
    h = cap_height(text_h) + (len(lines) - 1) * gap
    ang = math.radians(st.label["angle"])
    d = (math.cos(ang), math.sin(ang))
    n = (math.sin(ang), -math.cos(ang))
    px, py = citymap.label_anchor(st, scale)
    anchor = st.label.get("anchor", "start")
    if anchor == "end":
        px -= d[0] * w
        py -= d[1] * w
    elif anchor in ("center", "middle"):
        px -= d[0] * w / 2
        py -= d[1] * w / 2
    lo, hi = -h / 2, h / 2
    return [
        (px + n[0] * lo, py + n[1] * lo),
        (px + d[0] * w + n[0] * lo, py + d[1] * w + n[1] * lo),
        (px + d[0] * w + n[0] * hi, py + d[1] * w + n[1] * hi),
        (px + n[0] * hi, py + n[1] * hi),
    ]


def pill(corners, pad, radius=None):
    """A rounded rectangle around `corners`, grown by `pad`.

    The inner rectangle is built arithmetically: a negative buffer goes
    empty when the shrink equals half the height, which is exactly the
    one-line case, and the fallback then draws square corners.
    """
    pts = list(corners)
    if len(pts) > 4 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) != 4:
        return Polygon(corners).buffer(pad, join_style=1)
    cx = sum(p[0] for p in pts) / 4.0
    cy = sum(p[1] for p in pts) / 4.0
    e01 = math.dist(pts[0], pts[1])
    e12 = math.dist(pts[1], pts[2])
    if e01 < 1e-9 or e12 < 1e-9:
        return Polygon(corners).buffer(pad, join_style=1)
    ux, uy = (pts[1][0] - pts[0][0]) / e01, (pts[1][1] - pts[0][1]) / e01
    vx, vy = (pts[2][0] - pts[1][0]) / e12, (pts[2][1] - pts[1][1]) / e12
    r = (min(e01, e12) / 2.0 + pad) if radius is None else radius
    r = max(r, pad)
    inset = r - pad
    a = max(0.0, e01 / 2.0 - inset)
    b = max(0.0, e12 / 2.0 - inset)
    inner = [(cx + ux * sa * a + vx * sb * b, cy + uy * sa * a + vy * sb * b)
             for sa, sb in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    if a < 1e-9 and b < 1e-9:
        return Point(cx, cy).buffer(r)
    if b < 1e-9:
        return LineString([inner[0], inner[1]]).buffer(r, cap_style=1,
                                                       join_style=1)
    return Polygon(inner).buffer(r, join_style=1)


def label_capsule(st, scale, halo=None, text_h=None):
    """The capsule drawn behind one station's label."""
    halo = citymap.LABEL_HALO if halo is None else halo
    text_h = citymap.TEXT_H if text_h is None else text_h
    return pill(text_box(st, scale, text_h), halo,
                radius=cap_height(text_h) / 2.0 + halo)


def all_capsules(city, scale, halo=None, text_h=None):
    out = {}
    for st in list(city.stations.values()) + city.extras:
        out[st.id] = label_capsule(st, scale, halo, text_h)
    return out


def pad_keepouts(city, scale, clear):
    """A box round every LED pad, grown by `clear`.

    Silkscreen will not print on the pad's mask opening, so a route drawn
    across a pad is ink the board will not have; cutting it is truer as
    well as clearer.
    """
    out = []
    for st in list(city.stations.values()) + city.extras:
        x, y = st.x * scale, st.y * scale
        out.append(Polygon([(x - 0.8, y - 0.75), (x + 0.8, y - 0.75),
                            (x + 0.8, y + 0.75), (x - 0.8, y + 0.75)])
                   .buffer(clear, join_style=1))
    return out
