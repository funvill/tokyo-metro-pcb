"""Push labels out until their capsule clears every LED ring.

    python push_labels.py ../input/tokyo.json [--gap 0.15] [--max 3.0] [--write-overrides]

The station ring went from radius 0.63 to 1.65 when it turned out the small
one was printing as four arcs (60.7% of its ink sat on a pad's solder-mask
opening and the fab clips that away). The labels had been placed around the
small ring, so the big one swallowed them: 240 of 248 capsules overlapped a
ring.

Re-running the optimiser would fix it and throw away every hand placement.
This does not. Each offending label keeps its angle, its anchor and its
side, and is pushed straight out along its own direction - the smallest
change that respects what was chosen by hand. Labels that already clear are
not touched at all, and a leader label keeps its leader.

With --write-overrides the new dx/dy go back into label_overrides.json so
they survive the next rebuild (lesson B5: hand work lives in the override
file, not in tokyo.json).
"""
import argparse
import io
import json
import math
import os
import sys

from shapely.geometry import Point
from shapely.ops import unary_union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import capsules
import citymap

STEP = 0.05


def rings(city, scale, ring_r, ring_w):
    """Every LED's silk ring as a disc of its outer radius."""
    out = []
    for st in list(city.stations.values()) + city.extras:
        out.append(Point(st.x * scale, st.y * scale)
                   .buffer(ring_r + ring_w / 2.0, resolution=20))
    return unary_union(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city")
    ap.add_argument("--gap", type=float, default=0.15,
                    help="clear space to leave between capsule and ring")
    ap.add_argument("--max", type=float, default=3.0,
                    help="furthest a label may be pushed, mm")
    ap.add_argument("--ring-r", type=float, default=1.65)
    ap.add_argument("--ring-w", type=float, default=0.25)
    ap.add_argument("--write-overrides", action="store_true")
    args = ap.parse_args()

    city = citymap.load(args.city)
    scale = city.scale
    keep = rings(city, scale, args.ring_r, args.ring_w).buffer(args.gap)
    r_out = args.ring_r + args.ring_w / 2.0 + args.gap

    # Clearing a station's OWN ring is the requirement - that is the overlap
    # you see, the label sitting on its own LED. Clearing every OTHER ring
    # too is a preference: downtown the rings are 3.3 mm across and 2.8 mm
    # apart, so for 45 labels there is no distance along their own direction
    # that misses all of them, and pushing further only makes the label
    # point at the wrong station. So: push until it clears everything, and
    # if that is unreachable, settle for the smallest push that clears its
    # own ring.
    moved, partial, stuck = [], [], []
    for st in list(city.stations.values()) + city.extras:
        own = Point(st.x * scale, st.y * scale).buffer(r_out, resolution=20)
        if capsules.label_capsule(st, scale).disjoint(keep):
            continue
        dx0, dy0 = st.label.get("dx", 0.0), st.label.get("dy", 0.0)
        r0 = math.hypot(dx0, dy0)
        if r0 < 1e-6:
            stuck.append((st.id, "label is centred on the LED, nowhere to push"))
            continue
        ux, uy = dx0 / r0, dy0 / r0
        best_all = best_own = None
        steps = int(args.max / STEP)
        for k in range(1, steps + 1):
            st.label["dx"] = round(dx0 + ux * STEP * k, 2)
            st.label["dy"] = round(dy0 + uy * STEP * k, 2)
            cap = capsules.label_capsule(st, scale)
            if best_own is None and cap.disjoint(own):
                best_own = STEP * k
            if cap.disjoint(keep):
                best_all = STEP * k
                break
        if best_all is not None:
            st.label["dx"] = round(dx0 + ux * best_all, 2)
            st.label["dy"] = round(dy0 + uy * best_all, 2)
            moved.append((st.id, best_all))
        elif best_own is not None:
            st.label["dx"] = round(dx0 + ux * best_own, 2)
            st.label["dy"] = round(dy0 + uy * best_own, 2)
            partial.append((st.id, best_own))
        else:
            st.label["dx"], st.label["dy"] = dx0, dy0
            stuck.append((st.id, f"still on its own ring at +{args.max:g} mm"))

    print(f"{len(moved)} label(s) cleared of every ring, "
          f"{len(partial)} cleared of their own ring only, "
          f"{len(stuck)} not cleared")

    # Pushing labels out moves them INTO each other. Clearing the rings
    # alone left 16 capsules overlapping another capsule - two station
    # names printed on top of one another, which is worse than the overlap
    # being fixed. So repair those too: slide the label along its own
    # direction, in or out, to the nearest distance that clears its own
    # ring AND every other capsule. Several passes, because moving one
    # label changes its neighbours' problem.
    all_st = list(city.stations.values()) + city.extras
    cap = {s.id: capsules.label_capsule(s, scale) for s in all_st}
    by_id = {s.id: s for s in all_st}

    def overlaps(sid, shape):
        return [o for o in all_st if o.id != sid
                and shape.intersects(cap[o.id])
                and shape.intersection(cap[o.id]).area > 1e-3]

    fixed = 0
    for _ in range(4):
        clashing = [s.id for s in all_st if overlaps(s.id, cap[s.id])]
        if not clashing:
            break
        for sid in clashing:
            st = by_id[sid]
            if not overlaps(sid, cap[sid]):
                continue
            own = Point(st.x * scale, st.y * scale).buffer(r_out, resolution=20)
            dx0, dy0 = st.label.get("dx", 0.0), st.label.get("dy", 0.0)
            r0 = math.hypot(dx0, dy0)
            if r0 < 1e-6:
                continue
            ux, uy = dx0 / r0, dy0 / r0
            anchor0 = st.label.get("anchor", "start")
            flip = {"start": "end", "end": "start"}.get(anchor0)
            best = None
            # Sliding along its own direction cannot always escape - two
            # names on the same stretch of track just chase each other. So
            # also try the OTHER side of the LED: flipping the anchor and
            # mirroring dx/dy puts the same label on the far side, which is
            # still a placement the optimiser would have considered. Cost 1
            # for a flip so it is only taken when sliding fails.
            cands = [(anchor0, 1.0, 0)] + ([(flip, -1.0, 1)] if flip else [])
            for anchor, sgn, pen in cands:
                st.label["anchor"] = anchor
                for k in range(-int(1.0 / STEP), int(args.max / STEP) + 1):
                    st.label["dx"] = round(sgn * (dx0 + ux * STEP * k), 2)
                    st.label["dy"] = round(sgn * (dy0 + uy * STEP * k), 2)
                    c = capsules.label_capsule(st, scale)
                    if not c.disjoint(own):
                        continue
                    n = len(overlaps(sid, c))
                    score = (n, pen, abs(k))
                    if best is None or score < best[0]:
                        best = (score, anchor, st.label["dx"], st.label["dy"], c)
                    if n == 0:
                        break
                if best is not None and best[0][0] == 0:
                    break
            if best is None:
                st.label["anchor"] = anchor0
                st.label["dx"], st.label["dy"] = dx0, dy0
                continue
            _, st.label["anchor"], st.label["dx"], st.label["dy"], cap[sid] = best
            fixed += 1
    left = sum(1 for s in all_st if overlaps(s.id, cap[s.id]))
    print(f"capsule-on-capsule: {fixed} label(s) slid to clear a neighbour, "
          f"{left} still overlapping")
    if partial:
        print("  own-ring only: " + ", ".join(s for s, _ in partial[:8])
              + (" ..." if len(partial) > 8 else ""))
    if moved:
        far = sorted(moved, key=lambda m: -m[1])[:6]
        print("  furthest: " + ", ".join(f"{s} +{d:.2f}" for s, d in far))
    for s, why in stuck[:10]:
        print(f"  stuck: {s} - {why}")

    d = json.load(io.open(args.city, encoding="utf-8"))
    for sid, st in city.stations.items():
        if sid in d["stations"]:
            d["stations"][sid]["label"] = st.label
    json.dump(d, io.open(args.city, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {os.path.basename(args.city)}")

    if args.write_overrides:
        path = os.path.join(os.path.dirname(os.path.abspath(args.city)),
                            "label_overrides.json")
        ov = json.load(io.open(path, encoding="utf-8"))
        for sid, st in city.stations.items():
            if sid in ov:
                ov[sid]["label"] = st.label
        json.dump(ov, io.open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1, sort_keys=True)
        print(f"wrote {os.path.basename(path)} - the push survives a rebuild")


if __name__ == "__main__":
    main()
