"""Style C: the Tokyo subway drawn the way the official printed map draws it.

    python -X utf8 style_c_official.py

Writes ../test-results/style-c-official.png.

Three things make the official Tokyo Metro / Toei map look the way it does,
and this script does all three:

1. **Even station spacing.** The printed map is not a map of distances - it
   is a map of stops. Every leg is pulled towards one nominal pitch by a
   least-squares solve that keeps each leg on its 0/45/90-degree direction
   and keeps the whole drawing near where `tokyo.json` put it.

2. **Corridors drawn side by side.** Where two or more lines run along the
   same straight, they are drawn parallel with a constant gap, centred on
   the shared centreline, so every colour stays visible. The corridors are
   found geometrically (collinear, overlapping legs), not from shared
   station pairs - on this data only 17 of 267 legs are shared pair-wise,
   but far more lines share a straight without sharing the stops on it.

3. **No land and no water.** The official map draws none, so neither does
   this. Fat uniform strokes, generous rounded corners, nothing else.

The pitch floor (MIN_PITCH_MM, the LED footprint) is still enforced on the
real station positions, which are what the LEDs sit on; the coloured strands
are drawn offset around them.
"""
import io
import json
import math
import os
import sys

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import lsqr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import build_tokyo as BT                                    # noqa: E402
import style_sheet                                          # noqa: E402

SRC = os.path.join(HERE, "tokyo.json")
OUT = os.path.join(HERE, "..", "test-results", "style-c-official.png")

BOARD_W_MM = BT.BOARD_W_MM          # 400
BOARD_H_MM = BT.BOARD_H_MM          # 292
MARGIN_MM = 14.0                    # usable board is 372 x 264 mm
MIN_PITCH_MM = BT.MIN_PITCH_MM      # 3.3, the LED footprint floor

# --- the even-spacing solve -------------------------------------------------
PITCH_MM = 11.0                     # nominal leg length, the whole point of
                                    # the style; trimmed if the fit demands it
ROUNDS = 10                         # re-snap the directions and solve again
W_OCT = 3.0                         # a leg lies along its compass direction
W_PITCH = 1.00                      # ... and is PITCH_MM long
W_ANCHOR = 0.03                     # ... and the map keeps its overall shape
W_SEP = 8.0                         # ... and no two stations are too close
RELAX = 90                          # pitch-floor relaxation steps
WISH_STEP = 0.2                     # how fast a stubborn pair's wish grows
WISH_CAP = 2.4                      # ... and how far, as a multiple of floor
ANNEAL = 22                         # tightening steps on the direction term
ANNEAL_GAIN = 1.28
EVEN_HOLD = 0.60                    # how much of that tightening the even-
                                    # spacing term keeps, so the legs do not
                                    # go back to being long in the suburbs
OCTANTS = 8

# --- the corridors ----------------------------------------------------------
GAP_MM = 2.1                        # centre-to-centre of parallel strands
C_TOL_MM = 0.7                      # two legs are on the same straight if
                                    # their perpendicular offsets agree here
T_OVERLAP_MM = 1.0                  # ... and they overlap by at least this
MITER_CAP_MM = 5.0

# --- the drawing ------------------------------------------------------------
BEND_MM = 3.4                       # generous rounded corners
LINE_W = 4.6                        # points; ~1.5 mm of the 400 mm board
STATION_MS = 4.2
DPI = 120


def load():
    """tokyo.json -> (ids, positions mm, line records, line dict)."""
    with io.open(SRC, encoding="utf-8") as f:
        d = json.load(f)
    b = d["board_scale"]
    ids = sorted(d["stations"])
    p = np.array([[d["stations"][s]["x"] * b, d["stations"][s]["y"] * b]
                  for s in ids])
    return d, ids, p, d["lines"], {ln["id"]: ln for ln in d["lines"]}


def solve_even(ids, anchors, edges, pitch, rounds=ROUNDS, sep=None,
               verbose=True, w_oct=None, w_sep=None, w_pitch=None):
    """Octolinear least squares in which every leg wants the same length.

    `sep` carries the pitch-floor wishes, as build_tokyo.octolinear does:
    (i, j, ux, uy, target) asks for stations i and j to end up `target`
    apart along (ux, uy). Pushing them apart after the solve does not work -
    the next straightening pulls them straight back together.
    """
    index = {s: i for i, s in enumerate(ids)}
    pairs = [(index[a], index[b]) for a, b in edges]
    w_oct = W_OCT if w_oct is None else w_oct
    w_sep = W_SEP if w_sep is None else w_sep
    w_pitch = W_PITCH if w_pitch is None else w_pitch
    p = anchors.copy()
    step = 2 * math.pi / OCTANTS
    for r in range(rounds):
        rows, cols, vals, rhs = [], [], [], []
        nrow = [0]

        def add(terms, b):
            for c, v in terms:
                rows.append(nrow[0]); cols.append(c); vals.append(v)
            rhs.append(b)
            nrow[0] += 1

        off = []
        for i, j in pairs:
            d = p[j] - p[i]
            ang = math.atan2(d[1], d[0])
            snapped = round(ang / step) * step
            off.append(abs(math.degrees(ang - snapped)))
            ux, uy = math.cos(snapped), math.sin(snapped)
            nx, ny = -uy, ux
            add([(2 * j, w_oct * nx), (2 * j + 1, w_oct * ny),
                 (2 * i, -w_oct * nx), (2 * i + 1, -w_oct * ny)], 0.0)
            add([(2 * j, w_pitch * ux), (2 * j + 1, w_pitch * uy),
                 (2 * i, -w_pitch * ux), (2 * i + 1, -w_pitch * uy)],
                w_pitch * pitch)
        for i in range(len(ids)):
            add([(2 * i, W_ANCHOR)], W_ANCHOR * anchors[i, 0])
            add([(2 * i + 1, W_ANCHOR)], W_ANCHOR * anchors[i, 1])
        for i, j, ux, uy, target in (sep or []):
            add([(2 * j, w_sep * ux), (2 * j + 1, w_sep * uy),
                 (2 * i, -w_sep * ux), (2 * i + 1, -w_sep * uy)],
                w_sep * target)
        A = coo_matrix((vals, (rows, cols)),
                       shape=(nrow[0], 2 * len(ids))).tocsr()
        p = lsqr(A, np.array(rhs), atol=1e-10, btol=1e-10,
                 iter_lim=4000)[0].reshape(-1, 2)
        if verbose:
            print(f"  round {r + 1}: mean snap error {np.mean(off):5.2f} deg")
    return p


def relax(ids, p, edges, pitch, iters=RELAX, min_pitch=MIN_PITCH_MM):
    """Open every pair of stations to the LED footprint floor while keeping
    the runs straight and the spacing even.

    The floor cannot be enforced by pushing a pair apart after the solve:
    the next straightening pulls them back. It goes in as a wish, like the
    rest, and a wish for exactly the floor settles short of it - so a pair
    that is still too close has its wish raised a little each step, and no
    wish is ever dropped (a pair released the moment it clears simply
    closes again).
    """
    wishes = {}
    for it in range(iters):
        close = BT.close_pairs(p, min_pitch)
        for i, j, d in close:
            v = p[j] - p[i]
            n = float(np.hypot(*v))
            if n < 1e-6:
                v, n = np.array([1.0, 0.0]), 1.0
            was = wishes.get((i, j), (0.0, 0.0, min_pitch * 1.08))[2]
            wishes[(i, j)] = (v[0] / n, v[1] / n,
                              min(max(was + WISH_STEP, min_pitch * 1.08),
                                  min_pitch * WISH_CAP))
        if not close and it:
            break
        sep = [(i, j, ux, uy, t) for (i, j), (ux, uy, t) in wishes.items()]
        p = solve_even(ids, p, edges, pitch, rounds=1, sep=sep, verbose=False)

    # Anneal: even spacing and exact 45-degree legs pull against each other,
    # so the spacing is settled first (above) and the directions are then
    # tightened a step at a time, the pitch floor held just as hard, until
    # the legs are on their compass directions and nothing has collapsed.
    for k in range(ANNEAL):
        w = W_OCT * (ANNEAL_GAIN ** (k + 1))
        for i, j, d in BT.close_pairs(p, min_pitch):
            v = p[j] - p[i]
            n = float(np.hypot(*v)) or 1.0
            was = wishes.get((i, j), (0.0, 0.0, min_pitch * 1.08))[2]
            wishes[(i, j)] = (v[0] / n, v[1] / n,
                              min(max(was + WISH_STEP, min_pitch * 1.08),
                                  min_pitch * WISH_CAP))
        sep = [(i, j, ux, uy, t) for (i, j), (ux, uy, t) in wishes.items()]
        p = solve_even(ids, p, edges, pitch, rounds=2, sep=sep, verbose=False,
                       w_oct=w, w_sep=max(W_SEP, 2.5 * w),
                       w_pitch=W_PITCH * (ANNEAL_GAIN ** ((k + 1) * EVEN_HOLD)))
    return p, it + 1


def leg_angles(p, ids, edges):
    """How far each drawn leg is from its nearest 45-degree direction."""
    index = {s: i for i, s in enumerate(ids)}
    step = 2 * math.pi / OCTANTS
    out = []
    for a, b in edges:
        d = p[index[b]] - p[index[a]]
        if np.hypot(*d) < 1e-9:
            continue
        ang = math.atan2(d[1], d[0])
        out.append(abs(math.degrees(ang - round(ang / step) * step)))
    return np.array(out)


# --- corridors --------------------------------------------------------------
def corridors(lines, MM):
    """Offset every leg so lines sharing a straight run draw side by side.

    A leg is placed on the infinite straight it lies on - direction octant
    (folded to four, since a straight has no direction) plus perpendicular
    offset. Legs on the same straight that overlap along it form a corridor,
    and the lines in that corridor are spread across it at GAP_MM, centred.

    Returns {(line_id, a, b): (offset_mm, nx, ny)} and the corridor count.
    """
    legs = []
    for ln in lines:
        for path in ln["paths"]:
            for a, b in zip(path, path[1:]):
                if a == b:
                    continue
                pa, pb = np.array(MM[a]), np.array(MM[b])
                d = pb - pa
                n = float(np.hypot(*d))
                if n < 1e-9:
                    continue
                k = int(round(math.atan2(d[1], d[0]) / (math.pi / 4))) % 4
                ang = k * math.pi / 4
                u = np.array([math.cos(ang), math.sin(ang)])
                nrm = np.array([-u[1], u[0]])
                t0, t1 = sorted((float(u @ pa), float(u @ pb)))
                legs.append({"key": (ln["id"], a, b), "lid": ln["id"], "k": k,
                             "c": float(nrm @ pa), "t0": t0, "t1": t1,
                             "n": nrm})

    out, n_corridor = {}, 0
    for k in range(4):
        same = sorted([l for l in legs if l["k"] == k], key=lambda l: l["c"])
        # straights: runs of legs whose perpendicular offsets agree
        bands, cur = [], []
        for leg in same:
            if cur and leg["c"] - cur[-1]["c"] > C_TOL_MM:
                bands.append(cur); cur = []
            cur.append(leg)
        if cur:
            bands.append(cur)
        for band in bands:
            band.sort(key=lambda l: l["t0"])
            group, end = [], None
            for leg in band + [None]:
                if leg is not None and (end is None
                                        or leg["t0"] <= end - T_OVERLAP_MM):
                    group.append(leg)
                    end = max(end or leg["t1"], leg["t1"])
                    continue
                if group:
                    n_corridor += _assign(group, out)
                group, end = ([leg], leg["t1"]) if leg is not None else ([], None)
    return out, n_corridor


def _assign(group, out):
    """Spread the lines of one corridor across it, centred, at GAP_MM."""
    lids = sorted({l["lid"] for l in group})
    mid = (len(lids) - 1) / 2.0
    rank = {lid: (i - mid) * GAP_MM for i, lid in enumerate(lids)}
    for leg in group:
        out[leg["key"]] = (rank[leg["lid"]], leg["n"][0], leg["n"][1])
    return 1 if len(lids) > 1 else 0


def strand_points(lines, MM, off):
    """Per-line station positions: the offset strand, mitred at the corners.

    Every line gets its own copy of each station it serves, keyed
    "line@station", so the renderer can draw parallel strands through a
    shared corridor instead of every line through one point.
    """
    pos = {}
    for ln in lines:
        lid = ln["id"]
        for path in ln["paths"]:
            legs = [(a, b) for a, b in zip(path, path[1:]) if a != b]
            for idx, (a, b) in enumerate(legs):
                here = ((a, legs[idx - 1] if idx else None, (a, b)),
                        (b, (a, b),
                         legs[idx + 1] if idx + 1 < len(legs) else None))
                for sid, prev_leg, next_leg in here:
                    key = f"{lid}@{sid}"
                    if key in pos:
                        continue
                    pos[key] = _miter(MM, sid, prev_leg, next_leg, off, lid)
    return pos


def _vec(MM, leg, off, lid):
    """The sideways shift of one leg of one line, and the leg's direction."""
    if leg is None:
        return None, None
    a, b = leg
    d, nx, ny = off.get((lid, a, b), (0.0, 0.0, 0.0))
    u = np.array(MM[b], dtype=float) - np.array(MM[a], dtype=float)
    u = u / (np.hypot(*u) or 1.0)
    return np.array([nx, ny]) * d, u


def _miter(MM, sid, prev_leg, next_leg, off, lid):
    """Where a station sits on one line's strand: the mitre of its two legs."""
    p = np.array(MM[sid], dtype=float)
    v1, u1 = _vec(MM, prev_leg, off, lid)
    v2, u2 = _vec(MM, next_leg, off, lid)
    if v1 is None:
        return tuple(p + v2)
    if v2 is None:
        return tuple(p + v1)
    cross = u1[0] * u2[1] - u1[1] * u2[0]
    if abs(cross) < 1e-6:                      # straight through
        return tuple(p + (v1 + v2) / 2.0)
    dv = v2 - v1
    s = (dv[0] * u2[1] - dv[1] * u2[0]) / cross
    q = p + v1 + u1 * s
    if np.hypot(*(q - p)) > MITER_CAP_MM:      # a very sharp corner
        return tuple(p + (v1 + v2) / 2.0)
    return tuple(q)


def rounded(lines, pos):
    """Rounded corners, as shapes[line_id]["ka|kb"] in board millimetres."""
    out = {}
    for ln in lines:
        lid = ln["id"]
        shape = {}
        for path in ln["paths"]:
            keys = [f"{lid}@{s}" for s in path]
            pts = [pos[k] for k in keys]
            for i in range(len(keys) - 1):
                if keys[i] == keys[i + 1]:
                    continue
                via = []
                if i > 0:
                    via += [q for q in BT.fillet(pts[i - 1], pts[i], pts[i + 1],
                                                 BEND_MM)
                            if BT._between(q, pts[i], pts[i + 1])]
                if i + 2 < len(keys):
                    via += [q for q in BT.fillet(pts[i], pts[i + 1], pts[i + 2],
                                                 BEND_MM)
                            if BT._between(q, pts[i], pts[i + 1])]
                if via:
                    shape[f"{keys[i]}|{keys[i + 1]}"] = via
        if shape:
            out[lid] = shape
    return out


def main():
    data, ids, q, recs, lines = load()
    edges = BT.edges_of(lines)
    print(f"{len(ids)} stations, {len(edges)} legs, {len(lines)} lines")
    leg0 = np.array([np.hypot(*(np.array(
        [data['stations'][b]['x'], data['stations'][b]['y']]) -
        np.array([data['stations'][a]['x'], data['stations'][a]['y']]))) * 2.0
        for a, b in edges])
    print(f"source leg length: mean {leg0.mean():.2f} mm, "
          f"min {leg0.min():.2f}, max {leg0.max():.2f}, "
          f"spread (max/min) {leg0.max() / leg0.min():.1f}x")

    usable_w = BOARD_W_MM - 2 * MARGIN_MM
    usable_h = BOARD_H_MM - 2 * MARGIN_MM
    anchors, pitch = q.copy(), PITCH_MM
    for attempt in range(6):
        print(f"even-spacing solve (pass {attempt + 1}, pitch {pitch:.2f} mm):")
        p = solve_even(ids, anchors, edges, pitch)
        p, rounds = relax(ids, p, edges, pitch)
        left = [(ids[i], ids[j], round(d, 2))
                for i, j, d in BT.close_pairs(p, MIN_PITCH_MM)]
        w = p[:, 0].max() - p[:, 0].min()
        h = p[:, 1].max() - p[:, 1].min()
        need = max(w / usable_w, h / usable_h)
        print(f"  pitch floor: {rounds} round(s)"
              + ("; still tight: %s" % left if left else "; all clear")
              + f"; drawing {w:.0f} x {h:.0f} mm, {need:.3f} of the usable board")
        if 0.995 <= need <= 1.002:
            break
        grow = min(max(need, 0.80), 1.25)      # settle, do not oscillate
        anchors = anchors / grow
        pitch = pitch / grow

    ang = leg_angles(p, ids, edges)
    print(f"legs off their 45-degree direction: mean {ang.mean():.3f} deg, "
          f"max {ang.max():.3f} deg, {(ang < 1.0).sum()}/{len(ang)} within 1 deg, "
          f"{(ang > 2.0).sum()} over 2 deg")
    worst = sorted(zip(ang, edges), reverse=True)[:6]
    index0 = {s: i for i, s in enumerate(ids)}
    for e, (a, b) in worst:
        L = float(np.hypot(*(p[index0[b]] - p[index0[a]])))
        print(f"    {a}-{b}: {e:5.2f} deg over {L:5.2f} mm "
              f"({L * math.sin(math.radians(e)):.2f} mm sideways)")

    lo, hi = p.min(axis=0), p.max(axis=0)
    p = p - (lo + hi) / 2 + np.array([BOARD_W_MM / 2, BOARD_H_MM / 2])
    MM = {s: (float(p[i, 0]), float(p[i, 1])) for i, s in enumerate(ids)}

    index = {s: i for i, s in enumerate(ids)}
    legs = np.array([np.hypot(*(p[index[b]] - p[index[a]])) for a, b in edges])
    print(f"final leg length: mean {legs.mean():.2f} mm, min {legs.min():.2f}, "
          f"max {legs.max():.2f}, sd {legs.std():.2f} "
          f"({100 * legs.std() / legs.mean():.0f}% of mean), "
          f"spread {legs.max() / legs.min():.1f}x")
    tight = BT.close_pairs(p, MIN_PITCH_MM)
    nearest = min(float(np.hypot(*(p[j] - p[i])))
                  for i in range(len(p)) for j in range(i + 1, len(p)))
    print(f"closest pair of stations: {nearest:.2f} mm "
          f"(floor {MIN_PITCH_MM} mm); under the floor: "
          + (", ".join(f"{ids[i]}-{ids[j]} {d:.2f}" for i, j, d in tight)
             if tight else "none"))

    off, n_corridor = corridors(recs, MM)
    bundled = sum(1 for v in off.values() if abs(v[0]) > 1e-9)
    print(f"corridors with more than one line: {n_corridor}; "
          f"{bundled} legs drawn offset, gap {GAP_MM} mm")

    pos = strand_points(recs, MM, off)
    shapes = rounded(recs, pos)

    # the renderer draws one dot per entry in MM: the per-line strand stops,
    # as the official map does, plus the real station (the LED) in the middle
    # of its bundle.
    draw = dict(pos)
    draw.update(MM)
    drawn = [{"id": r["id"], "name": r["name"], "color": r["color"],
              "paths": [[f"{r['id']}@{s}" for s in path] for path in r["paths"]]}
             for r in recs]

    # LINE_W is in points; the frame is 17 inches wide for the 400 mm board
    stroke_mm = LINE_W / (17.0 * 72.0 / BOARD_W_MM)
    notes = [f"{len(ids)} stations, {len(edges)} legs, {len(lines)} lines; "
             f"no land, no water",
             f"even leg {legs.mean():.1f} mm, median {np.median(legs):.1f}, "
             f"sd {legs.std():.1f} (was {leg0.std():.1f})",
             f"octolinear: {(ang < 1.0).sum()}/{len(ang)} legs within 1 deg",
             f"{n_corridor} corridors parallel at {GAP_MM} mm, "
             f"{stroke_mm:.2f} mm stroke",
             f"closest LEDs {nearest:.2f} mm (floor {MIN_PITCH_MM} mm)"]

    style_sheet.render(OUT, title="C - Official map look (no land)",
                       notes=notes, MM=draw, lines=drawn, shapes=shapes,
                       water=None, rings=None, palette="colour",
                       line_w=LINE_W, station_ms=STATION_MS, station="dot",
                       board=(BOARD_W_MM, BOARD_H_MM), dpi=DPI)


if __name__ == "__main__":
    main()
