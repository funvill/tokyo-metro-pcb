"""Remove hairpin spikes from the track alignments.

Cutting a leg out of a merged rail line occasionally leaves a point that
the line runs out to and comes straight back from - a 176 degree turn, out
three millimetres and back under one. It draws as a short stub with a
rounded cap hanging in mid air beside the station, which is what it looks
like next to Osaki.

A reversal is never real track. A tight curve is: the Yurikamome's spiral
onto the Rainbow Bridge turns about 125 degrees over 0.3 mm legs and must
survive, so the threshold is set well above that.

    python despike.py ../input/tokyo.json [--limit 150]
"""
import argparse
import io
import json
import math


def turn(a, b, c):
    v1 = (b[0] - a[0], b[1] - a[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-12 or n2 < 1e-12:
        return 0.0
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def despike(full, limit):
    """Drop interior points that the line reverses at. Returns (pts, n)."""
    removed = 0
    changed = True
    while changed and len(full) > 2:
        changed = False
        for i in range(1, len(full) - 1):
            if turn(full[i - 1], full[i], full[i + 1]) > limit:
                del full[i]
                removed += 1
                changed = True
                break
    return full, removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--limit", type=float, default=135.0,
                    help="a turn sharper than this is a reversal, not a curve")
    args = ap.parse_args()

    d = json.load(io.open(args.path, encoding="utf-8"))
    s = d.get("board_scale", 2.0)
    total, legs = 0, 0
    for ln in d["lines"]:
        shape = ln.get("shape") or {}
        for key, via in list(shape.items()):
            a, b = key.split("|")
            if a not in d["stations"] or b not in d["stations"]:
                continue
            A = (d["stations"][a]["x"], d["stations"][a]["y"])
            B = (d["stations"][b]["x"], d["stations"][b]["y"])
            full = [A] + [tuple(p) for p in via] + [B]
            full, n = despike(full, args.limit)
            if not n:
                continue
            total += n
            legs += 1
            inner = full[1:-1]
            print(f"  {ln['id']:11s} {key:38s} removed {n} reversal point(s)")
            if inner:
                shape[key] = [[round(x, 3), round(y, 3)] for x, y in inner]
            else:
                del shape[key]
    with io.open(args.path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"removed {total} reversal point(s) across {legs} leg(s)")


if __name__ == "__main__":
    main()
