"""Make the LED silkscreen pin-1 mark say which CORNER, not just which side.

    "C:/Program Files/KiCad/10.0/bin/python.exe" led_polarity.py BOARD.kicad_pcb [--check]

The XL-1615 footprint carries pads 1 and 4 on the SAME side of the part
(pad 1 at -0.75, +0.45 and pad 4 at -0.75, -0.45), and the vendor's silk
pin-1 dot sits at (-1.5, 0.03) - on the left edge, centred between the two.
That marks the side and nothing more, so a part fitted 180 degrees out is
indistinguishable on silkscreen. A 180 degree error on this part swaps GND
with DI and +5V with DO on every LED it affects.

The F.Fab layer is already unambiguous - a pin-1 arrow, a dot and a "1"
text, all in pad 1's own corner - and that is the layer an assembler works
from. This is for the human: inspection, hand rework, and reading the board
with the part already on it.

The fix adds no ink. The existing dot is moved along the edge onto pad 1's
row, at (pad1.x - 0.75, pad1.y), which is the ordinary convention. Position
is computed from the pad, not hard-coded, so it follows the footprint if the
pad map ever changes.

Idempotent: a dot already within TOL of the target is left alone, so this
can run after every port_board.py. Run it with the board closed in KiCad.
"""
import sys

import pcbnew

TOL_MM = 0.01
OFFSET_MM = 0.75        # how far outside pad 1 the dot sits, along -x


def pin1_dot_target(fp):
    """Where the silk dot belongs, in board coordinates.

    Derived from the pads rather than from the footprint's orientation:
    pad 2 sits directly across the body from pad 1, so pad1 - pad2 IS the
    outward direction along the part's short axis, whatever the rotation
    and whichever side the part is on. No angle arithmetic, so no sign
    convention to get wrong - and the LEDs here sit at mixed rotations.
    """
    pads = {p.GetNumber(): p.GetPosition() for p in fp.Pads()}
    if "1" not in pads or "2" not in pads:
        return None
    p1, p2 = pads["1"], pads["2"]
    vx, vy = p1.x - p2.x, p1.y - p2.y
    ln = (vx * vx + vy * vy) ** 0.5
    if ln < 1:
        return None
    step = pcbnew.FromMM(OFFSET_MM) / ln
    return pcbnew.VECTOR2I(int(p1.x + vx * step), int(p1.y + vy * step))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    board = pcbnew.LoadBoard(args[0])
    leds = [f for f in board.GetFootprints()
            if f.GetReference().startswith("LED") and f.GetReference()[3:].isdigit()]
    moved, already, missing = [], [], []
    for fp in leds:
        circles = [g for g in fp.GraphicalItems()
                   if g.GetLayer() == pcbnew.F_SilkS and g.ShowShape() == "Circle"]
        want = pin1_dot_target(fp)
        if not circles or want is None:
            missing.append(fp.GetReference())
            continue
        dot = circles[0]
        have = dot.GetCenter()
        off = pcbnew.ToMM(int(((have.x - want.x) ** 2 + (have.y - want.y) ** 2) ** 0.5))
        if off <= TOL_MM:
            already.append(fp.GetReference())
            continue
        if not check:
            end = dot.GetEnd()
            r = pcbnew.VECTOR2I(end.x - have.x, end.y - have.y)
            dot.SetCenter(want)
            dot.SetEnd(pcbnew.VECTOR2I(want.x + r.x, want.y + r.y))
        moved.append((fp.GetReference(), round(off, 3)))

    print(f"{len(leds)} LEDs: {len(already)} dot(s) already on pad 1's row, "
          f"{len(moved)} {'to move' if check else 'moved'}, {len(missing)} with no silk dot")
    if missing:
        print("  no silk dot:", ", ".join(missing[:10]))
    if check:
        sys.exit(1 if moved or missing else 0)
    if moved:
        pcbnew.SaveBoard(args[0], board)
        print(f"saved {args[0]}")


if __name__ == "__main__":
    main()
