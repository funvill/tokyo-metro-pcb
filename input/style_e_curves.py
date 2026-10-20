"""Style E: the subway as smooth flowing curves through every station.

    python -X utf8 style_e_curves.py

The opposite pole from the octolinear styles. Every line path is one
continuous centripetal Catmull-Rom spline that is *interpolating*: it passes
exactly through every station, because every station is an LED and the track
has to arrive at its pad. No straight runs, no corner radii - the whole line
is one ribbon whose curvature varies with how the stations actually sit.

Three knobs, and only three:

* `alpha` - the knot parameterisation. 0 is uniform (loops badly where
  stations crowd), 1 is chord-length, 0.5 is centripetal, which is the one
  that provably never cusps or loops within a segment.
* `tau` - tangent gain. 0 collapses to straight polyline, 0.5 is textbook
  Catmull-Rom, above ~1 the ribbon starts swinging wide of the stations.
* `cap` - the control-point leash. Each Hermite tangent is converted to its
  equivalent cubic-Bezier handle and that handle is clamped to `cap` times
  the chord it belongs to. This is what actually kills the overshoot: a
  station 1 mm from its neighbour and 20 mm from the next one is where a
  naive spline throws a loop, and a per-segment leash is local enough to fix
  only that spot and leave the long sweeps alone.

Self-intersections are then measured for real (shapely, segment pairs via an
STRtree) and any path that is still non-simple gets its `tau` walked down
until it is. Counts are printed.

Writes, into ../test-results/:
    style-e-curves.png           gentle curvature, true-scale land (the pick)
    style-e-curves-strong.png    strong curvature, same frame
    style-e-curves-board.png     white silkscreen on green mask
    style-e-curves-core.png      zoom on the otemachi cluster
    style-e-curves-schematic.png the same spline over octolinear positions
"""
import io
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "tools"))
import style_sheet as SS

OUT = os.path.join(HERE, "..", "test-results")
SAMPLE_MM = 0.7          # one sample every 0.7 mm: smooth at 100 dpi, small json

# the two sub-variants
GENTLE = dict(alpha=0.5, tau=0.50, cap=0.30)
STRONG = dict(alpha=0.5, tau=1.00, cap=0.55)


# --- the spline -------------------------------------------------------------
def catmull_rom(P, alpha=0.5, tau=0.5, cap=0.30, step=SAMPLE_MM):
    """Interpolating centripetal Catmull-Rom through P, as sampled points.

    P is an (n,2) array in mm. Returns a list of (x, y) that starts at P[0],
    ends at P[-1], and passes exactly through every P[i]; also returns the
    index into that list of each P[i], so the samples can be split back into
    per-leg `shapes` entries.
    """
    P = np.asarray(P, dtype=float)
    n = len(P)
    if n < 2:
        return [tuple(p) for p in P], list(range(n))
    if n == 2:
        return [tuple(P[0]), tuple(P[1])], [0, 1]

    # knots: centripetal, t_i = sum |dP|^alpha
    d = np.linalg.norm(np.diff(P, axis=0), axis=1)
    d = np.maximum(d, 1e-9)
    t = np.concatenate([[0.0], np.cumsum(d ** alpha)])

    # one-sided differences, then the non-uniform Catmull-Rom tangent
    m = np.zeros_like(P)
    for i in range(n):
        if i == 0:
            m[i] = (P[1] - P[0]) / (t[1] - t[0])
        elif i == n - 1:
            m[i] = (P[-1] - P[-2]) / (t[-1] - t[-2])
        else:
            dt0, dt1 = t[i] - t[i - 1], t[i + 1] - t[i]
            v0 = (P[i] - P[i - 1]) / dt0
            v1 = (P[i + 1] - P[i]) / dt1
            m[i] = (v0 * dt1 + v1 * dt0) / (dt0 + dt1)
    m *= 2.0 * tau          # tau=0.5 -> the textbook gain of 1.0

    pts = [tuple(P[0])]
    idx = [0]
    for i in range(n - 1):
        h = t[i + 1] - t[i]
        chord = d[i]
        # Hermite -> cubic Bezier handles, then leash each handle to the chord
        c1 = P[i] + m[i] * h / 3.0
        c2 = P[i + 1] - m[i + 1] * h / 3.0
        for c, anchor in ((c1, P[i]), (c2, P[i + 1])):
            v = c - anchor
            L = float(np.hypot(*v))
            if L > cap * chord and L > 1e-12:
                c[:] = anchor + v * (cap * chord / L)
        k = max(2, int(math.ceil(chord / step)) + 1)
        u = np.linspace(0.0, 1.0, k + 1)[1:]        # skip u=0, already placed
        b = ((1 - u) ** 3)[:, None] * P[i] \
            + (3 * (1 - u) ** 2 * u)[:, None] * c1 \
            + (3 * (1 - u) * u ** 2)[:, None] * c2 \
            + (u ** 3)[:, None] * P[i + 1]
        b[-1] = P[i + 1]                            # land exactly on the LED
        pts.extend(tuple(q) for q in b)
        idx.append(len(pts) - 1)
    return pts, idx


def self_intersections(pts):
    """How many times a sampled polyline crosses itself, non-adjacent only."""
    segs = [LineString([pts[i], pts[i + 1]]) for i in range(len(pts) - 1)
            if pts[i] != pts[i + 1]]
    if len(segs) < 3:
        return 0
    tree = STRtree(segs)
    hits = set()
    for i, s in enumerate(segs):
        for j in tree.query(s):
            j = int(j)
            if j <= i + 1:
                continue
            if s.intersects(segs[j]):
                hits.add((i, j))
    return len(hits)


def fit_line(P, knob, log, base=0):
    """Spline one path, walking tau down until the ribbon stops crossing.

    `base` is how many times the raw station polyline already crosses itself:
    the Oedo line is a lasso and genuinely does, so only crossings the spline
    *adds* are worth chasing.
    """
    tau = knob["tau"]
    first = None
    for attempt in range(9):
        pts, idx = catmull_rom(P, knob["alpha"], tau, knob["cap"])
        bad = max(0, self_intersections(pts) - base)
        if first is None:
            first = bad
        if bad == 0:
            if attempt:
                log.append((first, tau, attempt))
            return pts, idx, first, bad
        tau *= 0.8
    log.append((first, tau, 9))
    return pts, idx, first, bad


# --- build ------------------------------------------------------------------
def build(data_path, knob):
    d, MM, lines, _old_shapes, rings = SS.load(data_path)
    shapes = {}
    curves = []
    stats = dict(paths=0, legs=0, pts=0, base=0, naive=0, before=0, after=0,
                 fixed=[])
    for line in lines:
        per = {}
        for path in line["paths"]:
            # collapse repeats; the spline needs distinct knots
            ids = [s for s in path if s in MM]
            ids = [s for i, s in enumerate(ids) if i == 0 or s != ids[i - 1]]
            if len(ids) < 2:
                continue
            P = np.array([MM[s] for s in ids])
            # what the raw polyline already does, and what an unleashed
            # uniform Catmull-Rom would do, as the two reference points
            base = self_intersections([tuple(p) for p in P])
            naive, _ = catmull_rom(P, alpha=0.0, tau=knob["tau"], cap=1e9)
            stats["base"] += base
            stats["naive"] += max(0, self_intersections(naive) - base)
            log = []
            pts, idx, before, after = fit_line(P, knob, log, base)
            stats["paths"] += 1
            stats["before"] += before
            stats["after"] += after
            stats["fixed"].extend((line["id"],) + e for e in log)
            stats["pts"] += len(pts)
            curves.append((line["id"], list(ids), LineString(pts)))
            for k in range(len(ids) - 1):
                via = pts[idx[k] + 1:idx[k + 1]]
                per[f"{ids[k]}|{ids[k + 1]}"] = [(round(x, 3), round(y, 3))
                                                 for x, y in via]
                stats["legs"] += 1
        shapes[line["id"]] = per
    stats["bulge"], stats["foul"] = audit(MM, curves)
    straight = [(lid, ids, LineString([MM[s] for s in ids]))
                for lid, ids, _ in curves]
    stats["foul0"] = len(audit(MM, straight)[1])
    return MM, lines, shapes, rings, stats


# a 1.6 mm LED on a 2.2 mm copper keepout; a 0.25 mm silk track centred
# 1.1 mm away just clears the pad edge.
FOUL_MM = 1.1


def audit(MM, curves):
    """Worst swing off the straight polyline, and tracks fouling other LEDs.

    An interpolating spline cannot miss its own stations, so the failure mode
    that matters is a ribbon bulging sideways into a *different* station's
    pad. That is what gets measured here.
    """
    bulge = 0.0
    foul = []
    for lid, ids, curve in curves:
        mine = set(ids)
        for sid, (x, y) in MM.items():
            if sid in mine:
                continue
            dist = curve.distance(Point(x, y))
            if dist < FOUL_MM:
                foul.append((lid, sid, round(dist, 2)))
        # how far the curve wanders from the straight-line version
        chain = LineString([MM[s] for s in ids]) if len(ids) > 1 else None
        if chain is not None:
            for p in curve.coords:
                bulge = max(bulge, chain.distance(Point(p)))
    return bulge, sorted(foul, key=lambda r: r[2])


# --- the otemachi crop ------------------------------------------------------
def crop(out, MM, lines, shapes, rings, centre="otemachi", half=(55.0, 42.0),
         dpi=120, line_w=3.2):
    if centre not in MM:
        raise SystemExit(f"no station {centre!r}")
    cx, cy = MM[centre]
    hw, hh = half
    fig, ax = plt.subplots(figsize=(16, 16 * hh / hw), dpi=dpi)
    ax.set_facecolor(SS.MASK)
    for ring in rings:
        ax.fill([p[0] for p in ring], [p[1] for p in ring],
                color=SS.COPPER, lw=0, zorder=1)
    for line in lines:
        shape = shapes.get(line["id"], {})
        for path in line["paths"]:
            for a, b in zip(path, path[1:]):
                if a == b or a not in MM or b not in MM:
                    continue
                via = shape.get(f"{a}|{b}") or shape.get(f"{b}|{a}") or []
                pts = [MM[a]] + list(via) + [MM[b]]
                ax.plot([p[0] for p in pts], [p[1] for p in pts],
                        color=line["color"], lw=line_w, solid_capstyle="round",
                        zorder=2)
    for sid, (x, y) in MM.items():
        if abs(x - cx) < hw + 8 and abs(y - cy) < hh + 8:
            ax.plot(x, y, "o", ms=7, mfc="white", mec="#1a1a1a", mew=1.1,
                    zorder=3)
    ax.set_xlim(cx - hw, cx + hw)
    ax.set_ylim(cy + hh, cy - hh)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    plt.subplots_adjust(0, 0, 1, 1)
    plt.savefig(out, dpi=dpi, facecolor=SS.INK)
    plt.close(fig)
    print("wrote", os.path.normpath(out))


def report(tag, knob, stats):
    print(f"[{tag}] alpha={knob['alpha']} tau={knob['tau']} cap={knob['cap']} "
          f"paths={stats['paths']} legs={stats['legs']} "
          f"samples={stats['pts']}\n"
          f"       crossings: {stats['base']} inherent in the station order, "
          f"{stats['naive']} added by a naive uniform unleashed spline, "
          f"{stats['before']} added by this one, {stats['after']} left after "
          f"the tau walk\n"
          f"       max bulge off the straight chain {stats['bulge']:.2f} mm; "
          f"{len(stats['foul'])} track(s) within {FOUL_MM} mm of a foreign LED, "
          f"against {stats['foul0']} for the straight polyline")
    for lid, sid, dist in stats["foul"][:12]:
        print(f"       foul {lid} passes {dist} mm from {sid}")
    for rec in stats["fixed"]:
        print(f"       fixed {rec[0]}: {rec[1]} crossing(s), tau walked to "
              f"{rec[2]:.3f} in {rec[3]} step(s)")


def main():
    nat = os.path.join(HERE, "tokyo-natural.json")
    sch = os.path.join(HERE, "tokyo.json")

    MM, lines, shapes, rings, st = build(nat, GENTLE)
    report("natural/gentle", GENTLE, st)
    SS.render(
        os.path.join(OUT, "style-e-curves.png"),
        title="E - Smooth curves on true-scale land",
        notes=[
            "one centripetal Catmull-Rom per line, through every station",
            f"alpha 0.5, gain {GENTLE['tau']}, handles capped at "
            f"{GENTLE['cap']:.2f}x chord",
            f"{SAMPLE_MM} mm sampling, {st['pts']} points, bulge "
            f"{st['bulge']:.1f} mm max",
            f"{st['before']} self-crossings added; LED fouls "
            f"{len(st['foul'])} vs {st['foul0']} straight",
        ],
        MM=MM, lines=lines, shapes=shapes, rings=rings,
        line_w=2.4, station_ms=3.4)
    crop(os.path.join(OUT, "style-e-curves-core.png"), MM, lines, shapes, rings)
    SS.render(
        os.path.join(OUT, "style-e-curves-board.png"),
        title="E - Smooth curves, as etched",
        notes=[
            "white silkscreen on green mask, ENIG water",
            f"same spline: alpha 0.5, gain {GENTLE['tau']}, "
            f"cap {GENTLE['cap']:.2f}x chord",
            "0.25 mm tracks render at 2.4 pt here, so read shape not weight",
            f"{st['before']} spline-induced self-crossings",
        ],
        MM=MM, lines=lines, shapes=shapes, rings=rings,
        palette="board", line_w=2.4, station_ms=3.4, station="ring")

    MM2, lines2, shapes2, rings2, st2 = build(nat, STRONG)
    report("natural/strong", STRONG, st2)
    SS.render(
        os.path.join(OUT, "style-e-curves-strong.png"),
        title="E - Smooth curves on true-scale land (strong)",
        notes=[
            "same spline, tangents twice as long",
            f"alpha 0.5, gain {STRONG['tau']}, handles capped at "
            f"{STRONG['cap']:.2f}x chord",
            f"bulge {st2['bulge']:.1f} mm max, so it swings wide on short legs",
            f"{st2['before']} self-crossings added; LED fouls "
            f"{len(st2['foul'])} vs {st2['foul0']} straight",
        ],
        MM=MM2, lines=lines2, shapes=shapes2, rings=rings2,
        line_w=2.4, station_ms=3.4)

    MM3, lines3, shapes3, rings3, st3 = build(sch, GENTLE)
    report("schematic/gentle", GENTLE, st3)
    SS.render(
        os.path.join(OUT, "style-e-curves-schematic.png"),
        title="E - Smooth curves on octolinear positions",
        notes=[
            "the same spline over the solved octolinear stations",
            f"alpha 0.5, gain {GENTLE['tau']}, cap {GENTLE['cap']:.2f}x chord",
            "corners round off, but the straight runs waver",
            f"adds {st3['before']} self-crossings; {st3['base']} are the "
            f"Oedo lasso itself",
        ],
        MM=MM3, lines=lines3, shapes=shapes3, rings=rings3,
        line_w=2.4, station_ms=3.4)


if __name__ == "__main__":
    main()
