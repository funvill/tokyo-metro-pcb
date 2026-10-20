"""Style D: the schematic, with shared corridors drawn side by side.

    python -X utf8 style_d_offset.py [--gap 1.6]

The schematic solve puts both lines of a shared run on exactly the same
centreline, so the second colour is painted over by the first and vanishes:
Fukutoshin disappears under Yurakucho for eight legs in the north-west,
Namboku under Mita at Shirokanedai, and so on. This is a **drawing** change
only - no station moves. Every leg carried by more than one line is found
from the data, consecutive shared legs are chained into corridors, and each
line's drawn track is pushed sideways off the true centreline by a constant
gap, symmetric about it, with a stable left-to-right order along the whole
corridor so a line never swaps sides halfway.

Where a corridor ends, the offset tapers back to zero over the last few
millimetres so both tracks visibly land on the one LED that is physically
there. The rounded bends are rebuilt with `build_tokyo.fillet()` over the
offset anchors, so the corners look exactly as they do in style A.

Writes ../test-results/style-d-offset.png (line colours),
       ../test-results/style-d-offset-board.png (white silk on green mask),
       ../test-results/style-d-offset-crop.png (one corridor, zoomed).
"""
import argparse
import io
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import style_sheet
from build_tokyo import fillet, BEND_MM

DATA = os.path.join(HERE, "tokyo.json")
OUT = os.path.join(HERE, "..", "test-results")
TAPER_MM = 3.0          # how far back from the LED the tracks converge
TAPER_FRAC = 0.40       # ... never more than this much of a short leg


# --- finding the corridors --------------------------------------------------
def shared_legs(lines):
    """{(a, b): [line ids]} for every leg carried by more than one line."""
    carried = {}
    for line in lines:
        for path in line["paths"]:
            for a, b in zip(path, path[1:]):
                if a == b:
                    continue
                key = (a, b) if a < b else (b, a)
                carried.setdefault(key, [])
                if line["id"] not in carried[key]:
                    carried[key].append(line["id"])
    return {k: sorted(v) for k, v in carried.items() if len(v) > 1}


def corridors(shared):
    """Chain consecutive shared legs that carry the same set of lines.

    One corridor is an ordered run of stations plus the line ids on it. The
    order is fixed by the lexicographically smallest end, so the left normal
    is the same all the way along and nobody swaps sides.
    """
    by_group = {}
    for key, ids in shared.items():
        by_group.setdefault(tuple(ids), []).append(key)
    out = []
    for ids, legs in sorted(by_group.items()):
        adj = {}
        for a, b in legs:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        seen = set()
        starts = sorted(s for s in adj if len(adj[s]) == 1) or sorted(adj)
        for s in starts:
            if s in seen:
                continue
            run, cur, prev = [s], s, None
            seen.add(s)
            while True:
                nxt = sorted(n for n in adj[cur] if n != prev and n not in seen)
                if not nxt:
                    break
                prev, cur = cur, nxt[0]
                seen.add(cur)
                run.append(cur)
            if len(run) > 1:
                if run[-1] < run[0]:
                    run.reverse()
                out.append({"stations": run, "lines": list(ids)})
    return out


def leg_offsets(cors, MM, gap):
    """{(leg, line id): (dx, dy)} - where each line's track is drawn.

    The offsets are symmetric about the true centreline and the order of the
    lines is the sorted order of their ids, held for the whole corridor.
    """
    off, which = {}, {}
    for ci, cor in enumerate(cors):
        ids = cor["lines"]
        n = len(ids)
        for a, b in zip(cor["stations"], cor["stations"][1:]):
            ax, ay = MM[a]
            bx, by = MM[b]
            L = math.hypot(bx - ax, by - ay) or 1.0
            nx, ny = -(by - ay) / L, (bx - ax) / L      # left of a -> b
            key = (a, b) if a < b else (b, a)
            for k, lid in enumerate(ids):
                d = (k - (n - 1) / 2.0) * gap
                off[(key, lid)] = (nx * d, ny * d)
                which[(key, lid)] = ci
    return off, which


# --- drawing ----------------------------------------------------------------
def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1.0
    return dx / L, dy / L, L


def _miter(p, d1, o1, d2, o2):
    """Where the two offset lines through p meet (fallback: average)."""
    det = d1[0] * (-d2[1]) - d1[1] * (-d2[0])
    if abs(det) > 1e-6:
        rx = (p[0] + o2[0]) - (p[0] + o1[0])
        ry = (p[1] + o2[1]) - (p[1] + o1[1])
        t = (rx * (-d2[1]) - ry * (-d2[0])) / det
        if abs(t) < 12.0:
            return (p[0] + o1[0] + d1[0] * t, p[1] + o1[1] + d1[1] * t)
    return (p[0] + (o1[0] + o2[0]) / 2, p[1] + (o1[1] + o2[1]) / 2)


def anchors_for(path, MM, off, which, lid):
    """The drawn polyline's corners for one line along one of its paths."""
    pts, legs = [], []
    for a, b in zip(path, path[1:]):
        if a == b:
            continue
        legs.append((a, b))
    if not legs:
        return []
    out = []
    for i, (a, b) in enumerate(legs):
        key = (a, b) if a < b else (b, a)
        o = off.get((key, lid), (0.0, 0.0))
        c = which.get((key, lid))
        legs[i] = (a, b, o, c)

    def taper(p, dx, dy, L):
        t = min(TAPER_MM, TAPER_FRAC * L)
        return (p[0] + dx * t, p[1] + dy * t)

    a0, b0, o0, c0 = legs[0]
    dx, dy, L = _unit(MM[a0], MM[b0])
    if o0 == (0.0, 0.0):
        out.append(MM[a0])
    else:                                   # start of a corridor: converge
        out.append(MM[a0])
        p = taper(MM[a0], dx, dy, L)
        out.append((p[0] + o0[0], p[1] + o0[1]))
    for i in range(len(legs) - 1):
        a, b, o1, c1 = legs[i]
        _, c, o2, c2 = legs[i + 1]
        d1 = _unit(MM[a], MM[b])
        d2 = _unit(MM[b], MM[c])
        if c1 == c2:
            # Same corridor (or neither): carry straight through. Inside a
            # corridor the normal turns with the bend, so the two offsets
            # differ and the corner is mitred.
            if c1 is None:
                out.append(MM[b])
            else:
                out.append(_miter(MM[b], d1[:2], o1, d2[:2], o2))
        else:                               # corridor edge: land on the LED
            if o1 != (0.0, 0.0):
                p = taper(MM[b], -d1[0], -d1[1], d1[2])
                out.append((p[0] + o1[0], p[1] + o1[1]))
            out.append(MM[b])
            if o2 != (0.0, 0.0):
                p = taper(MM[b], d2[0], d2[1], d2[2])
                out.append((p[0] + o2[0], p[1] + o2[1]))
    a1, b1, o1, c1 = legs[-1]
    dx, dy, L = _unit(MM[a1], MM[b1])
    if o1 != (0.0, 0.0):
        p = taper(MM[b1], -dx, -dy, L)
        out.append((p[0] + o1[0], p[1] + o1[1]))
    out.append(MM[b1])
    return out


def rounded(pts, radius=BEND_MM):
    """The same rounded bends build_tokyo draws, over these corners."""
    if len(pts) < 3:
        return list(pts)
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        arc = fillet(pts[k - 1], pts[k], pts[k + 1], radius)
        out.extend(arc if arc else [pts[k]])
    out.append(pts[-1])
    return out


class TrackMap(dict):
    """Station positions for the dots, plus hidden ends for the tracks.

    `style_sheet.render` looks tracks up with `MM[a]` but draws a dot for
    every key `MM.items()` yields, so the synthetic endpoints live off to
    the side and never grow a dot.
    """

    def __init__(self, real):
        super().__init__(real)
        self.extra = {}

    def __contains__(self, k):
        return dict.__contains__(self, k) or k in self.extra

    def __getitem__(self, k):
        if dict.__contains__(self, k):
            return dict.__getitem__(self, k)
        return self.extra[k]


def build_tracks(lines, MM, off, which):
    """-> (TrackMap, render-ready line records, shapes) for the offset draw."""
    track = TrackMap(MM)
    out_lines, shapes = [], {}
    for line in lines:
        lid = line["id"]
        paths, shape = [], {}
        for pi, path in enumerate(line["paths"]):
            pts = rounded(anchors_for(path, MM, off, which, lid))
            if len(pts) < 2:
                continue
            a, b = f"~{lid}~{pi}~a", f"~{lid}~{pi}~b"
            track.extra[a], track.extra[b] = pts[0], pts[-1]
            paths.append([a, b])
            shape[f"{a}|{b}"] = pts[1:-1]
        rec = dict(line)
        rec["paths"] = paths
        out_lines.append(rec)
        shapes[lid] = shape
    return track, out_lines, shapes


def crop(out, title, track, lines, shapes, rings, centre, half, dpi=130):
    """A zoomed window on one corridor, written here rather than in the tool."""
    cx, cy = centre
    hw, hh = half
    fig, ax = plt.subplots(figsize=(14, 14 * hh / hw), dpi=dpi)
    fig.patch.set_facecolor(style_sheet.INK)
    ax.set_facecolor(style_sheet.MASK)
    for ring in rings:
        ax.fill([p[0] for p in ring], [p[1] for p in ring],
                color=style_sheet.COPPER, lw=0, zorder=1)
    for line in lines:
        shape = shapes.get(line["id"], {})
        for a, b in line["paths"]:
            pts = [track[a]] + list(shape.get(f"{a}|{b}", [])) + [track[b]]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], color=line["color"],
                    lw=5.0, solid_capstyle="round", zorder=2)
    for sid, (x, y) in track.items():
        if abs(x - cx) < hw + 6 and abs(y - cy) < hh + 6:
            ax.plot(x, y, "o", ms=9, mfc="white", mec="#1a1a1a", mew=1.2, zorder=3)
            ax.text(x + 0.8, y - 0.8, sid, fontsize=8, color="white", zorder=4)
    ax.set_xlim(cx - hw, cx + hw)
    ax.set_ylim(cy + hh, cy - hh)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, color="white", fontsize=13, pad=8)
    fig.subplots_adjust(0.01, 0.01, 0.99, 0.94)
    plt.savefig(out, dpi=dpi, facecolor=style_sheet.INK)
    plt.close(fig)
    print("wrote", os.path.normpath(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap", type=float, default=1.6,
                    help="mm between neighbouring tracks in a corridor")
    ap.add_argument("--suffix", default="")
    ap.add_argument("--zoom", default=None,
                    help="crop this corridor instead of the longest one, by "
                         "any station id on it")
    args = ap.parse_args()

    d, MM, lines, _old_shapes, rings = style_sheet.load(DATA)
    shared = shared_legs(lines)
    cors = corridors(shared)
    print(f"{len(shared)} shared legs -> {len(cors)} corridors:")
    for c in cors:
        print(f"  {'+'.join(c['lines']):28s} "
              f"{len(c['stations']) - 1} leg(s): {' .. '.join(c['stations'])}")
    off, which = leg_offsets(cors, MM, args.gap)
    track, out_lines, shapes = build_tracks(lines, MM, off, which)

    sfx = args.suffix
    notes = [f"{len(cors)} corridors, {len(shared)} shared legs offset",
             f"{args.gap:.1f} mm between tracks, symmetric about the centreline",
             f"tapered back over {TAPER_MM:.0f} mm so both tracks reach the LED",
             "stations unmoved; bends still filleted at 2.0 mm"]
    title = "D - Schematic with parallel corridors offset"
    style_sheet.render(os.path.join(OUT, f"style-d-offset{sfx}.png"), title=title,
                       notes=notes, MM=track, lines=out_lines, shapes=shapes,
                       rings=rings, palette="colour")
    style_sheet.render(os.path.join(OUT, f"style-d-offset-board{sfx}.png"),
                       title=title + " (board)", notes=notes, MM=track,
                       lines=out_lines, shapes=shapes, rings=rings,
                       palette="board")

    # zoom: the longest corridor, Yurakucho + Fukutoshin in the north-west
    if args.zoom:
        big = next(c for c in cors if args.zoom in c["stations"])
    else:
        big = max(cors, key=lambda c: len(c["stations"]))
    xs = [MM[s][0] for s in big["stations"]]
    ys = [MM[s][1] for s in big["stations"]]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    hw = max(18.0, (max(xs) - min(xs)) / 2 + 10)
    hh = max(12.0, (max(ys) - min(ys)) / 2 + 10)
    crop(os.path.join(OUT, f"style-d-offset-crop{sfx}.png"),
         f"{' + '.join(big['lines'])} - {args.gap:.1f} mm apart, "
         f"{' .. '.join([big['stations'][0], big['stations'][-1]])}",
         track, out_lines, shapes, rings, (cx, cy), (hw, hh))


if __name__ == "__main__":
    main()
