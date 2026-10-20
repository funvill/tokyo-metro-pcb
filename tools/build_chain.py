"""Work out the LED daisy-chain order, and write it into the data file.

    python -X utf8 build_chain.py ../input/tokyo-schematic-sq340.json \
        [--start shinagawa] [--rounds 40000] [--dry-run]

The runbook says the chain is hand-authored - "walk the network the way the
copper will: down a branch and back, not hopping across the board". That was
written for 68 and 73 LEDs. At 251 it is a travelling-salesman path, so it
is solved and then checked by eye against the same rule.

What the order has to be good at, in order:

1. **Total wire length**, because every millimetre is a track the board has
   to find room for between the LEDs, the labels and the bare-copper water.
2. **No long hops.** One 60 mm jump across the middle of the map is worse
   than ten extra millimetres spread over the whole chain: it has to cross
   every line in its way.
3. **Starting where the controller is.** The chain starts at the LED nearest
   the controller, so the data line does not begin with a trip across the
   board.

Method: nearest-neighbour from the start, then 2-opt and Or-opt until it
stops improving. Both moves keep it a path (not a loop) and keep the start
fixed. For 251 points that settles in seconds and lands within a few per
cent of optimal - which is far closer than a hand pass would get, and the
hand pass is still free to edit the result.
"""
import argparse
import io
import json
import math
import os
import random


def load(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


HOP_CAP_MM = 40.0     # a hop longer than this is charged for, hard
HOP_PENALTY = 6.0     # ... at this many millimetres per millimetre over


def edge(a, b):
    """One hop's cost: its length, plus a charge for being a long one."""
    d = math.dist(a, b)
    return d + (HOP_PENALTY * (d - HOP_CAP_MM) if d > HOP_CAP_MM else 0.0)


def tour_length(order, P):
    """What the chain costs to route, not merely how long it is.

    Priority 2 in this file's own docstring says a single long jump across
    the map is worse than ten millimetres spread over the whole chain -
    because that jump has to cross every line in its way. Summing raw
    distance does not say that, and it showed: optimising the organic
    layout for pure length cut the total 11% while pushing the worst hop
    from 72 mm to 117 mm, right across the middle of the board.

    Anything over HOP_CAP_MM is charged HOP_PENALTY times its excess, so
    the search will happily spend ten short millimetres to avoid one long
    one.
    """
    return sum(edge(P[order[i]], P[order[i + 1]])
               for i in range(len(order) - 1))


def nearest_neighbour(ids, P, start):
    left = set(ids)
    left.remove(start)
    order = [start]
    while left:
        here = P[order[-1]]
        nxt = min(left, key=lambda s: edge(here, P[s]))
        order.append(nxt)
        left.remove(nxt)
    return order


def two_opt(order, P, rounds=40000, seed=1):
    """2-opt and Or-opt, start fixed, path not loop."""
    rng = random.Random(seed)
    n = len(order)
    best = tour_length(order, P)
    stale = 0
    for _ in range(rounds):
        if stale > 4000:
            break
        if rng.random() < 0.65:
            # 2-opt: reverse order[i:j]
            i = rng.randrange(1, n - 1)
            j = rng.randrange(i + 1, n)
            a, b = P[order[i - 1]], P[order[i]]
            c = P[order[j]]
            d = P[order[j + 1]] if j + 1 < n else None
            before = edge(a, b) + (edge(c, d) if d else 0.0)
            after = edge(a, c) + (edge(b, d) if d else 0.0)
            if after < before - 1e-9:
                order[i:j + 1] = reversed(order[i:j + 1])
                best += after - before
                stale = 0
                continue
        else:
            # Or-opt: move a run of 1-3 stations somewhere else
            k = rng.randint(1, 3)
            i = rng.randrange(1, n - k)
            run = order[i:i + k]
            rest = order[:i] + order[i + k:]
            j = rng.randrange(1, len(rest))
            if j == i:
                stale += 1
                continue
            cand = rest[:j] + run + rest[j:]
            cl = tour_length(cand, P)
            if cl < best - 1e-9:
                order[:] = cand
                best = cl
                stale = 0
                continue
        stale += 1
    return order, best


def report(order, P, names):
    hops = [(math.dist(P[order[i]], P[order[i + 1]]), order[i], order[i + 1])
            for i in range(len(order) - 1)]
    hops.sort(reverse=True)
    total = sum(h[0] for h in hops)
    print(f"  chain: {len(order)} LEDs, {total:.0f} mm of data line, "
          f"mean hop {total / len(hops):.1f} mm")
    print("  longest hops:")
    for d, a, b in hops[:8]:
        print(f"    {d:5.1f} mm  {names.get(a, a)} -> {names.get(b, b)}")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--start", default=None,
                    help="station id the chain starts at; default the one "
                         "nearest the bottom-right corner, where the "
                         "controller goes")
    ap.add_argument("--rounds", type=int, default=40000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = load(args.path)
    B = d["board_scale"]
    P = {k: (v["x"] * B, v["y"] * B) for k, v in d["stations"].items()}
    names = {k: v.get("name", k) for k, v in d["stations"].items()}
    ids = sorted(P)
    W = d["canvas_mm"] * B
    H = d["canvas_h_mm"] * B
    start = args.start or min(ids, key=lambda s: math.dist(P[s], (W, H)))
    print(f"start: {names.get(start, start)}")

    order = nearest_neighbour(ids, P, start)
    print("nearest neighbour:")
    before = report(order, P, names)
    order, _ = two_opt(order, P, args.rounds)
    print("after 2-opt / Or-opt:")
    after = report(order, P, names)
    print(f"  {100 * (before - after) / before:.0f}% shorter")

    assert sorted(order) == ids, "the chain must visit every LED exactly once"
    if args.dry_run:
        print("dry run: not written")
        return
    d["chain"] = order
    with io.open(args.path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    print(f"wrote the chain into {os.path.basename(args.path)}")


if __name__ == "__main__":
    main()
