"""Generate PCB artwork (station labels + land/water shapes) and inject it
into the KiCad board.

Water technique (see v1/input/natrual/natrual/map.kicad_pcb): a filled
polygon on F.Cu *and* a matching filled polygon on F.Mask, same outline.
The mask opening exposes the copper underneath, so water reads as bare
copper (gold with ENIG) against the black soldermask everywhere else -
the board substrate itself stands in for "land", so land needs no fill,
only an outline where its boundary isn't a coastline (parks, river
islands) drawn as thin F.SilkS strokes.

Station names are gr_text on F.SilkS, positioned/rotated the same way as
the SVG preview (citymap.label_box's placement math), white ink being the
only ink silkscreen has.

Regeneration is idempotent: every block this script writes is recorded by
uuid in <pcb>.art-manifest.json; on the next run those uuids are stripped
before new ones are appended, so re-running after an edit to vancouver.json
never leaves stale or duplicate art behind.

Usage:
    python export_art.py ../input/vancouver.json ../hardware/vancouver-skytrain-pcb.kicad_pcb --scale 1.5
"""
import argparse
import json
import math
import os
import re
import uuid

import citymap
import reposition_board as rb

ART_NAMESPACE = uuid.UUID("6f1b0b1a-b1a1-4a7a-9a1a-76616e636f75")  # fixed, arbitrary
TEXT_H = citymap.TEXT_H
TEXT_THICKNESS = 0.14  # ~1:8 keeps the stroke font's counters open
ROUTE_W = 1.0          # route stroke - one style for every segment, built
                       # or not, and slimmer than the station rings
# Silk ring behind every station LED, and a heavier one at interchanges.
#
# Watch the LED footprint when changing these: the XL-1615's four pads reach
# 1.15 mm from the part centre, so a ring inside that radius is under the
# pads and the body - and silkscreen cannot print on a solder-mask opening
# anyway (lesson A6), so it would be clipped away rather than merely hidden.
# 1.33 mm is the smallest radius that clears the pads with a 0.25 mm stroke.
# Halved to 0.63/0.15 on 2026-10-18, which put the whole ring INSIDE the
# pads' mask openings: 60.7% of all 248 rings' ink was on an opening, so
# the fab would have clipped each one into four arcs with four gaps. The
# warning above had been there the whole time. Back to a radius that
# clears, 2026-10-20.
# The binding constraint is the CORNER of a pad's mask opening, 1.4407 mm
# from the part centre - not the 1.15 mm pad reach the note above quotes,
# and not the 1.20 mm the opening reaches along x. The ring's INNER edge
# has to clear that corner, so R - W/2 > 1.4407: at the old "1.33 clears"
# figure 15% of the ink was still being clipped. 1.65 leaves 0.08 mm.
RING_R, RING_W = 1.65, 0.25
RING_R_INT, RING_W_INT = 1.90, 0.30
DASH_STYLES = {  # (dash, gap) in mm for "line" geo and future routes
    "dash": (2.2, 1.4),
    "dot": (0.5, 0.9),
    "dashdot": None,  # handled specially: long dash, gap, dot, gap
}
LABEL_FACE = "Archivo Narrow SemiBold"
CAPSULE_BORDER = 0.12  # the capsule outline stroke
# KiCad renders this as an outline font and plots the glyph outlines into
# the gerbers, so the fab needs nothing - but whoever plots them does. The
# font is embedded in the board (board.EmbedFonts) so it travels with the
# file instead of depending on what is installed.
PAD_SILK_CLEAR = 0.06  # silk kept just off the pad: enough that it is
                       # not ON the mask opening, no more. The old 0.18
                       # plus half a stroke read as a gap round every LED.
# The water's F.Mask opening has to keep a mask dam away from every LED
# pad, or the pad's own opening and the water's merge into one aperture
# with two nets exposed in it - bare pour and a pad, or a +5V pad and a
# GND pad 3.5 mm apart with nothing but bare copper between them. Solder
# follows that during assembly. KiCad reports it as solder_mask_bridge,
# which this project had set to "ignore". 0.05 is the board's pad mask
# expansion, 0.1 is JLCPCB's minimum dam.
MASK_DAM_CLEAR = 0.15
# The LED footprint's silkscreen pin-1 dot, at footprint-local (-1.5, 0.45)
# beside pad 1, with ink reaching 0.255 mm from its centre (0.13 radius +
# half of a 0.25 stroke). It is the only thing on the board that says which
# way round the part goes, and pads 1 and 4 share a side, so a part fitted
# 180 degrees out swaps GND with DI and +5V with DO. The map's routes and
# the station ring are white silk too, so without a gap round it the mark
# is just more ink. DOT_CLEAR is how much bare board to leave round it.
DOT_LOCAL = (-1.5, 0.45)
DOT_INK_R = 0.255
DOT_CLEAR = 0.18
RIVER_MITRE = 1.0  # extra length added at each river segment end, to close gaps
# citymap.repel() only pushes vertices, not the edges between them, so two
# adjacent vertices each individually clear of a station can still bound an
# edge that swings back close to it - a real risk where several stations
# sit only a few mm apart (e.g. the Expo diagonal crossing the Fraser).
# Any river rectangle whose corner still ends up under this floor is
# dropped rather than emitted too close to call safe; the gap reads as a
# bridge crossing, which is accurate anyway.
RIVER_SAFE_FLOOR = 1.5


KEYS = {}   # uuid -> key, for the manifest and for suppression by key


def art_uuid(key):
    u = str(uuid.uuid5(ART_NAMESPACE, key))
    KEYS[u] = key
    return u


def poly_block(kind, points, layer, fill, key, width=0.1):
    pts = " ".join(f"(xy {x:.3f} {y:.3f})" for x, y in points)
    return (f"({kind}\n\t\t(pts\n\t\t\t{pts}\n\t\t)\n\t\t(stroke\n\t\t\t"
            f"(width {width})\n\t\t\t(type default)\n\t\t)\n\t\t"
            f"(fill {'yes' if fill else 'no'})\n\t\t(layer \"{layer}\")\n\t\t"
            f"(uuid \"{art_uuid(key)}\")\n\t)")


def line_block(p1, p2, layer, key, width=1.0):
    return (f"(gr_line\n\t\t(start {p1[0]:.3f} {p1[1]:.3f})\n\t\t"
            f"(end {p2[0]:.3f} {p2[1]:.3f})\n\t\t(stroke\n\t\t\t"
            f"(width {width})\n\t\t\t(type solid)\n\t\t)\n\t\t"
            f"(layer \"{layer}\")\n\t\t(uuid \"{art_uuid(key)}\")\n\t)")


def dash_points(p1, p2, dash=2.2, gap=1.4):
    """(a, b) endpoint pairs for real physical dashes along p1->p2 - a
    stroke "line style" of dash/dot is a KiCad editor display hint only
    and is dropped on plot/fab/3D-render output, so a genuinely dashed
    silkscreen line has to be built from real solid segments with gaps."""
    ln = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if ln < 1e-6:
        return []
    ux, uy = (p2[0] - p1[0]) / ln, (p2[1] - p1[1]) / ln
    period = dash + gap
    out = []
    d = 0.0
    while d < ln:
        a = (p1[0] + ux * d, p1[1] + uy * d)
        end = min(d + dash, ln)
        b = (p1[0] + ux * end, p1[1] + uy * end)
        out.append((a, b))
        d += period
    return out


def circle_block(cx, cy, r, layer, key, width):
    return (f"(gr_circle\n\t\t(center {cx:.3f} {cy:.3f})\n\t\t"
            f"(end {cx + r:.3f} {cy:.3f})\n\t\t(stroke\n\t\t\t"
            f"(width {width})\n\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n\t\t"
            f"(layer \"{layer}\")\n\t\t(uuid \"{art_uuid(key)}\")\n\t)")


def dashdot_points(p1, p2, dash=3.0, dot=0.4, gap=1.0):
    """Long dash, gap, dot, gap - the cartographic international border."""
    ln = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
    if ln < 1e-6:
        return []
    ux, uy = (p2[0] - p1[0]) / ln, (p2[1] - p1[1]) / ln
    out, d = [], 0.0
    while d < ln:
        for seg in (dash, dot):
            if d >= ln:
                break
            end = min(d + seg, ln)
            out.append(((p1[0] + ux * d, p1[1] + uy * d),
                        (p1[0] + ux * end, p1[1] + uy * end)))
            d = end + gap
    return out


def styled_line_blocks(p1, p2, layer, key, width, dash=None):
    """One solid gr_line, or a run of real short segments for a dashed /
    dotted / dash-dot style (stroke line styles don't survive to fab)."""
    if not dash:
        return [line_block(p1, p2, layer, key, width=width)]
    if dash == "dashdot":
        pairs = dashdot_points(p1, p2)
    else:
        pairs = dash_points(p1, p2, *DASH_STYLES[dash])
    return [line_block(a, b, layer, f"{key}:{j}", width=width)
            for j, (a, b) in enumerate(pairs)]


def text_block(text, x, y, angle, anchor, layer, key, size=None, bold=False):
    justify = ""
    if anchor == "start":
        justify = "\n\t\t\t(justify left)"
    elif anchor == "end":
        justify = "\n\t\t\t(justify right)"
    text = text.replace('"', "'").replace("\n", "\\n")
    h = size if size is not None else TEXT_H
    ratio = 0.22 if bold else TEXT_THICKNESS / TEXT_H
    thickness = max(0.12, h * ratio)
    return (f'(gr_text "{text}"\n\t\t(at {x:.3f} {y:.3f} {angle % 360:.1f})\n'
            f'\t\t(layer "{layer}")\n\t\t(uuid "{art_uuid(key)}")\n\t\t'
            f'(effects\n\t\t\t(font\n\t\t\t\t(face "{LABEL_FACE}")\n'
            f'\t\t\t\t(size {h} {h})\n'
            f'\t\t\t\t(thickness {thickness:.3f})\n\t\t\t){justify}\n\t\t)\n\t)')


def avoid_points(city, scale):
    return [(st.x * scale, st.y * scale)
            for st in list(city.stations.values()) + city.extras]


def water_blocks(city, scale, geo=None, mask_cut=None):
    """One F.Cu + one F.Mask filled polygon per water/lake shape, and a
    chain of mitred rectangles for river/linear water. Shapes are already
    repelled from LED pads and inset from the board edge by
    citymap.prepared_geo, so the copper stays DRC-clean.

    `mask_cut` is subtracted from the F.Mask polygon only - the label
    capsules. The water reads as bare copper because its mask OPENING
    exposes it, so a capsule sitting on the water showed gold inside.
    Taking the capsule out of the opening leaves solder mask over that
    patch: the copper is still there, covered, and the capsule reads the
    same green as everywhere else. The F.Cu polygon is left alone - there
    is nothing to gain by removing copper nobody can see."""
    geo = geo if geo is not None else citymap.prepared_geo(
        city, scale, avoid_points(city, scale))
    avoid = avoid_points(city, scale)
    blocks = []
    dropped = []
    for g in geo:
        pts = g["points"]
        if g["type"] in ("water", "lake"):
            blocks.append(poly_block("gr_poly", pts, "F.Cu", True,
                                     f"water:{g['name']}:F.Cu"))
            if mask_cut is None:
                blocks.append(poly_block("gr_poly", pts, "F.Mask", True,
                                         f"water:{g['name']}:F.Mask"))
            else:
                from shapely.geometry import Polygon as _P
                opening = _P(pts).buffer(0).difference(mask_cut)
                for k, piece in enumerate(getattr(opening, "geoms", [opening])):
                    if piece.geom_type != "Polygon" or piece.is_empty:
                        continue
                    blocks.append(poly_block(
                        "gr_poly", _with_holes(piece), "F.Mask", True,
                        f"water:{g['name']}:F.Mask:{k}"))
        elif g["type"] == "river":
            half = g.get("width", 2.5) * scale / 2
            for i, (p1, p2) in enumerate(zip(pts, pts[1:])):
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                ln = math.hypot(dx, dy) or 1.0
                ux, uy = dx / ln * RIVER_MITRE, dy / ln * RIVER_MITRE
                a = (p1[0] - ux, p1[1] - uy)
                b = (p2[0] + ux, p2[1] + uy)
                rect = citymap.seg_rect(a, b, half)
                rect = citymap.clamp_to_board(rect, city.canvas_mm * scale,
                                              citymap.EDGE_MARGIN,
                                              city.height * scale)
                closest = min(citymap.poly_point_min_dist(rect, pt)
                             for pt in avoid)
                if closest < RIVER_SAFE_FLOOR:
                    dropped.append((g["name"], i, closest))
                    continue
                for layer in ("F.Cu", "F.Mask"):
                    blocks.append(poly_block(
                        "gr_poly", rect, layer, True,
                        f"river:{g['name']}:{i}:{layer}"))
    if dropped:
        print(f"  dropped {len(dropped)} river segment(s) too close to an "
              f"LED to route safely (reads as a bridge crossing):")
        for name, i, d in dropped:
            print(f"    {name}[{i}]  closest LED {d:.2f}mm "
                  f"(floor {RIVER_SAFE_FLOOR}mm)")
    return blocks


PARK_HATCH_SPACING = 1.6  # mm between hatch lines, matched to the 150mm board


def land_outline_blocks(city, scale, geo=None):
    """Islands: thin white silkscreen outline only (no fill - the board
    substrate itself is the land). Parks: outline + a diagonal hatch fill,
    the single-ink stand-in for the reference map's solid green park areas
    (see TransLink's Future Rapid Transit Network map)."""
    geo = geo if geo is not None else citymap.prepared_geo(
        city, scale, avoid_points(city, scale))
    blocks = []
    for g in geo:
        if g["type"] == "line":
            pts = g["points"]
            # copper hairlines (city boundaries) expose like the water:
            # the same stroke on F.Cu and on F.Mask
            layers = ("F.Cu", "F.Mask") if g.get("copper") else ("F.SilkS",)
            for layer in layers:
                for i, (p1, p2) in enumerate(zip(pts, pts[1:])):
                    blocks += styled_line_blocks(
                        p1, p2, layer, f"line:{g['name']}:{i}:{layer}",
                        g.get("width", 0.3), g.get("dash"))
            continue
        if g["type"] not in ("island", "park"):
            continue
        blocks.append(poly_block("gr_poly", g["points"], "F.SilkS", False,
                                 f"land:{g['name']}", width=0.15))
        if g["type"] == "park":
            hatch = citymap.hatch_fill(g["points"], PARK_HATCH_SPACING)
            for i, (a, b) in enumerate(hatch):
                blocks.append(line_block(a, b, "F.SilkS",
                                         f"hatch:{g['name']}:{i}", width=0.12))
    return blocks


def route_blocks(city, scale, keepouts=None):
    """The transit lines, as filled F.SilkS polygons with the elements cut
    out of them.

    The strokes are unioned into one shape and the keepouts - the label
    capsules and the LED pads - are subtracted from it. That is a solid
    line with a hole in it, which is what the map wants.

    Cutting the CENTRE LINE instead and drawing thick segments does not
    give that. A centre line trimmed to clear a capsule stops half a
    stroke width short of it, and KiCad draws the segment end flush, so
    every element ended up ringed by a visible gap - about 0.5 mm at a
    0.75 mm stroke. Unioning also removes the seams between consecutive
    segments, so a line reads as one stroke rather than a chain of them.
    """
    from shapely.geometry import LineString as _L
    from shapely.ops import unary_union as _uu
    weight = {l.id: getattr(l, "weight", 1.0) for l in city.lines}
    strokes = []
    for line_id, p1, p2, a, b in citymap.segments(city):
        p1s = (p1[0] * scale, p1[1] * scale)
        p2s = (p2[0] * scale, p2[1] * scale)
        if p1s == p2s:
            continue
        w = ROUTE_W * weight.get(line_id, 1.0)
        strokes.append(_L([p1s, p2s]).buffer(w / 2.0, cap_style=1,
                                             join_style=1, resolution=8))
    for line in city.lines:
        for (x0, y0), (x1, y1) in line.stubs:
            strokes.append(_L([(x0 * scale, y0 * scale),
                               (x1 * scale, y1 * scale)])
                           .buffer(ROUTE_W * line.weight / 2.0, cap_style=1,
                                   join_style=1, resolution=8))
    if not strokes:
        return []
    shape = _uu(strokes)
    if keepouts is not None:
        shape = shape.difference(keepouts)
    blocks = []
    for i, g in enumerate(getattr(shape, "geoms", [shape])):
        if g.geom_type != "Polygon" or g.is_empty or g.area < 0.004:
            continue
        # A hole is emitted as its own filled polygon on the mask-away
        # layer? No - gr_poly has one ring, so a ring with holes is cut
        # open along a seam to the nearest point on the hole.
        ring = _with_holes(g)
        blocks.append(poly_block("gr_poly", ring, "F.SilkS", True,
                                 f"route:{i}", width=0.01))
    return blocks


def _with_holes(poly):
    """A single point list for a polygon that may have holes.

    gr_poly carries one ring, so each hole is bridged into the outer ring
    by a seam: out to the hole, round it, and back. The seam is the width
    of nothing, so it does not print.
    """
    pts = list(poly.exterior.coords)
    for interior in poly.interiors:
        hole = list(interior.coords)
        # join at the closest pair of points
        best = None
        for i, a in enumerate(pts):
            for j, b in enumerate(hole):
                d = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                if best is None or d < best[0]:
                    best = (d, i, j)
        _, i, j = best
        bridged = hole[j:] + hole[:j + 1]
        pts = pts[:i + 1] + bridged + pts[i:]
    return pts


def pin1_dots(pcb_path):
    """Every LED's silkscreen pin-1 dot, in board mm, read from the board.

    The dot lives in the footprint at local (-1.5, 0.45) - beside pad 1 -
    so where it lands depends on the part's rotation, and the LEDs sit at
    eight different ones. KiCad's y runs down, so a footprint's local point
    maps to the board through -rot.
    """
    with open(pcb_path, encoding="utf-8") as f:
        src = f.read()
    out = []
    for blk in src.split("\n\t(footprint ")[1:]:
        ref = re.search(r'\(property "Reference" "(LED\d+)"', blk)
        at = re.search(r"\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)", blk)
        if not (ref and at):
            continue
        cx, cy = float(at.group(1)), float(at.group(2))
        th = math.radians(-float(at.group(3) or 0.0))
        lx, ly = DOT_LOCAL
        out.append((cx + lx * math.cos(th) - ly * math.sin(th),
                    cy + lx * math.sin(th) + ly * math.cos(th)))
    return out


def station_ring_blocks(city, scale, dot_cuts=None):
    """A white silk ring behind every LED so a station reads as the classic
    circle-on-line marker rather than a bare pad interrupting the route;
    interchanges get a visibly heavier ring.

    The ring is drawn as a filled annulus rather than a stroked circle so
    the pin-1 dot can be cut out of it. At RING_R = 1.65 the ring's band
    runs straight through the dot's ink, which left the polarity mark as
    one more white blob in a field of white - on every LED, and invisible
    on three. A notch in the ring puts bare board round the dot, so the
    ring still reads as a circle and the mark reads as a mark.
    """
    blocks = []
    for st in list(city.stations.values()) + city.extras:
        r, w = (RING_R_INT, RING_W_INT) if st.interchange else (RING_R, RING_W)
        from shapely.geometry import Point as _Pt
        c = _Pt(st.x * scale, st.y * scale)
        ring = c.buffer(r + w / 2.0, resolution=24).difference(
            c.buffer(r - w / 2.0, resolution=24))
        if dot_cuts is not None:
            ring = ring.difference(dot_cuts)
        for i, g in enumerate(getattr(ring, "geoms", [ring])):
            if g.geom_type != "Polygon" or g.is_empty or g.area < 0.002:
                continue
            blocks.append(poly_block("gr_poly", _with_holes(g), "F.SilkS",
                                     True, f"ring:{st.id}:{i}", width=0.01))
    return blocks


def annotation_blocks(city, scale):
    """River/municipality context labels (vancouver.json's "annotations"
    list) - the equivalent of the reference map's small gray place names
    and "NORTH ARM FRASER RIVER" style water labels."""
    blocks = []
    for i, a in enumerate(city.annotations):
        x, y = a["x"] * scale, a["y"] * scale
        # "copper": exposed-copper lettering (F.Cu + matching F.Mask opening,
        # the same trick as the water) - the wordmark, gold with ENIG.
        layers = ("F.Cu", "F.Mask") if a.get("copper") else ("F.SilkS",)
        for layer in layers:
            blocks.append(text_block(
                a["text"], x, y, a.get("angle", 0), a.get("anchor", "start"),
                layer, f"annotation:{i}:{a['text']}:{layer}",
                size=a.get("size", 1.4), bold=a.get("bold", False)))
    return blocks


def label_blocks(city, scale):
    blocks = []
    for st in list(city.stations.values()) + city.extras:
        x, y = citymap.label_anchor(st, scale)
        blocks.append(text_block(citymap.display_name(st), x, y, -st.label["angle"],
                                 st.label["anchor"], "F.SilkS",
                                 f"label:{st.id}"))
        seg = citymap.leader_segment(st, scale, pad_r=RING_R + RING_W / 2.0)
        if not seg:
            continue
        # Clip the leader where it meets the capsule. Drawn to the anchor it
        # carries on under the text - the anchor is the text ORIGIN, inside
        # the capsule, not its edge - so the hairline crossed the first
        # glyphs. Cut it at the capsule's outer border and keep the piece on
        # the LED's side.
        import capsules as _caps
        from shapely.geometry import LineString as _LS, Point as _Pt
        cap = _caps.label_capsule(st, scale).buffer(CAPSULE_BORDER / 2.0)
        line = _LS([seg[0], seg[1]]).difference(cap)
        here = _Pt(st.x * scale, st.y * scale)
        parts = [g for g in getattr(line, "geoms", [line])
                 if g.geom_type == "LineString" and not g.is_empty]
        if not parts:
            continue
        keep = min(parts, key=lambda g: g.distance(here))
        if keep.length < 0.2:         # nothing worth drawing
            continue
        a, b = keep.coords[0], keep.coords[-1]
        blocks.append(line_block(a, b, "F.SilkS",
                                 f"leader:{st.id}", width=0.15))
    return blocks


def load_manifest(path):
    """{uuid: key} of the blocks the last run wrote (older manifests were a
    bare uuid list - accepted, keys unknown)."""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {u: None for u in m}
    return {}


def save_manifest(path, uuid_keys):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(uuid_keys.items())), f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("pcb")
    ap.add_argument("--scale", type=float, default=None,
                    help="board mm per canvas unit; taken from the data "
                         "file's board_scale when omitted. It used to "
                         "default to 1.5 while the board is 2.0, so a run "
                         "that forgot the flag wrote every shape at 0.75x")
    args = ap.parse_args()
    city = citymap.load(args.data)
    if args.scale is None:
        args.scale = city.scale
    geo = citymap.prepared_geo(city, args.scale, avoid_points(city, args.scale))
    # What the silkscreen must keep clear of: the capsule behind every
    # station name, and every LED pad. The capsule geometry is imported
    # rather than restated - preview_map uses the same module, and every
    # time the two have had their own copy they have drifted apart.
    import capsules
    from shapely.ops import unary_union as _uu
    caps = list(capsules.all_capsules(city, args.scale).values())
    water = water_blocks(city, args.scale, geo,
                         mask_cut=_uu([c.buffer(CAPSULE_BORDER / 2.0)
                                       for c in caps]
                                      + capsules.pad_keepouts(
                                          city, args.scale, MASK_DAM_CLEAR)))
    # The pin-1 dots come from the BOARD, not from leds.csv: the dot's
    # place depends on the part's rotation and the board is the only file
    # that is certainly in step with the footprints as placed.
    from shapely.geometry import Point as _Pt
    dot_cuts = _uu([_Pt(x, y).buffer(DOT_INK_R + DOT_CLEAR, resolution=16)
                    for x, y in pin1_dots(args.pcb)])
    keepouts = _uu([c.buffer(CAPSULE_BORDER / 2.0) for c in caps]
                   + capsules.pad_keepouts(city, args.scale, PAD_SILK_CLEAR)
                   + [dot_cuts])
    routes = (route_blocks(city, args.scale, keepouts)
              + station_ring_blocks(city, args.scale, dot_cuts))

    # The capsule outline itself. It was being computed as a keepout and
    # never drawn, so the board had the cleared space but no border round
    # it. One closed polyline per capsule, unfilled.
    capsule_blocks = []
    for sid, cap in capsules.all_capsules(city, args.scale).items():
        for g in getattr(cap, "geoms", [cap]):
            if g.geom_type != "Polygon" or g.is_empty:
                continue
            pts = [(x, y) for x, y in g.exterior.coords]
            capsule_blocks.append(poly_block("gr_poly", pts, "F.SilkS", False,
                                             f"capsule:{sid}",
                                             width=CAPSULE_BORDER))
    routes += capsule_blocks
    land = land_outline_blocks(city, args.scale, geo)
    labels = label_blocks(city, args.scale)
    annotations = annotation_blocks(city, args.scale)
    blocks = water + routes + land + labels + annotations

    # art deleted by hand in KiCad (recorded by import_labels.py as keys in
    # vancouver.json "suppressed_art") is not regenerated
    with open(args.data, encoding="utf-8") as f:
        suppressed = set(json.load(f).get("suppressed_art", []))

    def block_uuid(b):
        i = b.index('(uuid "') + 7
        return b[i: b.index('"', i)]

    blocks = [b for b in blocks if KEYS.get(block_uuid(b)) not in suppressed]
    new_manifest = {block_uuid(b): KEYS.get(block_uuid(b)) for b in blocks}

    manifest_path = args.pcb + ".art-manifest.json"
    old_uuids = set(load_manifest(manifest_path))

    with open(args.pcb, encoding="utf-8") as f:
        text = f.read()
    header, top_blocks, footer = rb.split_top_blocks(text)
    kept = [b for b in top_blocks if not any(
        f'(uuid "{u}")' in b for u in old_uuids)]

    body = "\t" + "\n\t".join(kept + blocks) + "\n"
    with open(args.pcb, "w", encoding="utf-8", newline="\n") as f:
        f.write(header + body + footer)
    save_manifest(manifest_path, new_manifest)
    print(f"removed {len(top_blocks) - len(kept)} stale art block(s), "
          f"wrote {len(blocks)} art block(s) "
          f"({len(water)} water, {len(routes)} route segments, "
          f"{len(land)} land outline/hatch, {len(labels)} labels, "
          f"{len(annotations)} annotations"
          f"{f', {len(suppressed)} suppressed by hand' if suppressed else ''})")


if __name__ == "__main__":
    main()
