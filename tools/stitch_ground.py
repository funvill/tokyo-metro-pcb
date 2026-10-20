"""Tie a pad that the copper pour cannot reach into the pour with a short
track. Run with KiCad's own Python, after autoroute.py import and a zone
refill (kicad-cli pcb drc --refill-zones --save-board):

    python stitch_ground.py BOARD.kicad_pcb REF PAD
    python stitch_ground.py BOARD.kicad_pcb REF PAD PAD2     # straight to another pad of REF

Needed for U1's GND pad: its neighbours sit 0.54 mm either side, closer than
the pour's 0.508 mm clearance lets it squeeze in. The track runs on the
pad's own layer, straight from the pad centre to the nearest point of the
main pour that it can reach without coming within CLEAR_MM of another net's
track or pad. Re-running replaces the previous stitch. Check with DRC.
"""
import math
import sys

import pcbnew

WIDTH_MM = 0.4
CLEAR_MM = 0.3          # copper-to-copper, on top of half the track width


def seg_dist(p, q, a, b):
    """Distance between segments pq and ab (points are (x, y) tuples)."""
    def pt_seg(pt, s, e):
        dx, dy = e[0] - s[0], e[1] - s[1]
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((pt[0] - s[0]) * dx + (pt[1] - s[1]) * dy) / L))
        return math.hypot(pt[0] - s[0] - t * dx, pt[1] - s[1] - t * dy)

    def cross(o, u, v):
        return (u[0] - o[0]) * (v[1] - o[1]) - (u[1] - o[1]) * (v[0] - o[0])
    if (cross(p, q, a) * cross(p, q, b) < 0) and (cross(a, b, p) * cross(a, b, q) < 0):
        return 0.0
    return min(pt_seg(p, a, b), pt_seg(q, a, b), pt_seg(a, p, q), pt_seg(b, p, q))


def main(pcb, ref, num, num2=None):
    board = pcbnew.LoadBoard(pcb)
    mm, T = pcbnew.FromMM, pcbnew.ToMM
    pad = next(p for p in board.FindFootprintByReference(ref).Pads() if p.GetNumber() == num)
    if num2:
        # a part with two pads on the net (a switch's pair of ground legs),
        # one of them boxed in: join them directly, under the part
        other = next(p for p in board.FindFootprintByReference(ref).Pads() if p.GetNumber() == num2)
        assert other.GetNetname() == pad.GetNetname()
        back = board.GetLayerID("B.Cu")
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pad.GetPosition())
        track.SetEnd(other.GetPosition())
        track.SetWidth(mm(WIDTH_MM))
        track.SetLayer(back if pad.IsOnLayer(back) else board.GetLayerID("F.Cu"))
        track.SetNet(pad.GetNet())
        board.Add(track)
        pcbnew.SaveBoard(pcb, board)
        print(f"joined {ref} pads {num} and {num2} [{pad.GetNetname()}]")
        return
    back = board.GetLayerID("B.Cu")
    layer = back if pad.IsOnLayer(back) else board.GetLayerID("F.Cu")
    net = pad.GetNetname()
    start = pad.GetPosition()
    s = (T(start.x), T(start.y))

    for t in list(board.GetTracks()):                    # drop an earlier stitch
        if (t.GetClass() == "PCB_TRACK" and t.GetNetname() == net and t.GetStart() == start
                and abs(T(t.GetWidth()) - WIDTH_MM) < 1e-6):
            board.Remove(t)                              # (a second leg, if any, is left)

    zone = next(z for z in board.Zones() if not z.GetIsRuleArea() and z.GetNetname() == net)
    fill = zone.GetFilledPolysList(layer)
    main_i = max(range(fill.OutlineCount()), key=lambda i: abs(fill.Outline(i).Area()))
    main_fill = pcbnew.SHAPE_POLY_SET()
    main_fill.AddOutline(fill.Outline(main_i))
    for j in range(fill.HoleCount(main_i)):
        main_fill.AddHole(fill.Hole(main_i, j))

    # other nets' copper on this layer: track segments, and pads as boxes
    segs, boxes = [], []
    for t in board.GetTracks():
        if t.GetNetname() == net:
            continue
        is_via = t.GetClass() == "PCB_VIA"
        if is_via or t.GetLayer() == layer:
            a, b = t.GetStart(), t.GetEnd()
            width = t.GetWidth(layer) if is_via else t.GetWidth()
            segs.append(((T(a.x), T(a.y)), (T(b.x), T(b.y)), T(width) / 2))
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() != net and p.IsOnLayer(layer):
                bb = p.GetBoundingBox()
                boxes.append((T(bb.GetLeft()), T(bb.GetTop()), T(bb.GetRight()), T(bb.GetBottom())))

    def clear(a0, e):
        need = WIDTH_MM / 2 + CLEAR_MM
        for a, b, half in segs:
            if seg_dist(a0, e, a, b) < need + half:
                return False
        for x0, y0, x1, y1 in boxes:
            corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
            if min(seg_dist(a0, e, corners[i], corners[(i + 1) % 4]) for i in range(4)) < need:
                return False
        return True

    def in_pour(e):
        # well inside the pour, not on its edge
        return all(main_fill.Contains(pcbnew.VECTOR2I(mm(e[0] + ox), mm(e[1] + oy)))
                   for ox, oy in ((0, 0), (0.4, 0), (-0.4, 0), (0, 0.4), (0, -0.4)))

    def ring(c, radii):
        for r in radii:
            for deg in range(0, 360, 15):
                yield (c[0] + r * math.cos(math.radians(deg)), c[1] + r * math.sin(math.radians(deg)))

    def add(a0, e):
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(mm(a0[0]), mm(a0[1])))
        track.SetEnd(pcbnew.VECTOR2I(mm(e[0]), mm(e[1])))
        track.SetWidth(mm(WIDTH_MM))
        track.SetLayer(layer)
        track.SetNet(pad.GetNet())
        board.Add(track)

    reach = [x / 4 for x in range(8, 41)]                # 2.0 .. 10.0 mm, nearest first
    path = next(([e] for e in ring(s, reach) if in_pour(e) and clear(s, e)), None)
    if path is None:                                     # one bend
        path = next(([m, e] for m in ring(s, [x / 2 for x in range(3, 17)]) if clear(s, m)
                     for e in ring(m, reach) if in_pour(e) and clear(m, e)), None)
    if path:
        pts = [s] + path
        for a0, e in zip(pts, pts[1:]):
            add(a0, e)
        pcbnew.SaveBoard(pcb, board)
        print(f"stitched {ref} pad {num} [{net}] through "
              + " -> ".join(f"({x:.2f}, {y:.2f})" for x, y in pts))
        return
    sys.exit(f"no clear path from {ref} pad {num} to the pour")


if __name__ == "__main__":
    main(*sys.argv[1:5])
