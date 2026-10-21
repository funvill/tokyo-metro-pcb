"""Text-fit / collision checker for the LED map.

Models every station label as a rotated rectangle and reports collisions:
  label vs label, label vs other station's LED dot, label vs route segments
  (excluding segments that touch the label's own station), label off-board.

Usage:
    python check_fit.py ../input/vancouver.json           # full matrix
    python check_fit.py ../input/vancouver.json --scale 1.0 --text 1.2
"""
import argparse
import math
from dataclasses import dataclass

import citymap

EDGE_MARGIN = 1.0  # labels must stay this far inside the board edge
CAPSULE_GAP = 0.25   # capsules must not even touch: two outlines
                     # meeting reads as a drawing error, so this
                     # is clear space between them, on top of the
                     # border each one already carries
CAPSULE_HALO = citymap.LABEL_HALO  # the clear border drawn around every label. The label
                     # is not bare text on the board: it sits in a capsule,
                     # and the capsule is what can collide. Scoring the bare
                     # box let Kajiwara and Arakawa-shakomae pass as clean
                     # while their capsules plainly overlapped.
DOT_R = 1.1
OWN_R = 1.3        # own LED + ring. Calibrated to the 2026-10-13 hand pass: labels are tucked this close
LEADER_DOT_R = 2.8 # a leader-floated label keeps this far from other LEDs
LABEL_GAP = 0.4    # breathing room between any two labels, mm


def inflate(poly, d):
    """Grow a 4-point box by d PERPENDICULAR to each edge.

    Pushing the corners radially out from the centre instead - which this
    did, with a 1.4 fudge factor trying to make up for it - barely grows a
    long thin box across its short axis, because the corner vectors point
    almost entirely along the length. Station labels are long thin boxes,
    and the pairs that collide are usually stacked vertically: Higashi-ogu-
    sanchome and Machiya-ekimae sit 0.44 mm apart and a nominal 1.17 mm of
    inflation did not reach.
    """
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = poly[:4]
    ex, ey = x1 - x0, y1 - y0
    n = math.hypot(ex, ey) or 1.0
    ux, uy = ex / n * d, ey / n * d
    fx, fy = x3 - x0, y3 - y0
    m = math.hypot(fx, fy) or 1.0
    vx, vy = fx / m * d, fy / m * d
    return [
        (x0 - ux - vx, y0 - uy - vy),
        (x1 + ux - vx, y1 + uy - vy),
        (x2 + ux + vx, y2 + uy + vy),
        (x3 - ux + vx, y3 - uy + vy),
    ]
LINE_HALF_W = 0.75  # half the route stroke, no extra margin: the hand pass puts text right against its line


@dataclass
class Collision:
    kind: str      # label-label | label-line | label-dot | off-board
    a: str
    b: str
    poly: list     # polygon of offending label (for overlay rendering)


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _hits(a, b):
    """Do two bounding boxes overlap?"""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


class GeoIndex:
    """A polygon's edges on a coarse grid, so a label box only tests the
    edges near it.

    The water is the expensive obstacle: Tokyo Bay alone is thousands of
    points, and `box_poly_overlap` walks every one of them for every
    candidate placement of every label - 80% of the optimiser's time. The
    answers are the same; only the edges that cannot possibly be near the
    box are skipped.
    """

    CELL = 8.0

    def __init__(self, points):
        self.points = points
        self.bb = _bbox(points)
        self.cells = {}
        for a, b in zip(points, list(points[1:]) + [points[0]]):
            x0, x1 = sorted((a[0], b[0]))
            y0, y1 = sorted((a[1], b[1]))
            for cx in range(int(x0 // self.CELL), int(x1 // self.CELL) + 1):
                for cy in range(int(y0 // self.CELL), int(y1 // self.CELL) + 1):
                    self.cells.setdefault((cx, cy), []).append((a, b))

    def overlaps(self, box):
        bb = _bbox(box)
        if not _hits(bb, self.bb):
            return False
        # a polygon entirely inside the box (a small pond under a label)
        if (bb[0] <= self.bb[0] and bb[1] <= self.bb[1]
                and bb[2] >= self.bb[2] and bb[3] >= self.bb[3]):
            return True
        edges = set()
        for cx in range(int(bb[0] // self.CELL), int(bb[2] // self.CELL) + 1):
            for cy in range(int(bb[1] // self.CELL), int(bb[3] // self.CELL) + 1):
                for e in self.cells.get((cx, cy), ()):
                    edges.add(e)
        for a, b in edges:
            for c, d in zip(box, list(box[1:]) + [box[0]]):
                if citymap.segs_intersect(a, b, c, d):
                    return True
        # no crossing: either the box is inside the polygon or outside it
        return citymap.point_in_polygon(box[0], self.points)


class Context:
    """Everything that doesn't change while labels are being moved -
    scaled route rectangles, LED dots, prepared geo - built once so a
    label optimiser can re-check one station cheaply."""

    def __init__(self, city, scale=1.0, text_h=citymap.TEXT_H, use_short=False):
        self.city, self.scale, self.text_h, self.use_short = (
            city, scale, text_h, use_short)
        self.size = city.canvas_mm * scale
        self.size_h = city.height * scale
        self.all_st = list(city.stations.values()) + city.extras
        self.segs = []
        for lid, p1, p2, a, b in citymap.segments(city):
            p1 = (p1[0] * scale, p1[1] * scale)
            p2 = (p2[0] * scale, p2[1] * scale)
            self.segs.append((f"{lid}:{a}-{b}", a, b, p1, p2,
                              citymap.seg_rect(p1, p2, LINE_HALF_W)))
        avoid_pts = [(st.x * scale, st.y * scale) for st in self.all_st]
        prepared = citymap.prepared_geo(city, scale, avoid_pts)
        self.geo = [g for g in prepared if g["type"] not in ("river", "line")]
        # silk furniture lines (SeaBus route) are obstacles like routes;
        # copper hairlines (boundaries) are not - silk may cross them
        self.furniture = [(g["name"], citymap.seg_rect(p1, p2, 0.6))
                          for g in prepared if g["type"] == "line" and not g.get("copper")
                          for p1, p2 in zip(g["points"], g["points"][1:])]
        # annotation text (city names, wordmark) as boxes
        self.annots = []
        for a in city.annotations:
            size = a.get("size", 1.4)
            # measured, like every other text extent - the CHAR_W model
            # is 18% narrow on the wordmark
            w = citymap.text_width(a["text"], size)
            h = citymap.BOX_H * size
            x, y = a["x"] * scale, a["y"] * scale
            anchor = a.get("anchor", "start")
            x0 = x - w / 2 if anchor == "center" else (x - w if anchor == "end" else x)
            self.annots.append((a["text"], [(x0, y - h / 2), (x0 + w, y - h / 2),
                                            (x0 + w, y + h / 2), (x0, y + h / 2)]))
        self.dots = {st.id: (st.x * scale, st.y * scale) for st in self.all_st}
        # Bounding boxes for everything static. A label can only touch what
        # overlaps its own bounding box, and this prefilter is what makes the
        # optimiser usable at 251 stations: without it one candidate
        # placement is checked against every route segment and every water
        # polygon on the board, and a single greedy pass takes 14 minutes.
        self._bb_furniture = [_bbox(r) for _, r in self.furniture]
        self._bb_annots = [_bbox(b) for _, b in self.annots]
        self._bb_segs = [_bbox(r) for *_, r in self.segs]
        self._bb_geo = [_bbox(g["points"]) for g in self.geo]
        self._geo_ix = [GeoIndex(g["points"]) for g in self.geo]

    def box(self, st):
        return citymap.label_box(st, self.text_h, self.scale, self.use_short)

    def collisions_for(self, sid, boxes=None, others=True):
        """Collisions involving station sid's label. `boxes` caches the
        other labels' boxes; with others=False only label-label pairs
        where sid sorts first are reported (for a full-matrix pass)."""
        st = next(s for s in self.all_st if s.id == sid)
        box = self.box(st)
        out = []
        # The capsule is what reaches the edge, not the bare text, and the
        # pill's rounded cap sticks out past the box by its radius.
        cap = CAPSULE_HALO + self.text_h * 0.75
        for x, y in box:
            if not (EDGE_MARGIN + cap <= x <= self.size - EDGE_MARGIN - cap and
                    EDGE_MARGIN + cap <= y <= self.size_h - EDGE_MARGIN - cap):
                out.append(Collision("off-board", sid, "", box))
                break
        leader = citymap.leader_segment(st, self.scale)
        # Both labels wear a capsule, so each contributes its border to
        # the space between them.
        # The capsule IS the breathing room, so LABEL_GAP is not added on
        # top of it: two boxes need 2 x the border just for their capsules
        # to clear, plus CAPSULE_GAP so the outlines are visibly apart.
        gap_box = inflate(box, 2 * CAPSULE_HALO + CAPSULE_GAP)
        # the query box: the label, its breathing gap, and its leader
        qb = _bbox(list(gap_box) + (list(leader) if leader else []))
        for o in self.all_st:
            if o.id == sid:
                continue
            ob = boxes[o.id] if boxes else self.box(o)
            ol_pre = citymap.leader_segment(o, self.scale)
            if not _hits(qb, _bbox(list(ob) + (list(ol_pre) if ol_pre else []))):
                continue
            if citymap.polys_intersect(gap_box, ob):
                out.append(Collision("label-label", sid, o.id, box))
            # a leader may not cross another label, nor another leader
            ol = ol_pre
            if leader and citymap.seg_box_overlap(leader, ob):
                out.append(Collision("leader-label", sid, o.id, box))
            if ol and citymap.seg_box_overlap(ol, box):
                out.append(Collision("leader-label", o.id, sid, box))
            if leader and ol and citymap.segs_intersect(leader[0], leader[1], ol[0], ol[1]):
                out.append(Collision("leader-leader", sid, o.id, box))
        for oid, (cx, cy) in self.dots.items():
            if oid == sid:
                r = OWN_R
            elif leader:
                r = LEADER_DOT_R  # a floated label must not read as theirs
            else:
                r = DOT_R
            if citymap.polys_intersect(box, citymap.circle_rect(cx, cy, r)):
                out.append(Collision("label-dot", sid, oid, box))
            if leader and oid != sid and citymap.seg_box_overlap(
                    leader, citymap.circle_rect(cx, cy, OWN_R)):
                out.append(Collision("leader-dot", sid, oid, box))
        for (name, rect), bb in zip(self.furniture, self._bb_furniture):
            if not _hits(qb, bb):
                continue
            if citymap.polys_intersect(box, rect) or (
                    leader and citymap.seg_box_overlap(leader, rect)):
                out.append(Collision("label-line", sid, name, box))
        for (text, ab), bb in zip(self.annots, self._bb_annots):
            if not _hits(qb, bb):
                continue
            if citymap.polys_intersect(gap_box, ab) or (
                    leader and citymap.seg_box_overlap(leader, ab)):
                out.append(Collision("label-annot", sid, text, box))
        for (name, a, b, p1, p2, rect), bb in zip(self.segs, self._bb_segs):
            if not _hits(qb, bb) and sid not in (a, b):
                continue
            if sid in (a, b):
                # own segment: the part beyond the standoff still counts -
                # a label lying along its own line is unreadable
                own = self.dots[sid]
                far = p2 if a == sid else p1
                dx, dy = far[0] - own[0], far[1] - own[1]
                ln = math.hypot(dx, dy)
                if ln <= OWN_R + 0.5:
                    continue
                near = (own[0] + dx / ln * (OWN_R + 0.5),
                        own[1] + dy / ln * (OWN_R + 0.5))
                rect = citymap.seg_rect(near, far, LINE_HALF_W)
            if citymap.polys_intersect(box, rect):
                out.append(Collision("label-line", sid, name, box))
            if leader and sid not in (a, b) and citymap.segs_intersect(
                    leader[0], leader[1], p1, p2):
                out.append(Collision("leader-line", sid, name, box))
        # park outlines / copper water: readable but ugly, flagged so a
        # label ends up there deliberately, not by accident
        for g, bb, ix in zip(self.geo, self._bb_geo, self._geo_ix):
            if not _hits(qb, bb):
                continue
            if ix.overlaps(box):
                out.append(Collision("label-geo", sid, g["name"], box))
        return out


def find_collisions(city, scale=1.0, text_h=citymap.TEXT_H, use_short=False):
    ctx = Context(city, scale, text_h, use_short)
    boxes = {st.id: ctx.box(st) for st in ctx.all_st}
    ids = [st.id for st in ctx.all_st]
    seen = set()
    out = []
    for sid in ids:
        for c in ctx.collisions_for(sid, boxes):
            if c.kind == "label-label":
                key = frozenset((c.a, c.b))
                if key in seen:
                    continue
                seen.add(key)
            out.append(c)
    return out


def summarize(cols):
    by_kind = {}
    for c in cols:
        by_kind.setdefault(c.kind, []).append(c)
    return by_kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--scale", type=float)
    ap.add_argument("--text", type=float, default=citymap.TEXT_H)
    ap.add_argument("--short", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    city = citymap.load(args.data)

    if args.scale:
        matrix = [(args.scale, args.text, args.short)]
    else:
        matrix = [(s, t, sh)
                  for s in (1.0, 1.2, 1.35, 1.5)
                  for t in (1.0, 1.2)
                  for sh in (False, True)]

    print(f"{'board':>7} {'text':>5} {'names':>6} {'total':>6} "
          f"{'lbl-lbl':>8} {'lbl-line':>9} {'lbl-dot':>8} {'off':>4}")
    for s, t, sh in matrix:
        cols = find_collisions(city, s, t, sh)
        k = summarize(cols)
        print(f"{city.canvas_mm * s:6.0f}mm {t:4.1f}mm "
              f"{'short' if sh else 'full':>6} {len(cols):6d} "
              f"{len(k.get('label-label', [])):8d} "
              f"{len(k.get('label-line', [])):9d} "
              f"{len(k.get('label-dot', [])):8d} "
              f"{len(k.get('off-board', [])):4d}")
        if args.verbose:
            for c in cols:
                print(f"    {c.kind:12} {c.a:22} {c.b}")


if __name__ == "__main__":
    main()
