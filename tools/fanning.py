"""Fan shared corridors into parallel strokes, the way a metro map does.

Drawing every line on its own centreline is honest and unreadable: once the
layout is strictly octolinear, eleven lines settle onto the same x through
the middle of Tokyo and draw as one bar 127 mm tall. Merging them into a
single stroke hides that eleven lines are there. Fanning them is what every
published map does.

Three things have to be right, and the obvious implementation gets all
three wrong:

* **The lane has to be stable.** Assign a lane per *segment* and a line hops
  sideways wherever the number of lines sharing the corridor changes, so it
  comes out in fragments. The lane is assigned once per corridor and held
  for every segment of that line in it.

* **The offset polyline has to stay joined.** Offsetting each segment on its
  own leaves a gap at every vertex where the direction changes. Each vertex
  is the intersection of its two neighbouring offset segments instead, which
  is ordinary polyline offsetting and closes them.

* **The track still has to reach the station.** An offset lane passes to one
  side of the station pad rather than touching it, which is what left
  Ikebukuro with the track stopping short on both sides. Each station gets a
  tick across the bundle, so every lane meets it.
"""
import math
from collections import defaultdict

# Two segments are the same corridor when they lie on the same infinite line
# to within these tolerances.
ANGLE_TOL_DEG = 6.0
MITER_MAX_MM = 1.6    # past this a corner is bevelled, not mitered
MIN_STEP_MM = 0.35    # shorter than this is a join artefact, not a line


def polylines(city):
    """(line_id, [points], [station id or None per point]) per path.

    Rebuilt here rather than taken from citymap.segments, which flattens
    every path of every line into one stream: the path boundaries are what
    says where a polyline ends, and without them the offset joins run across
    the gap between two unrelated paths.
    """
    out = []
    for line in city.lines:
        for path in line.paths:
            pts, owners = [], []
            for k, (a, b) in enumerate(zip(path, path[1:])):
                if a not in city.stations or b not in city.stations:
                    continue
                sa, sb = city.stations[a], city.stations[b]
                via = line.shape.get(f"{a}|{b}")
                if via is None and f"{b}|{a}" in line.shape:
                    via = line.shape[f"{b}|{a}"][::-1]
                seq = [(sa.x, sa.y)] + [tuple(p) for p in via or []]
                own = [a] + [None] * len(via or [])
                # owners is one entry per point and must stay that way:
                # dropping the station whenever the leg had via points
                # slid the two out of step, and every tick then spanned
                # the wrong station.
                if pts and pts[-1] == seq[0]:
                    seq, own = seq[1:], own[1:]
                pts.extend(seq)
                owners.extend(own)
                if k == len(path) - 2:
                    pts.append((sb.x, sb.y))
                    owners.append(b)
            if len(pts) >= 2:
                out.append((line.id, pts, owners))
    return out


def _corridor_key(p1, p2, tol):
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ang = math.atan2(dy, dx) % math.pi            # undirected
    c = -math.sin(ang) * p1[0] + math.cos(ang) * p1[1]
    return (round(math.degrees(ang) / ANGLE_TOL_DEG), round(c / tol))


def assign_lanes(lines, tol):
    """{(line_id, corridor): lane offset in multiples of the gap}.

    One lane per line per corridor, so the line holds that side of the band
    for as long as it stays in the corridor.
    """
    members = defaultdict(set)
    for lid, pts, _ in lines:
        for p1, p2 in zip(pts, pts[1:]):
            if p1 == p2:
                continue
            members[_corridor_key(p1, p2, tol)].add(lid)
    # Order the lanes by line degree, busiest first, and only then by name.
    # Sorting by name alone is arbitrary: it puts the Shinkansen wherever the
    # alphabet happens to land it, and a line's side of the band changes for
    # no reason the reader can see. Laying the trunk down first and letting
    # the quieter lines take the outside is what Bast, Brosi and Storandt do
    # (EuroVis 2020), and it keeps the busy lines together in the middle.
    degree = defaultdict(int)
    for key, lids in members.items():
        for lid in lids:
            degree[lid] += 1
    lanes = {}
    for key, lids in members.items():
        ordered = sorted(lids, key=lambda l: (-degree[l], l))
        n = len(ordered)
        for k, lid in enumerate(ordered):
            lanes[(lid, key)] = k - (n - 1) / 2
    return lanes


def _intersect(a1, a2, b1, b2):
    """Where the infinite lines a and b cross, or None if near-parallel."""
    d1x, d1y = a2[0] - a1[0], a2[1] - a1[1]
    d2x, d2y = b2[0] - b1[0], b2[1] - b1[1]
    den = d1x * d2y - d1y * d2x
    if abs(den) < 1e-9:
        return None
    t = ((b1[0] - a1[0]) * d2y - (b1[1] - a1[1]) * d2x) / den
    return (a1[0] + d1x * t, a1[1] + d1y * t)


def offset_polyline(pts, offs):
    """Offset pts, segment i by offs[i], joined at the vertex intersections.

    A straight run offsets to a straight run; a corner offsets to a corner.
    Offsetting the segments separately and drawing them as they fall is what
    opens a gap at every bend.
    """
    segs = []
    for i, (p1, p2) in enumerate(zip(pts, pts[1:])):
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        n = math.hypot(dx, dy)
        if n < 1e-9:
            segs.append(None)
            continue
        # The normal comes from the corridor's own undirected direction, not
        # from the way this line happens to run along it. Taking it from the
        # segment mirrors the lanes for any line traversing the corridor the
        # other way, so the two sets cross through each other instead of
        # lying side by side.
        ang = math.atan2(dy, dx) % math.pi
        nx, ny = -math.sin(ang), math.cos(ang)
        o = offs[i]
        segs.append(((p1[0] + nx * o, p1[1] + ny * o),
                     (p2[0] + nx * o, p2[1] + ny * o)))
    live = [s for s in segs if s]
    if not live:
        return []
    out = [live[0][0]]
    for a, b in zip(live, live[1:]):
        hit = _intersect(a[0], a[1], b[0], b[1])
        # A miter limit. Two segments that are nearly parallel but on
        # different lanes meet a very long way away, and mitering out to
        # that point is what turned every interchange into a starburst.
        if hit is None or math.dist(hit, a[1]) > MITER_MAX_MM:
            # One bevel point, not two. Emitting both ends put a short
            # segment at an odd angle into the path, and a dozen of those
            # radiating from one junction is the frayed "crushed spider"
            # at Ikebukuro, Shinjuku and Odaiba-kaihinkoen.
            out.append(((a[1][0] + b[0][0]) / 2, (a[1][1] + b[0][1]) / 2))
        else:
            out.append(hit)
    out.append(live[-1][1])

    # Drop the degenerate hops. Anything this short is a join artefact, and
    # at this scale it draws as a stub rather than as part of the line.
    clean = [out[0]]
    for q in out[1:]:
        if math.dist(q, clean[-1]) >= MIN_STEP_MM:
            clean.append(q)
    if len(clean) < 2:
        return out[:2]
    # the true end matters even if the last hop was short
    if clean[-1] != out[-1]:
        clean[-1] = out[-1]
    return clean


def build(city, tol, gap, gap_fn=None):
    """([(line_id, offset points)], {station id: (dir, lo, hi)}).

    The second is what each station needs to span: the direction of the
    bundle through it, and the lowest and highest lane offset arriving
    there, in millimetres.

    gap_fn(p1, p2) -> multiplier lets the lane pitch vary with position.
    It has to: thinning the lines in the congested centre while leaving the
    pitch at 0.85 mm makes the gap 2.4 times the line width there, so the
    band stays as wide as it ever was and the thinning buys far less than
    it should. The pitch belongs in proportion to the stroke.
    """
    lines = polylines(city)
    lanes = assign_lanes(lines, tol)
    drawn, ticks = [], defaultdict(lambda: ([], []))
    for lid, pts, owners in lines:
        offs = []
        for p1, p2 in zip(pts, pts[1:]):
            if p1 == p2:
                offs.append(0.0)
                continue
            g = gap * (gap_fn(p1, p2) if gap_fn else 1.0)
            offs.append(lanes.get((lid, _corridor_key(p1, p2, tol)), 0.0) * g)
        drawn.append((lid, offset_polyline(pts, offs)))
        # what arrives at each station, for the tick
        for i, sid in enumerate(owners):
            if sid is None:
                continue
            for j in (i - 1, i):              # the segments either side
                if 0 <= j < len(offs):
                    p1, p2 = pts[j], pts[j + 1]
                    if p1 == p2:
                        continue
                    ang = math.atan2(p2[1] - p1[1], p2[0] - p1[0]) % math.pi
                    ticks[sid][0].append(ang)
                    ticks[sid][1].append(offs[j])
    spans = {}
    for sid, (angs, os) in ticks.items():
        if not os:
            continue
        # Always span the pad. A station every one of whose lanes sits to
        # one side gets a tick that never reaches its own pad, which is why
        # Zoshigaya and Mejiro ended up with the dot sitting beside the
        # line instead of on it.
        lo, hi = min(min(os), 0.0), max(max(os), 0.0)
        if (hi - lo) < 1e-6:
            continue
        # the direction most of the bundle runs in, as a mean of unit
        # vectors doubled so that 0 and 180 degrees agree
        sx = sum(math.cos(2 * a) for a in angs)
        sy = sum(math.sin(2 * a) for a in angs)
        spans[sid] = (math.atan2(sy, sx) / 2, lo, hi)
    return drawn, spans
