"""Put a one-colour SVG on the board's silkscreen. Run with KiCad's own Python.

    python svg_to_silk.py ART.svg BOARD.kicad_pcb --ref LOGO1 --height 100 --top 4.5 [--front]

The SVG must be a single filled path of straight lines (M/L/Z) using the
even-odd fill rule, white on black, as written by the usual "one-bit
silkscreen" tracers. The artwork becomes one board-only footprint, excluded
from the BOM and position files, so it can be moved as a whole in KiCad and
does not upset schematic parity. It is centred left-right on the board, its
top edge --top mm below the board's top edge, scaled to --height mm tall.

By default it goes on the back, mirrored so it reads correctly when the
board is turned over. Re-running replaces the footprint with the same ref.
"""
import argparse
import re

import pcbnew

MIN_AREA_MM2 = 0.01      # drop specks smaller than this


def rings(svg_path):
    d = re.search(r'<path[^>]* d="([^"]+)"', open(svg_path, encoding="utf-8").read())[1]
    out = []
    for sub in re.split(r"(?=M)", d.strip()):
        if not sub.strip():
            continue
        if set(re.findall(r"[A-Za-z]", sub)) - {"M", "L", "Z"}:
            raise SystemExit("only M/L/Z path commands are supported")
        out.append([(float(x), float(y)) for x, y in re.findall(r"(-?[\d.]+),(-?[\d.]+)", sub)])
    return out


def chain(pts):
    c = pcbnew.SHAPE_LINE_CHAIN()
    for x, y in pts:
        c.Append(pcbnew.FromMM(x), pcbnew.FromMM(y))
    c.SetClosed(True)
    return c


def evenodd(rs):
    """Even-odd fill: each ring toggles the area it covers."""
    shape = pcbnew.SHAPE_POLY_SET()
    for r in rs:
        if len(r) < 3:
            continue
        one = pcbnew.SHAPE_POLY_SET()
        one.AddOutline(chain(r))
        one.Simplify()                       # untangle self-touching rings
        shape.BooleanXor(one)
    return shape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("board")
    ap.add_argument("--ref", default="LOGO1")
    ap.add_argument("--height", type=float, required=True, help="artwork height, mm")
    ap.add_argument("--top", type=float, required=True, help="gap from the board's top edge, mm")
    ap.add_argument("--front", action="store_true")
    a = ap.parse_args()

    rs = rings(a.svg)
    xs = [x for r in rs for x, _ in r]
    ys = [y for r in rs for _, y in r]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    s = a.height / (y1 - y0)
    board = pcbnew.LoadBoard(a.board)
    edge = board.GetBoardEdgesBoundingBox()
    cx = pcbnew.ToMM(edge.GetCenter().x)
    top = pcbnew.ToMM(edge.GetTop()) + a.top
    # built for the front, centred on the board, then flipped for the back
    art = evenodd([[(cx + (x - (x0 + x1) / 2) * s, top + (y - y0) * s) for x, y in r] for r in rs])

    for fp in [f for f in board.GetFootprints() if f.GetReference() == a.ref]:
        board.Remove(fp)
    fp = pcbnew.FOOTPRINT(board)
    board.Add(fp)
    fp.SetReference(a.ref)
    fp.SetValue("artwork")
    fp.Reference().SetVisible(False)
    fp.Value().SetVisible(False)
    fp.SetAttributes(pcbnew.FP_BOARD_ONLY | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(cx), pcbnew.FromMM(top + a.height / 2)))

    n = 0
    for i in range(art.OutlineCount()):
        sps = pcbnew.SHAPE_POLY_SET()
        sps.AddOutline(art.Outline(i))
        for h in range(art.HoleCount(i)):
            sps.AddHole(art.Hole(i, h))
        if sps.Area() / 1e12 < MIN_AREA_MM2:
            continue
        sps.Fracture()
        shape = pcbnew.PCB_SHAPE(fp, pcbnew.SHAPE_T_POLY)
        shape.SetPolyShape(sps)
        shape.SetFilled(True)
        shape.SetWidth(0)
        shape.SetLayer(pcbnew.F_SilkS)
        fp.Add(shape)
        n += 1
    if not a.front:
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
    pcbnew.SaveBoard(a.board, board)
    w = (x1 - x0) * s
    print(f"{a.ref}: {n} polygons, {w:.1f} x {a.height:.1f} mm, x {cx - w / 2:.1f}-{cx + w / 2:.1f}, "
          f"y {top:.1f}-{top + a.height:.1f}, {'front' if a.front else 'back'}")


if __name__ == "__main__":
    main()
