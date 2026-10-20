"""Assemble tokyo.json: the subway drawn in straight octolinear runs with
rounded bends, over the real land and water.

    python -X utf8 build_tokyo.py [--variant natural|schematic]

Montreal's schematic was hand-authored on a unit grid: four lines, 73
stations, every leg and corner typed out by hand. Tokyo has thirteen lines
and 219 stations, so the runs are **solved** instead.

The solve, in one paragraph. Every leg between two consecutive stations is
assigned the nearest of the eight compass directions, and then the station
positions are the least-squares answer to three wishes at once: each leg
should point exactly along its direction (penalise the sideways part of it),
each leg should keep roughly the length it really has, and every station
should stay near where it really is. Snapping the directions and re-solving a
few times lets a leg change its mind about which octant it belongs to. The
result is a map of straight 0/45/90-degree runs whose stations have barely
moved - which is what lets the land stay rigid.

The land is **not** warped to fit (lesson A2). It is placed by the single
rotation + uniform scale + shift that best matches where the stations really
are to where they are drawn, so Tokyo Bay, the Sumida and the Imperial
Palace moats keep their true proportions.

Run `geo_tokyo.py` first for the geography preview; this writes
../test-results/schematic-preview.png as it goes.
"""
import argparse
import io
import json
import math
import os
import sys

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import lsqr
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import nearest_points, unary_union

import geo_tokyo as GEO

HERE = os.path.dirname(os.path.abspath(__file__))

# The board. Defaults to the frame's own aspect (lesson B3: let the board
# take the frame's shape rather than forcing a square), but --board overrides
# it, because a square board is also a thing you can decide to want and then
# crop the frame to suit.
BOARD_W_MM = GEO.BOARD_W_MM
BOARD_H_MM = GEO.BOARD_H_MM
MM_PER_KM = GEO.MM_PER_KM
BOARD = 2.0                  # board mm per canvas unit, as Montreal

# --- the solve --------------------------------------------------------------
ROUNDS = 6                   # snap directions, solve, repeat
W_OCT = 1.0                  # a leg should lie along its compass direction
W_LEN = 0.25                 # ... and keep the length it really has
W_ANCHOR = 0.22              # ... and the station should stay where it is
W_SEP = 3.0                  # ... and no two stations closer than the pitch floor

# The tighter crop. A leg longer than this asks to be drawn at this length
# instead of its true one, which pulls the outer tails in - Motoyawata to
# Shinozaki is 35 mm of board for a stretch of Chiba nobody is looking at,
# while Otemachi to Tokyo gets 4 mm. Shortening the tails shrinks the whole
# drawing, and the fit-to-board loop then scales everything back up, so the
# core gets the room. This is the one deliberate departure from true
# proportions in the layout; the land is still placed rigidly and is never
# warped (lesson A2).
LEG_CAP_MM = None            # set by --leg-cap
OCTANTS = 8                  # 45-degree steps
MAX_TURN = math.radians(67.5)   # how far a leg may be turned from its true
                                # direction: one and a half octants, enough
                                # to straighten a run, not enough to fold it

# --- the board --------------------------------------------------------------
MIN_PITCH_MM = 3.3           # lesson B2: 2.5 mm is the package, 3.3 mm is the
                             # footprint once it rotates to aim DOUT
SPREAD_ROUNDS = 40
STUB_MAX_MM = 400.0          # a stub runs to the board edge. It is bounded
                             # only so a wrong direction cannot cut across
                             # the whole map; the direction rule below is
                             # what actually keeps stubs honest.
FAR_STUB_KM = 5.0            # beyond this, the cut station's bearing is not
                             # the direction the track leaves by
BEND_MM = 2.0                # rounded bend radius at a station corner. A
                             # 90-degree turn pulls the track 0.59 mm off the
                             # corner, which the station ring covers; a
                             # 45-degree turn, 0.15 mm.
# Copper keepout disc around each LED, cut out of the bare-copper water.
#
# This is not decoration and it cannot be removed: the water is an F.Cu
# polygon with no net, so a pad inside it is shorted to it - all four pads
# of that LED shorted together. The question is only how small it can be.
#
# The XL-1615's pads reach 1.15 mm from the part centre, and JLCPCB wants
# 0.2 mm between copper features, so 1.4 mm is the electrical floor. At that
# size the hole is barely wider than the LED package (1.6 x 1.5 mm) and
# reads as the part sitting in the water rather than as a hole cut round it.
PAD_CLEAR_MM = 1.4           # the floor: pads 1.15 mm + 0.25 mm clearance

# A station with water all round it is a different problem. Its ground pad
# can only reach the back plane through a via, a via cannot sit in the bare
# copper either, and the via pad needs 0.6 mm plus clearance of its own.
# There is no room for it under the part - the gap between the four pads is
# 0.7 x 0.25 mm - so these, and only these, keep the bigger disc.
VIA_CLEAR_MM = 2.2           # 1.15 pads + 0.25 + 0.6 via pad + 0.2
ENCLOSED_MM = 2.6            # no land this close = the via has nowhere else
LABEL_MARGIN_MM = 14.0        # room outside the outermost stations for their labels
TITLE = "TOKYO"
TITLE_MM = 14.0              # wordmark cap height, in copper like the water
TITLE_CHAR_W = 0.65          # Archivo Narrow SemiBold, as citymap.CHAR_W
HOLE_INSET_MM = 4.0
HOLE_CLEAR_MM = 4.5
MIN_WATER_MM = 0.5           # thinnest copper feature; thin water is fattened
MIN_PIECE_MM2 = 1.5
MIN_EDGE_PIECE_MM2 = 20.0
STUB_MM2 = 10.0
MIN_ISLAND_MM2 = 8.0
MIN_ISLAND_WIDTH_MM = 0.8

# Stations whose side of the water is the point of them: they hold the land
# fit (lesson A2, SHORE_STATIONS). Toyosu, Tatsumi and Shin-kiba sit on the
# reclaimed islands; Kasai and Urayasu on the bay shore; Oshiage, Asakusa and
# Kuramae on the Sumida.
SHORE_STATIONS = {
    "toyosu", "tatsumi", "shin-kiba", "kachidoki", "tsukishima",
    "kasai", "nishi-kasai", "urayasu", "minami-sunamachi",
    "asakusa", "kuramae", "oshiage", "ryogoku", "monzen-nakacho",
    "shinagawa", "sengakuji",
}
SHORE_WEIGHT = 6.0


def load():
    def j(name):
        with io.open(os.path.join(HERE, name), encoding="utf-8") as f:
            return json.load(f)
    return j("tokyo_station_latlon.json"), j("tokyo_stations.json"), j("tokyo_lines.json")


# --- octolinear layout ------------------------------------------------------
def edges_of(lines):
    """Unique consecutive station pairs over every line path."""
    seen, out = set(), []
    for line in lines.values():
        for path in line["paths"]:
            for a, b in zip(path, path[1:]):
                if a == b:
                    continue
                key = (a, b) if a < b else (b, a)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def octolinear(ids, q, edges, rounds=ROUNDS, verbose=True, sep=None, ref=None,
               w_oct=None, ramp=1.0, w_len=None, w_anchor=None, w_sep=None,
               len_ramp=None):
    w_oct = W_OCT if w_oct is None else w_oct
    w_len = W_LEN if w_len is None else w_len
    w_anchor = W_ANCHOR if w_anchor is None else w_anchor
    w_sep = W_SEP if w_sep is None else w_sep
    len_ramp = ramp if len_ramp is None else len_ramp
    """Least-squares octolinear layout. q is (N, 2) in mm; returns (N, 2).

    `sep` is a list of (i, j, ux, uy, target): wishes that stations i and j
    end up `target` apart along the unit axis (ux, uy). The pitch floor is
    enforced through these rather than by pushing stations around after the
    solve, because the straightening would simply pull them back together.

    `ref` is the geography: the positions whose leg directions are the truth.
    A leg may only be snapped to an octant within MAX_TURN of its true
    direction. Without that limit the solve can fold a line back on itself -
    minimising the sideways part of a leg is just as happy with the leg
    reversed, and once a leg flips, the next round re-snaps to the flipped
    direction and it stays flipped. That is what doubled the Ginza line back
    through Tameike-sanno and Akasaka-mitsuke: a -171 degree turn drawn where
    the city turns +33.
    """
    if ref is None:
        ref = q
    index = {sid: i for i, sid in enumerate(ids)}
    pairs = [(index[a], index[b]) for a, b in edges]
    true_ang = np.array([math.atan2(*(ref[j] - ref[i])[::-1]) for i, j in pairs])
    true_len = np.array([np.hypot(*(ref[j] - ref[i])) for i, j in pairs])
    if LEG_CAP_MM:
        true_len = np.minimum(true_len, LEG_CAP_MM)
    p = q.copy()
    step = 2 * math.pi / OCTANTS
    for r in range(rounds):
        # With ramp > 1 the octolinear wish grows each round until it beats
        # the pitch floor (W_SEP is three times W_OCT at the default weights,
        # which is why most legs settle a degree or two off an axis: the
        # separation constraint wins the argument). Ramping it is what turns
        # a natural-looking map into an iconic one.
        W_OCT_R = w_oct * (ramp ** r)
        # The pitch floor does not ramp. It is passed in already scaled,
        # because straight legs and separated stations genuinely compete:
        # the stock 3:1 in the floor's favour is exactly why the unramped
        # map is only 29% octolinear, and giving the floor the same ramp
        # just restores that stalemate at a hundred times the magnitude.
        W_SEP_R = w_sep
        W_LEN_R = w_len * (len_ramp ** r)
        rows, cols, vals, rhs, nrow = [], [], [], [], 0

        def add(terms, b):
            nonlocal nrow
            for c, v in terms:
                rows.append(nrow); cols.append(c); vals.append(v)
            rhs.append(b)
            nrow += 1

        turns = []
        for (i, j), L, t_ang in zip(pairs, true_len, true_ang):
            d = p[j] - p[i]
            ang = math.atan2(d[1], d[0])
            snapped = round(ang / step) * step
            # ... but never further from the truth than MAX_TURN
            off = (snapped - t_ang + math.pi) % (2 * math.pi) - math.pi
            if abs(off) > MAX_TURN:
                limit = t_ang + math.copysign(MAX_TURN, off)
                snapped = round(limit / step) * step
                if abs((snapped - t_ang + math.pi) % (2 * math.pi) - math.pi) > MAX_TURN:
                    snapped -= math.copysign(step, off)
            turns.append(abs(math.degrees(ang - snapped)))
            ux, uy = math.cos(snapped), math.sin(snapped)
            nx, ny = -uy, ux
            # sideways part of the leg -> 0
            add([(2 * j, W_OCT_R * nx), (2 * j + 1, W_OCT_R * ny),
                 (2 * i, -W_OCT_R * nx), (2 * i + 1, -W_OCT_R * ny)], 0.0)
            # along-leg part -> its true length
            # The length wish ramps with the octolinear one. It is the term
            # that stops a short leg collapsing: left behind at 2.5 while the
            # octolinear wish reaches 98, the solve is free to zero a leg
            # rather than turn it, and the two stations end up on the same
            # point - Akasaka-mitsuke and Tameike-sanno 0.05 mm apart, and no
            # amount of extra board clears it, because it is not density.
            add([(2 * j, W_LEN_R * ux), (2 * j + 1, W_LEN_R * uy),
                 (2 * i, -W_LEN_R * ux), (2 * i + 1, -W_LEN_R * uy)], W_LEN_R * L)
        for i in range(len(ids)):                     # stay near the truth
            add([(2 * i, w_anchor)], w_anchor * q[i, 0])
            add([(2 * i + 1, w_anchor)], w_anchor * q[i, 1])
        for i, j, ux, uy, target in (sep or []):      # the pitch floor
            add([(2 * j, W_SEP_R * ux), (2 * j + 1, W_SEP_R * uy),
                 (2 * i, -W_SEP_R * ux), (2 * i + 1, -W_SEP_R * uy)], W_SEP_R * target)

        A = coo_matrix((vals, (rows, cols)), shape=(nrow, 2 * len(ids))).tocsr()
        sol = lsqr(A, np.array(rhs), atol=1e-10, btol=1e-10, iter_lim=4000)[0]
        p = sol.reshape(-1, 2)
        if verbose:
            moved = np.hypot(*(p - q).T)
            print(f"  round {r + 1}: mean snap error {np.mean(turns):5.2f} deg, "
                  f"station moved mean {moved.mean():4.2f} mm, max {moved.max():5.2f} mm")
    return p


def leg_angles(p, ids, edges):
    """How far each drawn leg is from its nearest 45-degree direction."""
    index = {sid: i for i, sid in enumerate(ids)}
    step = 2 * math.pi / OCTANTS
    out = []
    for a, b in edges:
        d = p[index[b]] - p[index[a]]
        if np.hypot(*d) < 1e-9:
            continue
        ang = math.atan2(d[1], d[0])
        out.append(abs(math.degrees(ang - round(ang / step) * step)))
    return np.array(out)


# --- pitch spreading --------------------------------------------------------
def close_pairs(p, min_pitch):
    out = []
    for i in range(len(p)):
        for j in range(i + 1, len(p)):
            d = float(np.hypot(*(p[j] - p[i])))
            if d < min_pitch:
                out.append((i, j, d))
    return out


def spread(ids, p, edges, min_pitch=MIN_PITCH_MM, rounds=SPREAD_ROUNDS, w_oct=None,
           w_len=None, w_anchor=None, w_sep=None,
           straighten=True, ref=None):
    """Open every pair of stations to at least the pitch floor.

    Lesson B2: the floor is a footprint fact, not a package fact - two
    diagonal neighbours' pads collide below 3.3 mm once the LEDs rotate to
    aim DOUT at the next one in the chain.

    Each round asks the solve for a little more separation than the pair
    needs, so the straightening has something to give back, and the pairs
    found are kept in the next round's wishes: dropping a pair as soon as it
    clears lets the next solve close it again.
    """
    p = p.copy()
    wishes = {}
    for r in range(rounds):
        close = close_pairs(p, min_pitch)
        for i, j, d in close:
            v = p[j] - p[i]
            n = float(np.hypot(*v))
            if n < 1e-6:
                v, n = np.array([1.0, 0.0]), 1.0
            wishes[(i, j)] = (v[0] / n, v[1] / n, min_pitch * 1.08)
        if not close and r:
            return p, r, []
        if straighten:
            sep = [(i, j, ux, uy, t) for (i, j), (ux, uy, t) in wishes.items()]
            p = octolinear(ids, p, edges, rounds=1, verbose=False, sep=sep,
                           ref=ref, w_oct=w_oct, w_len=w_len, w_anchor=w_anchor,
                           w_sep=w_sep)
        else:
            # The natural variant keeps true positions, so the pitch floor
            # is met by pushing the pair apart and nothing else.
            for i, j, d in close:
                v = p[j] - p[i]
                n = float(np.hypot(*v)) or 1.0
                push = (min_pitch - d) / 2 + 0.02
                p[i] -= v / n * push
                p[j] += v / n * push
    left = [(ids[i], ids[j], round(d, 2)) for i, j, d in close_pairs(p, min_pitch)]
    return p, rounds, left


# --- drawing ----------------------------------------------------------------
def fillet(a, p, b, radius, steps=8):
    """Points of the rounded bend at p on the way a -> p -> b (board mm)."""
    ua, ub = (a[0] - p[0], a[1] - p[1]), (b[0] - p[0], b[1] - p[1])
    la, lb = math.hypot(*ua), math.hypot(*ub)
    if la < 1e-9 or lb < 1e-9:
        return []
    ua, ub = (ua[0] / la, ua[1] / la), (ub[0] / lb, ub[1] / lb)
    dot = max(-1.0, min(1.0, ua[0] * ub[0] + ua[1] * ub[1]))
    turn = math.pi - math.acos(dot)
    if turn < math.radians(5):
        return []
    t = min(radius * math.tan(turn / 2), 0.45 * la, 0.45 * lb)
    t1 = (p[0] + ua[0] * t, p[1] + ua[1] * t)
    t2 = (p[0] + ub[0] * t, p[1] + ub[1] * t)
    out = []
    for i in range(steps + 1):
        s = i / steps
        out.append(((1 - s) ** 2 * t1[0] + 2 * s * (1 - s) * p[0] + s ** 2 * t2[0],
                    (1 - s) ** 2 * t1[1] + 2 * s * (1 - s) * p[1] + s ** 2 * t2[1]))
    return out


def build_shapes(lines, MM):
    """Rounded bends at every station where a line changes direction.

    The bend is written into the leg either side of the station, so the
    drawn track rounds the corner while the LED stays on it: a 90-degree
    turn pulls the track 0.59 mm off the corner, less than the station
    ring's radius.
    """
    shapes, geoms = {}, []
    for lid, line in lines.items():
        shape = {}
        for path in line["paths"]:
            pts = [MM[s] for s in path]
            for k in range(len(path) - 1):
                a, b = path[k], path[k + 1]
                if a == b:
                    continue
                head = fillet(pts[k - 1], pts[k], pts[k + 1], BEND_MM) if k > 0 else []
                tail = (fillet(pts[k], pts[k + 1], pts[k + 2], BEND_MM)
                        if k + 2 < len(path) else [])
                via = [q for q in head if _between(q, pts[k], pts[k + 1])]
                via += [q for q in tail if _between(q, pts[k], pts[k + 1])]
                if via:
                    shape[f"{a}|{b}"] = [[round(x / BOARD, 3), round(y / BOARD, 3)]
                                         for x, y in via]
                geoms.append(LineString([pts[k]] + via + [pts[k + 1]]))
        if shape:
            shapes[lid] = shape
    return shapes, unary_union(geoms)


def _between(q, a, b):
    """Is q on the a->b side of the corner (within the leg's half-space)?"""
    ab = (b[0] - a[0], b[1] - a[1])
    t = ((q[0] - a[0]) * ab[0] + (q[1] - a[1]) * ab[1]) / (ab[0] ** 2 + ab[1] ** 2 + 1e-12)
    return 0.0 < t < 1.0


WATER_OPEN_MM = 0.0          # set by --water-open


def open_water(water, frame):
    """Drop the channels narrower than 2 * WATER_OPEN_MM, keeping the bay.

    Tokyo is a delta: the Sumida, the Kanda, the moats and the canals all
    run into the bay, so the water is one connected shape 7 mm across on
    average and no filter by piece can separate "bay" from "river". A
    morphological opening can: erode, then dilate by the same amount, and
    anything thinner than the erosion disappears while the wide water comes
    back the shape it was. This is what makes a station sit *beside* the
    water instead of in a disc carved out of it - the alternative, moving
    the stations onto land, moves them kilometres and still does not
    converge, because off one bank in this city is onto another.
    """
    if WATER_OPEN_MM <= 0:
        return water
    opened = water.buffer(-WATER_OPEN_MM, join_style=1)
    if opened.is_empty:
        return opened
    return opened.buffer(WATER_OPEN_MM, join_style=1).intersection(frame)


def apply_crossings(shapes, MM, place, path):
    """Route a leg along a real bridge or tunnel instead of straight across.

    A schematic line that cuts the bay in a straight diagonal is the one
    thing on this map that is plainly wrong rather than merely stylised:
    the Yurikamome crosses on the Rainbow Bridge, the Rinkai Line is in a
    tunnel, and each has an alignment you can point at. The structure is
    given in latitude and longitude and goes through the SAME transform as
    the coastline, so the track lands on the bridge the land already draws.

    The file is {line id: {"a|b": [[lat, lon], ...]}}; the end points are
    the stations and are dropped, the rest become the leg's via points.
    """
    with io.open(path, encoding="utf-8") as f:
        spec = json.load(f)
    used = 0
    for lid, legs in spec.items():
        for key, pts in legs.items():
            a, b = key.split("|")
            if a not in MM or b not in MM:
                print(f"  crossing {lid} {key}: station not on the board, skipped")
                continue
            km = np.array([GEO.km(lat, lon) for lat, lon in pts])
            mm = np.asarray(place(km))
            # Orient the structure the way the leg runs: the file may list
            # it either way round.
            if (math.dist(mm[0], MM[a]) + math.dist(mm[-1], MM[b]) >
                    math.dist(mm[0], MM[b]) + math.dist(mm[-1], MM[a])):
                mm = mm[::-1]
            via = [[round(float(x) / BOARD, 3), round(float(y) / BOARD, 3)]
                   for x, y in mm[1:-1]]
            if not via:
                continue
            shapes.setdefault(lid, {})[f"{a}|{b}"] = via
            used += 1
    print(f"crossings routed along their real structure: {used}")
    return shapes


def land_placement(q_km, p, ids):
    w = np.array([SHORE_WEIGHT if sid in SHORE_STATIONS else 1.0 for sid in ids])
    return similarity(q_km, p, w)[0]


def raw_water(q_km, p, ids, place=None, fatten=True):
    """The water as it would be drawn for this layout, before any station
    clearance is carved out of it.

    The land is fitted to the stations, so where the water falls depends on
    where the solve put them - which is why drying the stations has to be a
    loop: move a station, the land moves under it, check again.
    """
    if place is None:
        place = land_placement(q_km, p, ids)
    raw = shapely.segmentize(GEO.water(), 0.1)
    water = shapely.transform(raw, place).buffer(0)
    frame = box(0, 0, BOARD_W_MM, BOARD_H_MM)
    water = water.intersection(frame)
    if fatten:
        # The drawn water is widened so the thinnest channel still etches.
        # That widening is what puts a station that really stands 30 m back
        # from the bank inside the river, so the side test below has to run
        # against the unfattened water instead.
        water = water.buffer(MIN_WATER_MM / 2, join_style=1).intersection(frame)
        water = open_water(water, frame)
    return water.simplify(0.06, preserve_topology=True)


def dry_targets(p, ids, q_km, clear, place=None):
    """Where each station in (or too near) the water should move to.

    Returns {index: (x, y)} for the stations that are wet. The target is the
    nearest point that is `clear` mm clear of the water, found by walking out
    along the direction away from the water - the nearest point on the
    boundary is the shortest move, and the shortest move is the one that
    disturbs the octolinear geometry least.
    """
    water = raw_water(q_km, p, ids, place)
    if water.is_empty:
        return {}, water
    dry = water.buffer(clear)
    targets = {}
    for i, sid in enumerate(ids):
        pt = Point(p[i])
        if not dry.contains(pt):
            continue
        # the nearest point outside: push out along the outward normal
        edge = nearest_points(water.boundary, pt)[0]
        dx, dy = pt.x - edge.x, pt.y - edge.y
        n = math.hypot(dx, dy)
        if n < 1e-9:                      # dead on the boundary: any way out
            dx, dy, n = 1.0, 0.0, 1.0
        if water.contains(pt):            # inside: the normal points the wrong way
            dx, dy = -dx, -dy
        step = clear + 0.05
        for k in range(1, 40):
            cand = Point(edge.x + dx / n * step * k, edge.y + dy / n * step * k)
            if not dry.contains(cand):
                targets[i] = (cand.x, cand.y)
                break
    return targets, water


# --- the land, placed rigidly ----------------------------------------------
def similarity(src_km, dst_mm, weights):
    """Best rotation + uniform scale + shift, km -> mm. No mirror, no warp."""
    w = weights[:, None]
    sc = (src_km * w).sum(axis=0) / w.sum()
    dc = (dst_mm * w).sum(axis=0) / w.sum()
    u, sv, vt = np.linalg.svd(((dst_mm - dc) * w).T @ (src_km - sc))
    flip = np.diag([1.0, np.sign(np.linalg.det(u @ vt))])
    rot = u @ flip @ vt
    scale = float((sv * np.diag(flip)).sum() / (w * (src_km - sc) ** 2).sum())

    def apply(xy):
        return (np.asarray(xy) - sc) @ rot.T * scale + dc

    angle = math.degrees(math.atan2(rot[1, 0], rot[0, 0]))
    return apply, scale, angle


def ring_with_holes(poly):
    """One outline with each island bridged in: the data format has no holes."""
    pts = list(poly.exterior.coords)[:-1]
    for ring in poly.interiors:
        hole = list(ring.coords)[:-1]
        i = min(range(len(pts)), key=lambda k: (pts[k][0] - hole[0][0]) ** 2 +
                (pts[k][1] - hole[0][1]) ** 2)
        pts = pts[:i + 1] + hole + [hole[0]] + [pts[i]] + pts[i + 1:]
    return [[round(x / BOARD, 2), round(y / BOARD, 2)] for x, y in pts]


def edge_stubs(truncations, MM, latlon, prev=None):
    """Short runs of track that leave the board where a line was cut.

    Direction: the true bearing toward the station that was cropped away,
    snapped to the nearest 45 degrees so the stub matches the octolinear
    geometry. When that station is far off the board - the Shinkansen's next
    stop is Omiya, 25 km away - its bearing is not the direction the track
    leaves by, so the line's own last leg is continued instead.

    Length: to the board edge, but never more than STUB_MAX_MM. Unbounded,
    the Shinkansen's two stubs ran 137 mm and 157 mm and cut a diagonal
    across the whole map.
    """
    out = []
    step = 2 * math.pi / OCTANTS
    prev = prev or {}
    for lid, sid, (lat, lon) in truncations:
        if sid not in MM:
            continue
        here = np.array(GEO.km(*latlon[sid])) if sid in latlon else None
        there = np.array(GEO.km(lat, lon))
        if here is None:
            continue
        d = there - here
        if np.hypot(*d) > FAR_STUB_KM and (lid, sid) in prev:
            # the next stop is too far away to say which way the track goes;
            # carry on the way the line arrived
            a = np.array(MM[prev[(lid, sid)]])
            b = np.array(MM[sid])
            d = b - a
        if np.hypot(*d) < 1e-9:
            continue
        ang = round(math.atan2(d[1], d[0]) / step) * step
        ux, uy = math.cos(ang), math.sin(ang)
        x, y = MM[sid]
        # distance to the board edge along (ux, uy)
        ts = []
        if ux > 1e-9:
            ts.append((BOARD_W_MM - x) / ux)
        elif ux < -1e-9:
            ts.append((0 - x) / ux)
        if uy > 1e-9:
            ts.append((BOARD_H_MM - y) / uy)
        elif uy < -1e-9:
            ts.append((0 - y) / uy)
        if not ts:
            continue
        t = min(min(t for t in ts if t > 0), STUB_MAX_MM)
        out.append((lid, (x, y), (x + ux * t, y + uy * t)))
    return out


def main():
    global WATER_OPEN_MM, STUB_MAX_MM
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="schematic",
                    choices=["schematic", "natural"],
                    help="schematic: octolinear runs. natural: true positions.")
    ap.add_argument("--out", default=None)
    ap.add_argument("--stub-max", type=float, default=STUB_MAX_MM, metavar="MM",
                    help="longest a cut-off line may run toward the board "
                         "edge. The Shinkansen enters north and leaves south; "
                         "once the layout is strictly octolinear both its "
                         "stubs land on the same x and, with its route, draw "
                         "one unbroken line the full height of the board")
    ap.add_argument("--separate-last", action="store_true",
                    help="after the solve, push stations apart physically "
                         "until the pitch floor holds. Costs a little angle "
                         "and is the only thing that actually clears the "
                         "merged pairs a ramped solve creates")
    ap.add_argument("--len-ramp", dest="len_ramp", type=float, default=None,
                    help="ramp for the length wish; defaults to --oct-ramp. "
                         "Below it, short legs collapse and stations merge; "
                         "at it, the map stops being octolinear")
    ap.add_argument("--w-sep", dest="w_sep", type=float, default=W_SEP,
                    help="how hard the pitch floor is held. It ramps with "
                         "--oct-ramp, so the floor is never outvoted")
    ap.add_argument("--expand-core", default=None, metavar="R,K",
                    help="enlarge the dense centre before solving: radius R "
                         "mm about the busiest station, exponent K below 1. "
                         "r_new = R*(r/R)**K, so the inside stretches and "
                         "the rim is untouched. Every published metro map "
                         "does this; the cost here is that the coastline is "
                         "fitted to the stations afterwards, so it moves too")
    ap.add_argument("--crossings", default=None, metavar="FILE",
                    help="route named legs along a real bridge or tunnel, "
                         "given in latitude/longitude; it goes through the "
                         "same transform as the coastline, so the track "
                         "lands on the structure the land already draws")
    ap.add_argument("--shore-shift", action="store_true",
                    help="move stations the solve left offshore onto the "
                         "nearest land. The water is never moved: it is the "
                         "geography and it is the truth")
    ap.add_argument("--shore-clear", type=float, default=PAD_CLEAR_MM,
                    metavar="MM",
                    help="how far clear of the water a shifted station lands")
    ap.add_argument("--water-open", type=float, default=0.0, metavar="MM",
                    help="drop water channels narrower than twice this, "
                         "keeping the bay. The lever that actually gets a "
                         "station out of the water, unlike moving it")
    ap.add_argument("--dry-passes", type=int, default=0, metavar="N",
                    help="move stations out of the water and re-solve, N "
                         "times. The land is fitted to the stations, so "
                         "moving one moves the water under it: it has to be "
                         "a loop, not a single correction")
    ap.add_argument("--dry-clear", type=float, default=PAD_CLEAR_MM,
                    metavar="MM",
                    help="how far clear of the water a station must end up")
    ap.add_argument("--w-len", dest="w_len", type=float, default=W_LEN,
                    help="how hard a leg keeps its true length. Raise it "
                         "alongside --oct-ramp: a strong octolinear wish "
                         "crushes short legs in the core to nothing, and a "
                         "leg with no length left is the one that flips")
    ap.add_argument("--w-anchor", dest="w_anchor", type=float, default=W_ANCHOR,
                    help="how hard a station stays where it really is")
    ap.add_argument("--w-oct", dest="w_oct", type=float, default=W_OCT,
                    help="how hard a leg is pulled onto its compass direction")
    ap.add_argument("--oct-ramp", dest="oct_ramp", type=float, default=1.0,
                    help="multiply --w-oct by this each round, and use the "
                         "final value for the pitch-floor straightening. "
                         "Above 1 the octolinear wish ends up beating the "
                         "pitch floor, which is what makes the map iconic "
                         "rather than natural")
    ap.add_argument("--leg-cap", type=float, default=None,
                    help="draw any leg longer than this at this length, mm: "
                         "pulls the outer tails in so the core gets the room")
    ap.add_argument("--suffix", default="",
                    help="added to the output file names, to keep a variant")
    ap.add_argument("--board", default=None, metavar="WxH",
                    help="board size in mm, e.g. 340x340. Default is the "
                         "frame's aspect at %.0f x %.0f mm"
                         % (GEO.BOARD_W_MM, GEO.BOARD_H_MM))
    ap.add_argument("--fill", type=float, default=1.0,
                    help="how much of the usable board the drawing fills")
    ap.add_argument("--bay", type=float, default=0.0, metavar="MM",
                    help="board height reserved at the bottom for the bay. "
                         "The drawing is fitted above it and centred across "
                         "the board, so the water south-east of the network "
                         "gets room without the map sliding into a corner")
    ap.add_argument("--anchor", choices=["centre", "nw", "n"], default="centre",
                    help="where the drawing sits on the board. n: centred "
                         "left to right, held to the top")
    ap.add_argument("--labels", default=None, metavar="FILE",
                    help="label placements to re-apply after the rebuild "
                         "(lesson B5: hand work must survive regeneration)")
    ap.add_argument("--chain", default=None, metavar="FILE",
                    help="LED chain order to re-apply after the rebuild")
    ap.add_argument("--crop", default=None, metavar="S,W,N,E",
                    help="drop every station outside this lat/lon box, and "
                         "the legs that reached them: a zoomed map that "
                         "spends no board on the outer suburbs")
    args = ap.parse_args()
    if args.len_ramp is None:
        args.len_ramp = args.oct_ramp
    WATER_OPEN_MM = args.water_open
    STUB_MAX_MM = args.stub_max

    global LEG_CAP_MM, BOARD_W_MM, BOARD_H_MM, MM_PER_KM
    LEG_CAP_MM = args.leg_cap
    if args.board:
        BOARD_W_MM, BOARD_H_MM = (float(v) for v in args.board.lower().split("x"))
        MM_PER_KM = BOARD_W_MM / GEO.W_KM
    latlon, meta, lines = load()
    full_latlon = dict(latlon)      # before any crop, for the edge stubs

    truncations = []          # (line id, station kept, lat, lon of the one cut)
    if args.crop:
        s_, w_, n_, e_ = (float(v) for v in args.crop.split(","))
        keep = {sid for sid, (lat, lon) in latlon.items()
                if s_ <= lat <= n_ and w_ <= lon <= e_}
        dropped = sorted(set(latlon) - keep)
        latlon = {k: v for k, v in latlon.items() if k in keep}
        for lid, line in lines.items():
            paths = []
            for path in line["paths"]:
                # Where the path leaves the board, remember the station it
                # left from and the one it was heading for: the silkscreen
                # runs on off the edge rather than stopping dead, so the
                # map reads as a window on a bigger network.
                for a, b in zip(path, path[1:]):
                    if a in keep and b not in keep:
                        truncations.append((lid, a, full_latlon[b]))
                    elif b in keep and a not in keep:
                        truncations.append((lid, b, full_latlon[a]))
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
            line["paths"] = paths
            line["stations"] = len({s for p in paths for s in p})
        # a station whose whole line was cut away is gone too
        on_a_line = {s for l in lines.values() for p in l["paths"] for s in p}
        for sid in sorted(set(latlon) - on_a_line):
            del latlon[sid]
            dropped.append(sid)
        print(f"crop {args.crop}: dropped {len(dropped)} stations, "
              f"{len(latlon)} left")
        for lid, line in sorted(lines.items()):
            if line["stations"] < len({s for p in line["paths"] for s in p}) or True:
                pass
        lost = {}
        for sid in dropped:
            for lid in meta.get(sid, {}).get("lines", []):
                lost.setdefault(lid, []).append(meta[sid]["name"])
        for lid in sorted(lost):
            print(f"    {lid:12s} lost {len(lost[lid]):2d}: "
                  f"{', '.join(sorted(lost[lid])[:6])}"
                  f"{' ...' if len(lost[lid]) > 6 else ''}")

    ids = sorted(latlon)
    q_km = np.array([GEO.km(*latlon[sid]) for sid in ids])
    q_mm = q_km * MM_PER_KM
    edges = edges_of(lines)
    print(f"{len(ids)} stations, {len(edges)} legs, {len(lines)} lines")
    print(f"board {BOARD_W_MM:.0f} x {BOARD_H_MM:.0f} mm at {MM_PER_KM:.2f} mm/km")

    # Straighten, open the pitch, and shrink to fit: the octolinear solve
    # and the pitch floor both push outward, so the drawing ends up wider
    # than the stations really are. Shrinking the anchors and solving again
    # settles it; the alternative is a board that overflows its own edge.
    anchors = q_mm.copy()
    # --- enlarge the centre --------------------------------------------------
    index_of = {sid: i for i, sid in enumerate(ids)}
    if args.expand_core:
        R, K = (float(v) for v in args.expand_core.split(","))
        # the busiest station is the centre of the congestion
        deg = {sid: 0 for sid in ids}
        for a, b in edges:
            deg[a] += 1
            deg[b] += 1
        hub = max(deg, key=lambda s: deg[s])
        hx, hy = anchors[index_of[hub]]
        moved = 0
        for i in range(len(ids)):
            dx, dy = anchors[i, 0] - hx, anchors[i, 1] - hy
            r = math.hypot(dx, dy)
            if r < 1e-6 or r > R:
                continue
            rn = R * (r / R) ** K
            anchors[i] = (hx + dx / r * rn, hy + dy / r * rn)
            moved += 1
        print(f"centre enlarged about {hub}: {moved} station(s) within {R:.0f} mm, "
              f"exponent {K}")

    for attempt in range(8):
        if args.variant == "schematic":
            print(f"octolinear solve (pass {attempt + 1}):")
            p = octolinear(ids, anchors, edges, ref=anchors,
                           w_oct=args.w_oct, ramp=args.oct_ramp,
                           w_len=args.w_len, w_anchor=args.w_anchor,
                           w_sep=args.w_sep, len_ramp=args.len_ramp)
        else:
            p = anchors.copy()
        p, rounds, left = spread(ids, p, edges, ref=anchors,
                                 straighten=args.variant == "schematic",
                                 w_oct=args.w_oct * args.oct_ramp ** (ROUNDS - 1),
                                 w_len=args.w_len * args.len_ramp ** (ROUNDS - 1),
                                 w_anchor=args.w_anchor, w_sep=args.w_sep)
        w = p[:, 0].max() - p[:, 0].min()
        h = p[:, 1].max() - p[:, 1].min()
        avail_w = BOARD_W_MM - 2 * LABEL_MARGIN_MM
        avail_h = BOARD_H_MM - 2 * LABEL_MARGIN_MM - args.bay
        need = max(w / avail_w, h / avail_h) / args.fill
        print(f"  pitch spreading: {rounds} round(s)"
              + (f"; still under {MIN_PITCH_MM} mm: {left}" if left else "; all clear")
              + f"; drawing {w:.0f} x {h:.0f} mm, {need:.3f} of the "
                f"{avail_w:.0f} x {avail_h:.0f} mm usable board")
        # Scale both ways. Shrinking stops the drawing overflowing the
        # board; growing is what turns a shorter tail into room in the core,
        # and without it a leg cap just makes a smaller map.
        if 0.99 <= need <= 1.002:
            break
        # Damped: scaling straight to the target overshoots, because the
        # solve and the pitch floor both push back, and the loop then
        # oscillates instead of settling.
        anchors = anchors / (need ** 0.6)

    # --- dry the stations ---------------------------------------------------
    # A station in the water needs a disc of substrate carved out of the pour
    # to sit in, which reads as an island in the middle of a river and leaves
    # the front pour in pieces. Moving the station onto land instead is the
    # fix. The anchors are moved, not the positions, so the octolinear solve
    # still gets the last word and the legs stay on their axes; the track
    # bends to follow, which is the S curve.
    if args.dry_passes and args.variant == "schematic":
        # The land is fitted to the stations, so re-fitting it every pass
        # lets the water chase the stations being moved and the count just
        # oscillates (66, 60, 64, 52, 62 ...). Freeze the placement for the
        # whole loop, and re-fit once at the end.
        place = land_placement(q_km, p, ids)
        for dp in range(args.dry_passes):
            targets, _ = dry_targets(p, ids, q_km, args.dry_clear, place)
            if not targets:
                print(f"  drying pass {dp + 1}: every station is on land")
                break
            shift = 0.0
            for i, (tx, ty) in targets.items():
                shift = max(shift, math.hypot(tx - p[i, 0], ty - p[i, 1]))
                anchors[i] = (tx, ty)
            print(f"  drying pass {dp + 1}: {len(targets)} station(s) in or "
                  f"within {args.dry_clear} mm of water, worst {shift:.1f} mm")
            p = octolinear(ids, anchors, edges, ref=anchors, verbose=False,
                           w_oct=args.w_oct, ramp=args.oct_ramp,
                           w_len=args.w_len, w_anchor=args.w_anchor,
                           w_sep=args.w_sep, len_ramp=args.len_ramp)
            p, _, _ = spread(ids, p, edges, ref=anchors, straighten=True,
                             w_oct=args.w_oct * args.oct_ramp ** (ROUNDS - 1),
                             w_len=args.w_len, w_anchor=args.w_anchor)
        left, _ = dry_targets(p, ids, q_km, args.dry_clear, place)
        print(f"stations still in or against water: {len(left)} "
              f"(against the frozen land placement)")

    ang = leg_angles(p, ids, edges)
    print(f"legs off their 45-degree direction: mean {ang.mean():.2f} deg, "
          f"max {ang.max():.2f} deg, {(ang < 1.0).sum()}/{len(ang)} within 1 deg")
    # folds: a leg drawn more than a right angle away from the way the city
    # actually runs. Should be zero; it is the check that the MAX_TURN limit
    # is doing its job.
    index = {sid: i for i, sid in enumerate(ids)}
    folds = []
    for a, b in edges:
        i, j = index[a], index[b]
        da = math.atan2(*(p[j] - p[i])[::-1])
        ta = math.atan2(*(q_mm[j] - q_mm[i])[::-1])
        off = abs((da - ta + math.pi) % (2 * math.pi) - math.pi)
        if off > math.pi / 2:
            folds.append((a, b, round(math.degrees(off))))
    print(f"legs folded past a right angle from the truth: {folds or 'none'}")
    # How far each station is from where the city puts it, measured after
    # the best rigid alignment of the two - otherwise this reports the zoom
    # factor rather than the distortion.
    fit, fit_scale, _ = similarity(q_mm / MM_PER_KM, p,
                                   np.ones(len(ids)))
    moved = np.hypot(*(p - fit(q_mm / MM_PER_KM)).T)
    print(f"stations moved from true: mean {moved.mean():.2f} mm "
          f"({moved.mean() / fit_scale * 1000:.0f} m), max {moved.max():.2f} mm "
          f"({moved.max() / fit_scale * 1000:.0f} m)")

    # centre the drawing on the board
    # centre on the drawing's bounding box, not the mean: a long tail of
    # outer stations drags the mean and pushes the far side off the board
    lo, hi = p.min(axis=0), p.max(axis=0)
    if args.anchor == "nw":
        p = p - lo + LABEL_MARGIN_MM
    elif args.anchor == "n":
        p = p - lo + np.array([(BOARD_W_MM - (hi - lo)[0]) / 2, LABEL_MARGIN_MM])
    else:
        p = p - (lo + hi) / 2 + np.array([BOARD_W_MM / 2, BOARD_H_MM / 2])
    MM = {sid: (float(p[i, 0]), float(p[i, 1])) for i, sid in enumerate(ids)}

    for lid, line in lines.items():
        for off in line.get("off_board", []):
            if off["from"] in latlon:
                truncations.append((lid, off["from"], off["toward"]))
    prev = {}
    for lid, line in lines.items():
        for path in line["paths"]:
            if len(path) >= 2:
                prev[(lid, path[0])] = path[1]
                prev[(lid, path[-1])] = path[-2]
    # --- hold the pitch floor, physically -----------------------------------
    # A strong octolinear wish and the 3.3 mm floor cannot both be won by the
    # least-squares solve: the floor is a wish there, and the straightening
    # outvotes it every round, so stations merge (Akasaka-mitsuke and
    # Tameike-sanno 0.05 mm apart). Pushing them apart afterwards, with no
    # re-solve, costs a little angle and settles it for good.
    if args.separate_last:
        before = sum(1 for a in range(len(ids)) for b in range(a + 1, len(ids))
                     if math.dist(p[a], p[b]) < MIN_PITCH_MM)
        p, rounds, left = spread(ids, p, edges, ref=p, straighten=False)
        after = sum(1 for a in range(len(ids)) for b in range(a + 1, len(ids))
                    if math.dist(p[a], p[b]) < MIN_PITCH_MM)
        print(f"final separation push: {rounds} round(s), "
              f"{before} pair(s) under the floor -> {after}")
        MM = {sid: (float(p[i, 0]), float(p[i, 1])) for i, sid in enumerate(ids)}

    # --- stations onto the shore --------------------------------------------
    # The water is the truth and is never moved. What is wrong is the handful
    # of stations the solve has left offshore: Shinagawa is on land in Tokyo
    # and belongs on land here. Each one moves the shortest way out, and
    # nothing else moves - re-solving the network instead is what made the
    # earlier attempt wander kilometres without ever converging. The legs
    # into a shifted station change direction, and build_shapes already
    # fillets a direction change, so the track curves in rather than kinking.
    shore_place = None
    if args.shore_shift:
        shore_place = land_placement(q_km, p, ids)
        water = raw_water(q_km, p, ids, shore_place)                  # as drawn
        true_water = raw_water(q_km, p, ids, shore_place, fatten=False)
        danger = water.buffer(args.shore_clear)
        moved, flipped = [], []
        for i, sid in enumerate(ids):
            pt = Point(MM[sid])
            if not danger.contains(pt):
                continue
            # Which bank is this station really on? Iidabashi stands on the
            # north side of the Kanda and Ichigaya on the south; pushing
            # either to the NEAREST dry point can put it across the river,
            # which is a worse error than the notch it fixes. The direction
            # out is taken from the UNFATTENED water, so it always leads
            # away from the bank the station actually stands on.
            ref = true_water if not true_water.is_empty else water
            inside_true = ref.contains(pt)
            edge = nearest_points(ref.boundary, pt)[0]
            dx, dy = pt.x - edge.x, pt.y - edge.y
            n = math.hypot(dx, dy)
            if n < 1e-9:
                dx, dy, n = 1.0, 0.0, 1.0
            if inside_true:             # genuinely over water: any way out
                dx, dy = -dx, -dy
            ux, uy = dx / n, dy / n
            # Walk outward along that side until the clearance disc is clear
            # of the drawn water. Stepping from the station, not from the
            # bank, is what keeps a station that is already well inland from
            # being dragged back to the water's edge.
            cand = None
            for k in range(1, 160):
                step = args.shore_clear * 0.25 * k
                c = Point(pt.x + ux * step, pt.y + uy * step)
                if not danger.contains(c):
                    cand = (c.x, c.y)
                    break
            if cand is None:
                continue
            # It must not have crossed TO THE OTHER BANK. Testing for a
            # boundary crossing is too strict: a station standing in the
            # fattened river has to cross the bank once on its way out, and
            # that is the move we want. What is forbidden is water still
            # ahead of it - that means the far bank.
            seg = LineString([(pt.x, pt.y), cand])
            ahead = seg.difference(Point(pt.x, pt.y).buffer(n + 0.05))
            if not ahead.is_empty and ahead.intersects(ref):
                flipped.append(sid)
                continue
            moved.append((math.hypot(cand[0] - pt.x, cand[1] - pt.y), sid))
            MM[sid] = cand
            p[i] = cand
        if flipped:
            print(f"  left in place rather than cross the water: "
                  f"{len(flipped)} ({', '.join(sorted(flipped)[:6])})")
        moved.sort(reverse=True)
        print(f"stations shifted onto the shore: {len(moved)}"
              + (f", worst {moved[0][0]:.1f} mm ({moved[0][1]})" if moved else ""))

        # Several stations can be nearest the same stretch of shore and end
        # up stacked on it - 38 pairs under the pitch floor, two of them
        # 0.05 mm apart. Push them apart along the shore, then put back
        # anyone the push shoved into the water.
        shifted = {sid for _, sid in moved}
        for _ in range(60):
            worst = 0.0
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    sa, sb = ids[a], ids[b]
                    if sa not in shifted and sb not in shifted:
                        continue
                    ax, ay = MM[sa]
                    bx, by = MM[sb]
                    dd = math.hypot(bx - ax, by - ay)
                    if dd >= MIN_PITCH_MM:
                        continue
                    worst = max(worst, MIN_PITCH_MM - dd)
                    ux, uy = ((bx - ax) / dd, (by - ay) / dd) if dd > 1e-9 else (1.0, 0.0)
                    gap = MIN_PITCH_MM - dd + 0.02
                    # Both ends give way. Moving only the shifted one leaves
                    # the pairs where the station already on land is the one
                    # in the way, which is the last handful that would not
                    # clear.
                    share = 0.5 if (sa in shifted and sb in shifted) else 1.0
                    for sid, sign in ((sa, -1.0), (sb, 1.0)):
                        if share == 1.0 and sid not in shifted:
                            continue
                        x, y = MM[sid]
                        MM[sid] = (x + ux * gap * share * sign,
                                   y + uy * gap * share * sign)
            if worst < 0.01:
                break
        # Push apart, put back on land, repeat. One pass of each is not
        # enough: re-projecting a station out of the water can shove it
        # into its neighbour again, which is how Oji and Oji-ekimae ended
        # up 2.68 mm apart under a 3.3 mm floor.
        for _ in range(8):
            for sid in shifted:
                pt = Point(MM[sid])
                if not danger.contains(pt):
                    continue
                edge = nearest_points(water.boundary, pt)[0]
                dx, dy = pt.x - edge.x, pt.y - edge.y
                n = math.hypot(dx, dy) or 1.0
                if water.contains(pt):
                    dx, dy = -dx, -dy
                for k in range(1, 80):
                    step = args.shore_clear * 0.4 * k
                    cand = (edge.x + dx / n * step, edge.y + dy / n * step)
                    if not danger.contains(Point(cand)):
                        MM[sid] = cand
                        break
            worst = 0.0
            for a in range(len(ids)):
                for b in range(a + 1, len(ids)):
                    sa, sb = ids[a], ids[b]
                    ax, ay = MM[sa]
                    bx, by = MM[sb]
                    dd = math.hypot(bx - ax, by - ay)
                    if dd >= MIN_PITCH_MM:
                        continue
                    worst = max(worst, MIN_PITCH_MM - dd)
                    ux, uy = ((bx - ax) / dd, (by - ay) / dd) if dd > 1e-9 else (1.0, 0.0)
                    gap = (MIN_PITCH_MM - dd) / 2 + 0.02
                    MM[sa] = (ax - ux * gap, ay - uy * gap)
                    MM[sb] = (bx + ux * gap, by + uy * gap)
            if worst < 0.01:
                break
        for i, sid in enumerate(ids):
            p[i] = MM[sid]

        tight = []
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                dd = math.dist(MM[ids[a]], MM[ids[b]])
                if dd < MIN_PITCH_MM:
                    tight.append((round(dd, 2), ids[a], ids[b]))
        if tight:
            print(f"  WARNING: {len(tight)} pair(s) now under the "
                  f"{MIN_PITCH_MM} mm pitch floor: {sorted(tight)[:5]}")

    shapes, routes = build_shapes(lines, MM)
    if args.crossings:
        place_for = (shore_place if shore_place is not None
                     else land_placement(q_km, p, ids))
        shapes = apply_crossings(shapes, MM, place_for, args.crossings)
    stubs = edge_stubs(truncations, MM, latlon, prev)
    if stubs:
        print(f"lines run off the board edge at {len(stubs)} places")

    # --- the land ----------------------------------------------------------
    w = np.array([SHORE_WEIGHT if sid in SHORE_STATIONS else 1.0 for sid in ids])
    place, scale, angle = similarity(q_km, p, w)
    if shore_place is not None:
        # Re-fitting now would drag the coastline after the stations that
        # were just moved off it, and put them back in the water.
        place = shore_place
        print(f"land placed rigidly: {scale:.2f} mm/km (frozen before the "
              f"shore shift)")
    else:
        print(f"land placed rigidly: {scale:.2f} mm/km, rotated {angle:+.2f} deg")
    raw = shapely.segmentize(GEO.water(), 0.1)        # km, so long edges follow
    water = shapely.transform(raw, place).buffer(0)

    FRAME = box(0, 0, BOARD_W_MM, BOARD_H_MM)
    water = water.intersection(FRAME)
    water = water.buffer(MIN_WATER_MM / 2, join_style=1).intersection(FRAME)
    water = open_water(water, FRAME)
    water = water.simplify(0.06, preserve_topology=True)
    edge = FRAME.boundary.buffer(0.01)
    water = unary_union([g for g in getattr(water, "geoms", [water])
                         if g.area >= (MIN_EDGE_PIECE_MM2 if g.intersects(edge)
                                       else MIN_PIECE_MM2)])

    def keep_island(ring):
        island = Polygon(ring)
        return (island.area >= MIN_ISLAND_MM2
                and not island.buffer(-MIN_ISLAND_WIDTH_MM / 2).is_empty)

    water = unary_union([Polygon(g.exterior, [r for r in g.interiors if keep_island(r)])
                         for g in getattr(water, "geoms", [water])
                         if g.geom_type == "Polygon"])

    wet = sorted(sid for sid in ids if water.contains(Point(MM[sid])))
    # Which stations have water all the way round them at the via radius?
    # Those are the ones that keep the bigger disc; everyone else gets the
    # electrical floor, so the river runs up to the LED.
    land_here = FRAME.difference(water)
    enclosed = sorted(sid for sid in ids
                      if not land_here.intersects(
                          Point(MM[sid]).buffer(ENCLOSED_MM, 16)))
    for sid, pt in MM.items():
        water = water.difference(Point(pt).buffer(
            VIA_CLEAR_MM if sid in enclosed else PAD_CLEAR_MM, 16))
    water = unary_union([g for g in getattr(water, "geoms", [water])
                         if g.area >= STUB_MM2
                         or min(g.distance(Point(v)) for v in MM.values()) > 5.0])
    HOLES = [(x, y) for x in (HOLE_INSET_MM, BOARD_W_MM - HOLE_INSET_MM)
             for y in (HOLE_INSET_MM, BOARD_H_MM - HOLE_INSET_MM)]
    for pt in HOLES:
        water = water.difference(Point(pt).buffer(HOLE_CLEAR_MM, 16))

    print(f"water: {water.area:.0f} mm2, "
          f"{len([g for g in getattr(water, 'geoms', [water])])} pieces")
    print(f"stations sitting in water (island carved): {wet or 'none'}")
    print(f"stations with water all round them, keeping the {VIA_CLEAR_MM} mm "
          f"via island: {len(enclosed)}"
          + (f" ({', '.join(enclosed[:8])}{' ...' if len(enclosed) > 8 else ''})"
             if enclosed else ""))

    # --- write -------------------------------------------------------------
    out_lines = []
    for lid, line in sorted(lines.items(), key=lambda kv: kv[1]["ref"]):
        rec = {"id": lid, "name": line["name"], "ref": line["ref"],
               "color": line["colour"], "operator": line["operator"],
               "paths": line["paths"]}
        if line.get("weight", 1.0) != 1.0:
            rec["weight"] = line["weight"]
        if lid in shapes:
            rec["shape"] = shapes[lid]
        ends = [st[1:] for st in stubs if st[0] == lid]
        if ends:
            rec["stubs"] = [[[round(v / BOARD, 3) for v in p] for p in e]
                            for e in ends]
        out_lines.append(rec)

    stations = {}
    for sid in ids:
        rec = meta.get(sid, {})
        stations[sid] = {"name": rec.get("name", sid),
                         "name_ja": rec.get("name_ja", ""),
                         "codes": rec.get("codes", []),
                         "lines": rec.get("lines", []),
                         "x": round(MM[sid][0] / BOARD, 3),
                         "y": round(MM[sid][1] / BOARD, 3)}
        if rec.get("status"):
            stations[sid]["status"] = rec["status"]

    # Hand work goes back on before the file is written. A rebuild that
    # silently drops the labels or the chain is how Vancouver nearly lost a
    # day's hand placement (lesson B5).
    if args.labels and os.path.exists(args.labels):
        with io.open(args.labels, encoding="utf-8") as f:
            overrides = json.load(f)
        applied = 0
        for sid, entry in overrides.items():
            if sid in stations:
                stations[sid]["label"] = dict(entry["label"])
                if "wrap" in entry:
                    stations[sid]["wrap"] = entry["wrap"]
                applied += 1
        missing = sorted(set(overrides) - set(stations))
        print(f"labels re-applied: {applied} of {len(overrides)}"
              + (f"; {len(missing)} are for stations no longer on the board: "
                 f"{', '.join(missing[:6])}" if missing else ""))

    chain = []
    if args.chain and os.path.exists(args.chain):
        with io.open(args.chain, encoding="utf-8") as f:
            chain = json.load(f)
        if sorted(chain) != sorted(stations):
            print(f"  WARNING: the chain is for a different station set "
                  f"({len(chain)} vs {len(stations)}); dropped, re-run "
                  f"build_chain.py")
            chain = []
        else:
            print(f"chain re-applied: {len(chain)} LEDs")

    geo = [{"name": f"water-{i}", "type": "water", "points": ring_with_holes(g)}
           for i, g in enumerate(sorted(getattr(water, "geoms", [water]),
                                        key=lambda poly: -poly.area))
           if g.geom_type == "Polygon" and g.area >= 1.0]

    # --- the wordmark, in the bottom-left corner -----------------------
    # Copper like the water, on the clearest land the lower-left quarter has
    # to offer. Searched rather than placed by hand so it moves with the
    # layout instead of quietly ending up on top of a line.
    tw = len(TITLE) * TITLE_CHAR_W * TITLE_MM
    th = 1.25 * TITLE_MM
    land = box(0, 0, BOARD_W_MM, BOARD_H_MM).difference(water)
    avoid = unary_union([routes.buffer(3.0)]
                        + [Point(v).buffer(7.0) for v in MM.values()])
    best = None
    # 12 mm, not 6: TITLE_CHAR_W is a model of the width and the real face
    # sets a little wider than it, so a 6 mm margin left the T touching the
    # board edge in the preview.
    for cx in np.arange(tw / 2 + 12, BOARD_W_MM * 0.55, 2.0):
        for cy in np.arange(BOARD_H_MM * 0.55, BOARD_H_MM - th / 2 - 6, 2.0):
            blk = box(cx - tw / 2, cy - th / 2, cx + tw / 2, cy + th / 2)
            if not land.contains(blk.buffer(2.0)) or blk.intersects(avoid):
                continue
            # the clearest spot, nudged toward the bottom-left corner
            score = (min(blk.distance(avoid), 14.0)
                     + 0.05 * (BOARD_H_MM - cy) * -1
                     + 0.05 * (BOARD_W_MM - cx))
            if best is None or score > best[0]:
                best = (score, float(cx), float(cy))
    annotations = []
    if best:
        annotations.append({"text": TITLE, "x": round(best[1] / BOARD, 2),
                            "y": round(best[2] / BOARD, 2), "size": TITLE_MM,
                            "angle": 0, "anchor": "center", "copper": True,
                            "bold": True})
        print(f"wordmark '{TITLE}' at ({best[1]:.0f}, {best[2]:.0f}) mm, "
              f"{tw:.0f} x {th:.0f} mm")
    else:
        print(f"  WARNING: no clear land in the lower left for the wordmark")

    data = {
        "city": "tokyo",
        "variant": args.variant,
        "lines": out_lines,
        "stations": stations,
        "extras": [],
        "chain": chain,         # from build_chain.py, re-applied on rebuild
        "geo": geo,
        "annotations": annotations,
        "mounting_holes": [list(h) for h in HOLES],
        "canvas_mm": BOARD_W_MM / BOARD,
        "canvas_h_mm": BOARD_H_MM / BOARD,
        "board_scale": BOARD,
    }
    out = args.out or os.path.join(HERE, f"tokyo-{args.variant}{args.suffix}.json")
    with io.open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    print("wrote", os.path.basename(out))

    render(os.path.join(HERE, "..", "test-results",
                        f"{args.variant}{args.suffix}-preview.png"),
           water, MM, out_lines, shapes)


def render(path, water, MM, out_lines, shapes, dpi=110, labels=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(18, 18 * BOARD_H_MM / BOARD_W_MM), dpi=dpi)
    ax.set_facecolor("#2f5442")
    for g in getattr(water, "geoms", [water]):
        if g.geom_type != "Polygon":
            continue
        x, y = g.exterior.xy
        ax.fill(x, y, color="#f2d43a", lw=0, zorder=1)
        for r in g.interiors:
            x, y = r.xy
            ax.fill(x, y, color="#2f5442", lw=0, zorder=1)
    for line in out_lines:
        shape = shapes.get(line["id"], {})
        for p in line["paths"]:
            for a, b in zip(p, p[1:]):
                if a == b:
                    continue
                via = [(x * BOARD, y * BOARD) for x, y in shape.get(f"{a}|{b}", [])]
                pts = [MM[a]] + via + [MM[b]]
                ax.plot([q[0] for q in pts], [q[1] for q in pts], color=line["color"],
                        lw=2.4, solid_capstyle="round", zorder=2)
    for sid, (x, y) in MM.items():
        ax.plot(x, y, "o", ms=3.4, mfc="white", mec="#1a1a1a", mew=0.7, zorder=3)
    ax.set_xlim(0, BOARD_W_MM)
    ax.set_ylim(BOARD_H_MM, 0)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    plt.subplots_adjust(0, 0, 1, 1)
    plt.savefig(path, dpi=dpi)
    plt.close(fig)
    print("wrote", os.path.normpath(path))


if __name__ == "__main__":
    main()
