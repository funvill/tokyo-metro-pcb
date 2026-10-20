"""Choose a label angle/anchor for every station so nothing collides.

The defaults follow the user's hand pass on the Montréal board (2026-10-13):
  * the label sits directly beside its station and level with it, about
    1.9 mm from the pad centre - right side first, then left
  * if the line is in the way it is nudged up or down, as little as will do
  * a run of stations keeps its labels on one side
  * on a level run the labels go below / above the stations, alternating
  * a leader line is the last resort
Text may sit right against its own line and pad ring (see check_fit).

Scoring, per candidate placement of one station (lower is better):
  * real collisions (label-label, label-dot, label-line, off-board) x 100
  * label-geo collisions (park hatch, copper water) x 60 - readable but
    ugly, so avoided when anything cleaner exists
  * angle not in the readable set {0, +-45, +-90}: x 3
  * any rotated label: +10 to +16 - horizontal text is preferred
  * angle differs from the previous station's on the same path: +2 -
    the eye tracks one direction along a corridor
  * a leader label: +40 plus 1/mm of leader length - last resort for the
    stations that have nowhere clean to sit next to their pad

Angles outside [-90, 90] render upside-down in KiCad (rigid rotation),
so those are never tried. Stations are placed in path order so the
consistency bonus chains along each corridor.

Usage:
    python auto_label.py [city.json] [--only sid,sid,...] [--fixed overrides.json]
                         [--parallel sid,sid]
"""
import argparse
import json
import math
import random

import citymap
import check_fit

PATH = "../input/tokyo.json"
ANGLES = [0, -45, 45, -90, 90, -60, 60, -30, 30, -75, 75]
LEADER_RING = [5.0, 7.0, 9.0, 12.0, 15.0, 18.0]
LEADER_DIRS = [(math.cos(math.radians(a)), math.sin(math.radians(a)))
               for a in range(0, 360, 22)]


def find_station(city, sid):
    if sid in city.stations:
        return city.stations[sid]
    return next(e for e in city.extras if e.id == sid)


def path_order(city):
    """Station ids in corridor order (each once) plus each one's
    predecessor on its path, for the consistency bonus."""
    order, prev = [], {}
    for line in city.lines:
        for path in line.paths:
            for a, b in zip([None] + path, path):
                if b not in prev:
                    prev[b] = a
                    order.append(b)
    for e in city.extras:
        if e.id not in prev:
            prev[e.id] = None
            order.append(e.id)
    return order, prev


def score(ctx, sid, prev_angle):
    cols = ctx.collisions_for(sid, getattr(ctx, "boxes", None))
    st = find_station(ctx.city, sid)
    s = 0
    for c in cols:
        s += {"label-geo": W_GEO, "label-line": W_LINE}.get(c.kind, W_COLLIDE)
    if st.label["angle"] not in (0, 45, -45, 90, -90):
        s += 3
    # left-to-right text wherever it fits: a rotated label costs about as
    # much as a leader, a vertical one more
    if st.label["angle"] != 0:
        s += W_ROT + abs(st.label["angle"]) / 15
    if prev_angle is not None and st.label["angle"] != prev_angle:
        s += 2
    s += position_cost(ctx, st)
    if st.label.get("leader"):
        # a leader is the last resort: dearer than any rotation, cheaper
        # only than a label on bare copper or a real collision
        s += W_LEADER + 1.0 * math.hypot(st.label["dx"], st.label["dy"])
        # in a cluster, leaders should fan outward: penalise a leader that
        # points toward the centroid of the neighbours within 9 mm
        near = [(o.x, o.y) for o in ctx.all_st
                if o.id != sid and math.hypot(o.x - st.x, o.y - st.y) * ctx.scale < 9.0]
        if near:
            mx = sum(p[0] for p in near) / len(near) - st.x
            my = sum(p[1] for p in near) / len(near) - st.y
            L = math.hypot(mx, my)
            dl = math.hypot(st.label["dx"], st.label["dy"])
            if L > 1e-6 and dl > 1e-6:
                toward = (mx / L) * (st.label["dx"] / dl) + (my / L) * (st.label["dy"] / dl)
                s += 8 * (toward + 1)     # 0 when pointing straight away, 16 toward
    if st.label.get("short"):
        s += 8
    return s


# The scoring weights, exposed so the trade can be swept rather than argued
# about. The optimiser converges by pass 2, so the only way past the floor
# it reaches is to change these, not to search harder.
W_COLLIDE = 100.0  # label on a label, a pad, or off the board
W_LINE = 0.0       # label lying on a route. Not a fault: every label is
                   # drawn in a capsule that knocks the route out behind it.
                   # It was the commonest "collision" by far, and at 100 it
                   # was what drove most of the rotations and leaders.
W_GEO = 60.0       # label over the bare-copper water
W_ROT = 150.0      # a rotated label. Deliberately DEARER than the water:
                   # the order of preference is a name on the track first,
                   # then on the water, and only then turned on its side.
                   # Horizontal text is what makes the map readable; a name
                   # crossing a river still reads, a vertical one barely
                   # does.
W_LEADER = 40.0    # the fixed part of a leader's cost, plus 1 per mm

NUDGE = 0.45       # a small step up or down from level, mm
PREV = {}          # station id -> previous station on its path (set in main)


def level_run(ctx, st):
    """True if the station's neighbours on its line sit at the same height:
    labels beside it would run into them, so they go above / below instead."""
    near = [o for o in ctx.all_st if o.id != st.id
            and abs(o.y - st.y) * ctx.scale < 0.3 and abs(o.x - st.x) * ctx.scale < 9.0]
    return bool(near)


def position_cost(ctx, st):
    """How far a placement is from the preferred one: beside and level, on
    the right, on the same side as the previous station of the run."""
    pos = position(st.label)
    if pos == "other":
        return 0                                # rotation / leader are costed separately
    cost = 0.0
    if pos in ("above", "below"):
        if not level_run(ctx, st):
            cost += 6
        prev = PREV.get(st.id)
        if prev and position(find_station(ctx.city, prev).label) == pos:
            cost += 2                           # alternate: not the same as the last one
        return cost
    if level_run(ctx, st):
        cost += 4                               # beside, on a level run: usually collides anyway
    side = pos.split("-")[1]
    cost += 0 if side == "right" else 1.5
    cost += min(abs(st.label.get("dy", 0)) / NUDGE, 4) * 0.6     # level 0, nudge 0.6, raised ~1.2-2.4
    prev = PREV.get(st.id)
    if prev:
        ppos = position(find_station(ctx.city, prev).label)
        if "-" in ppos and ppos.split("-")[1] != side:
            cost += 1.5                         # keep a run on one side
    return cost


def position(label):
    """Where a horizontal, leaderless label sits relative to its station."""
    if label.get("angle", 0) != 0 or label.get("leader"):
        return "other"                      # costed separately
    dx, dy = label.get("dx", 0), label.get("dy", 0)
    if label.get("anchor") == "start" or (label.get("anchor") == "center" and dx > 0.6):
        side = "right"
    elif label.get("anchor") == "end" or dx < -0.6:
        side = "left"
    else:
        return "above" if dy < 0 else "below"
    return ("upper-" if dy < -0.3 else "lower-" if dy > 0.3 else "middle-") + side


def candidates(st):
    for short in (False, True):
        if short and st.short == st.name:
            continue
        # beside the pad first: level, then nudged, then a full step up / down
        keep = st.label
        st.label = {"short": True} if short else {}
        n_lines = len(citymap.display_lines(st))
        st.label = keep
        rise = round((citymap.BOX_H + (n_lines - 1) * citymap.LINE_PITCH) * citymap.TEXT_H / 2 + 0.2, 2)
        for dy in (0.0, -NUDGE, NUDGE, -2 * NUDGE, 2 * NUDGE, -rise, rise):
            for anchor, dx in (("start", citymap.LABEL_STANDOFF), ("end", -citymap.LABEL_STANDOFF)):
                yield {"angle": 0, "anchor": anchor, "dx": dx, "dy": dy,
                       **({"short": True} if short else {})}
        for angle in ANGLES:
            for anchor in ("start", "end"):
                dx, dy = citymap.label_offset(angle, anchor)
                yield {"angle": angle, "anchor": anchor, "dx": dx, "dy": dy,
                       **({"short": True} if short else {})}
                # the same text shifted sideways so it runs *beside* the
                # pad (and its own line) instead of away from it - the
                # only way a label fits along a corridor of stations
                a = math.radians(angle)
                nx, ny = -math.sin(a) * 1.9, math.cos(a) * 1.9
                for sgn in (1, -1):
                    yield {"angle": angle, "anchor": anchor,
                           "dx": round(dx * 0.4 + nx * sgn, 2),
                           "dy": round(dy * 0.4 + ny * sgn, 2),
                           **({"short": True} if short else {})}
        # horizontal text hugging the pad with no leader: above / below
        # (centred, or slid left / right), and tucked into each corner
        keep = st.label
        st.label = {"short": True} if short else {}
        lines = citymap.display_lines(st)
        st.label = keep
        h = (citymap.BOX_H + (len(lines) - 1) * citymap.LINE_PITCH) * citymap.TEXT_H
        w = max(len(t) for t in lines) * citymap.CHAR_W * citymap.TEXT_H
        for sgn in (-1, 1):
            # clear of the label's own pad keepout, as check_fit measures it
            dy = round(sgn * (check_fit.OWN_R + 0.1 + h / 2), 2)
            for dx in (0.0, w / 4, -w / 4, w / 2, -w / 2):
                yield {"angle": 0, "anchor": "center", "dx": round(dx, 2), "dy": dy,
                       **({"short": True} if short else {})}
        for r in LEADER_RING:
            for ux, uy in LEADER_DIRS:
                anchor = "end" if ux < -0.05 else "start"
                yield {"angle": 0, "anchor": anchor, "dx": round(ux * r, 2),
                       "dy": round(uy * r, 2), "leader": True,
                       **({"short": True} if short else {})}


def best_label(ctx, sid, prev_angle, exclude=None):
    st = find_station(ctx.city, sid)
    best = None
    for cand in candidates(st):
        if exclude and cand in exclude:
            continue
        st.label = cand
        s = score(ctx, sid, prev_angle)
        if best is None or s < best[0]:
            best = (s, dict(cand))
        if s == 0:
            break
    st.label = best[1]
    return best


def anneal(ctx, prev, d, iters=40000, t0=60.0, t1=0.5, seed=1, only=None):
    """Simulated annealing over every label: propose one station's label
    from its candidate list, accept by the change in that station's score
    (its collisions are symmetric, so this tracks the total), cooling
    geometrically. Finds the joint layouts greedy placement can't."""
    rng = random.Random(seed)
    all_st = ctx.all_st
    cands = {st.id: list(candidates(st)) for st in all_st}
    boxes = {st.id: ctx.box(st) for st in all_st}
    ctx.boxes = boxes

    def sc(sid):
        pa = find_station(ctx.city, prev[sid]).label["angle"] if prev.get(sid) else None
        return score(ctx, sid, pa)

    # with --only, every other label (hand-placed ones included) stays put
    movable = [st for st in all_st if not only or st.id in only]
    cur = {st.id: sc(st.id) for st in all_st}
    total = sum(cur.values())
    best_total, best = total, {st.id: dict(st.label) for st in all_st}
    for i in range(iters):
        t = t0 * (t1 / t0) ** (i / iters)
        st = movable[rng.randrange(len(movable))]
        old_label, old_s = st.label, cur[st.id]
        st.label = rng.choice(cands[st.id])
        boxes[st.id] = ctx.box(st)
        new_s = sc(st.id)
        delta = new_s - old_s
        if delta <= 0 or rng.random() < math.exp(-delta / t):
            cur[st.id] = new_s
            total += delta
            if total < best_total:
                best_total, best = total, {s.id: dict(s.label) for s in all_st}
        else:
            st.label = old_label
            boxes[st.id] = ctx.box(st)
        if i % 5000 == 0:
            print(f"anneal {i}: T={t:.1f} total={total:.0f} best={best_total:.0f}")
    for st in all_st:
        st.label = best[st.id]
        boxes[st.id] = ctx.box(st)
        target = d["stations"].get(st.id) or next(e for e in d["extras"] if e["id"] == st.id)
        target["label"] = st.label
    ctx.boxes = None
    return best_total


def polish(ctx, prev, d, only=None, rounds=8):
    """Annealing ends warm - plenty of stations are left on a leader or a
    rotation with a free horizontal spot right beside them. Re-place each
    station greedily against the settled neighbours until nothing improves."""
    def pa(sid):
        return find_station(ctx.city, prev[sid]).label["angle"] if prev.get(sid) else None

    for r in range(rounds):
        before = sum(score(ctx, st.id, pa(st.id)) for st in ctx.all_st)
        for st in ctx.all_st:
            if only and st.id not in only:
                continue
            keep, was = dict(st.label), score(ctx, st.id, pa(st.id))
            s, label = best_label(ctx, st.id, pa(st.id))
            if s >= was:
                st.label = keep
                continue
            target = d["stations"].get(st.id) or next(e for e in d["extras"] if e["id"] == st.id)
            target["label"] = label
        after = sum(score(ctx, st.id, pa(st.id)) for st in ctx.all_st)
        print(f"polish {r}: total {before:.0f} -> {after:.0f}")
        if after >= before:
            break


def parallel_leaders(ctx, d, sids):
    """One leader offset shared by a group of stations, so their leaders run
    parallel: the shortest offset that leaves none of them colliding."""
    sts = [find_station(ctx.city, sid) for sid in sids]
    best = None
    for dx10 in range(-90, 91, 5):
        for dy10 in range(-90, 91, 5):
            dx, dy = dx10 / 10, dy10 / 10
            length = math.hypot(dx, dy)
            if length < 3.5 or (best and length >= best[0]):
                continue
            keep = [st.label for st in sts]
            for st in sts:
                st.label = {"angle": 0, "anchor": "end" if dx < 0 else "start",
                            "dx": dx, "dy": dy, "leader": True}
            if not any(ctx.collisions_for(st.id) for st in sts):
                best = (length, [dict(st.label) for st in sts])
            for st, k in zip(sts, keep):
                st.label = k
    if not best:
        print(f"  no collision-free parallel leaders for {sids}")
        return
    for st, label in zip(sts, best[1]):
        st.label = label
        d["stations"][st.id]["label"] = label
    print(f"  parallel leaders for {sids}: offset ({best[1][0]['dx']}, {best[1][0]['dy']}) mm")


def real_collisions(ctx):
    return [c for c in check_fit.find_collisions(ctx.city, ctx.scale)
            if c.kind != "label-geo"]


def repair(ctx, prev, d, rounds=40):
    """Greedy placement leaves collisions made by later neighbours: keep
    re-placing every station in a remaining collision (its previous choice
    barred, so a pair can't just swap back and forth) until clean."""
    tried = {}
    for r in range(rounds):
        cols = real_collisions(ctx)
        if not cols:
            return True
        involved = sorted({c.a for c in cols} | {c.b for c in cols if c.b in ctx.city.stations
                                                  or c.b in {e.id for e in ctx.city.extras}})
        for sid in involved:
            st = find_station(ctx.city, sid)
            tried.setdefault(sid, []).append(dict(st.label))
            pa = find_station(ctx.city, prev[sid]).label["angle"] if prev.get(sid) else None
            _, label = best_label(ctx, sid, pa, exclude=tried[sid][-6:])
            target = d["stations"].get(sid) or next(e for e in d["extras"] if e["id"] == sid)
            target["label"] = label
        print(f"repair {r}: {len(cols)} collision(s) -> {involved}")
    return False


def main():
    global W_LEADER, W_ROT, W_COLLIDE, W_LINE, W_GEO
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=PATH, help="city data file")
    ap.add_argument("--only", default="",
                    help="comma-separated station ids to (re)place; default all")
    ap.add_argument("--fixed", default="",
                    help="JSON file {station id: {label, wrap?}}: hand placements. They are "
                         "applied first and never moved; everything else works round them")
    ap.add_argument("--parallel", action="append", default=[], metavar="SID,SID,...",
                    help="give these stations leader lines that run parallel (same "
                         "offset from each pad); repeatable")
    ap.add_argument("--wrap-over", type=int, default=None, metavar="N",
                    help="set a name on two lines once it is longer than N "
                         "characters (citymap default 13). A wider single "
                         "line used to be expensive because it hit more "
                         "routes; with capsule knockouts it is not")
    ap.add_argument("--text-h", type=float, default=None, metavar="MM",
                    help="label height, overriding citymap.TEXT_H (1.1). "
                         "Smaller text is the only geometric lever that "
                         "moves the unlabellable count, and it moves it "
                         "less than saying less does")
    ap.add_argument("--w-geo", type=float, default=W_GEO,
                    help="cost of a label over bare-copper water (default "
                         "60). Silkscreen will not print on a mask opening, "
                         "and a name in the river reads as a mistake, so "
                         "the preference is firmly for the track instead")
    ap.add_argument("--w-line", type=float, default=W_LINE,
                    help="cost of a label lying on a route (default 100). "
                         "With capsule knockouts this is no longer a fault: "
                         "pass 0 and the optimiser stops rotating and "
                         "leadering to avoid something that now prints fine")
    ap.add_argument("--w-leader", type=float, default=W_LEADER,
                    help="fixed cost of a leader line (default 40). Lower it "
                         "and more labels take a leader instead of lying on "
                         "a route")
    ap.add_argument("--w-rot", type=float, default=W_ROT,
                    help="fixed cost of a rotated label (default 10). Lower "
                         "it and more labels turn to follow their line")
    ap.add_argument("--w-collide", type=float, default=W_COLLIDE,
                    help="cost of a real collision (default 100)")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--iters", type=int, default=40000)
    args = ap.parse_args()
    W_LEADER, W_ROT, W_COLLIDE = args.w_leader, args.w_rot, args.w_collide
    W_LINE, W_GEO = args.w_line, args.w_geo
    if args.text_h:
        citymap.TEXT_H = args.text_h
    if args.wrap_over:
        citymap.WRAP_OVER = args.wrap_over
    only = set(filter(None, args.only.split(",")))

    d = json.load(open(args.path, encoding="utf-8"))
    city = citymap.load(args.path)
    ctx = check_fit.Context(city, city.scale, citymap.TEXT_H, False)
    order, prev = path_order(city)
    PREV.update(prev)
    fixed = json.load(open(args.fixed, encoding="utf-8")) if args.fixed else {}
    for sid, entry in fixed.items():
        entry = entry if "label" in entry else {"label": entry}
        st = find_station(city, sid)
        st.label = dict(entry["label"])
        d["stations"][sid]["label"] = dict(entry["label"])
        if "wrap" in entry:
            st.wrap = entry["wrap"]
            d["stations"][sid]["wrap"] = entry["wrap"]
    if fixed:
        only = (only or set(order)) - set(fixed)
    for p in range(args.passes):
        total = 0
        for sid in order:
            if only and sid not in only:
                continue
            pa = find_station(city, prev[sid]).label["angle"] if prev[sid] else None
            s, label = best_label(ctx, sid, pa)
            total += s
            target = d["stations"].get(sid)
            if target is None:
                target = next(e for e in d["extras"] if e["id"] == sid)
            target["label"] = label
        print(f"pass {p}: total score {total:.0f}")
    anneal(ctx, prev, d, iters=args.iters, only=only)
    polish(ctx, prev, d, only)
    for group in args.parallel:
        parallel_leaders(ctx, d, group.split(","))
    json.dump(d, open(args.path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    cols = real_collisions(ctx)
    print(f"remaining real collisions: {len(cols)}")
    for c in cols:
        print(" ", c.kind, c.a, c.b)
    leaders = [s.id for s in list(city.stations.values()) + city.extras
               if s.label.get("leader")]
    print(f"leader labels: {leaders}")


if __name__ == "__main__":
    main()
