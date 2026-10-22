"""Join the islands of a plane together on the other layer.

    "C:/Program Files/KiCad/10.0/bin/python.exe" bridge_power.py BOARD.kicad_pcb \
        [--net +5V] [--over B.Cu] [--check]

The front pour is +5V and the back is GND. The 15,200 mm2 of netless
bare-copper water already cut the front pour into 19 islands, and the
autorouter's 2,488 front-side tracks cut it into 82, so most of the +5V
pads sit on a piece of plane that reaches nothing: 122 of the board's 132
unconnected items are +5V.

Each bridge is a via down into the back layer, a track across, and a via
back up. That costs a slot in the GND plane per crossing, which is the
price of leaving the map's water intact.

Connectivity is worked out from the geometry rather than from
BOARD.GetConnectivity(): GetConnectedPads() does not count a pad joined to
its neighbour only through a zone fill, so it reported all 304 +5V pads as
304 separate components.

The crossing itself is tried straight first, then as an L through either
corner. A pair that cannot be joined by those is reported rather than
forced - better a named gap to route by hand than a track laid through
something.
"""
import argparse
import math
import sys

import pcbnew

ERR = pcbnew.FromMM(0.005)


class DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, a):
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def poly_of(item, layer):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, ERR, pcbnew.ERROR_OUTSIDE)
    return ps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcb")
    ap.add_argument("--net", default="+5V")
    ap.add_argument("--over", default="B.Cu")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.pcb)
    net = board.GetNetsByName()[args.net]
    code = net.GetNetCode()
    plane_layer = pcbnew.F_Cu
    over = board.GetLayerID(args.over)
    ds = board.GetDesignSettings()
    clear = pcbnew.FromMM(0.25)
    vd, vh = ds.GetCurrentViaSize(), ds.GetCurrentViaDrill()
    tw = ds.GetCurrentTrackWidth()

    # --- the nodes: plane islands, pads, tracks, vias of this net ---------
    zone = next(z for z in board.Zones() if z.GetNetCode() == code)
    fill = zone.GetFilledPolysList(plane_layer)
    islands = []
    for i in range(fill.OutlineCount()):
        ps = pcbnew.SHAPE_POLY_SET()
        ps.AddOutline(fill.COutline(i))
        islands.append(ps)

    pads = [p for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetNetCode() == code]
    trks = [t for t in board.GetTracks()
            if t.GetNetCode() == code and t.GetClass() != "PCB_VIA"]
    vias = [t for t in board.GetTracks()
            if t.GetNetCode() == code and t.GetClass() == "PCB_VIA"]

    nodes = []          # (kind, obj, layers, poly)
    for ps in islands:
        nodes.append(("island", ps, {plane_layer}, ps))
    for p in pads:
        nodes.append(("pad", p, set(p.GetLayerSet().Seq()),
                      poly_of(p, plane_layer)))
    for t in trks:
        nodes.append(("track", t, {t.GetLayer()}, poly_of(t, t.GetLayer())))
    for v in vias:
        nodes.append(("via", v, {plane_layer, over}, poly_of(v, plane_layer)))

    # Bucket by bounding box before testing shapes: this is ~1,000 pieces
    # and the all-pairs version is a million polygon collisions.
    dsu = DSU(len(nodes))
    boxes = [n[3].BBox() for n in nodes]
    CELL = pcbnew.FromMM(8.0)
    grid = {}
    for i, bb in enumerate(boxes):
        for gx in range(bb.GetLeft() // CELL, bb.GetRight() // CELL + 1):
            for gy in range(bb.GetTop() // CELL, bb.GetBottom() // CELL + 1):
                grid.setdefault((gx, gy), []).append(i)
    tested = set()
    for cell in grid.values():
        for a in range(len(cell)):
            for b in range(a + 1, len(cell)):
                i, j = cell[a], cell[b]
                key = (i, j) if i < j else (j, i)
                if key in tested:
                    continue
                tested.add(key)
                if not (nodes[i][2] & nodes[j][2]):
                    continue
                if not boxes[i].Intersects(boxes[j]):
                    continue
                if nodes[i][3].Collide(nodes[j][3], 0):
                    dsu.union(i, j)

    # components that actually carry a pad are the ones that must be joined
    comp = {}
    for i, n in enumerate(nodes):
        comp.setdefault(dsu.find(i), []).append(i)
    live = {r: m for r, m in comp.items()
            if any(nodes[k][0] == "pad" for k in m)}
    print(f"{args.net}: {len(nodes)} pieces -> {len(comp)} components, "
          f"{len(live)} of them carrying a pad")
    if len(live) <= 1:
        print("already one network; nothing to bridge")
        return 0

    # --- a via site per component ----------------------------------------
    others = pcbnew.SHAPE_POLY_SET()
    for t in board.GetTracks():
        if t.GetNetCode() != code:
            for L in (plane_layer, over):
                if t.IsOnLayer(L):
                    t.TransformShapeToPolygon(others, L, 0, ERR,
                                              pcbnew.ERROR_OUTSIDE)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() != code:
                p.TransformShapeToPolygon(others, plane_layer, 0, ERR,
                                          pcbnew.ERROR_OUTSIDE)
    for d in board.GetDrawings():
        if d.GetLayer() == plane_layer:
            d.TransformShapeToPolygon(others, plane_layer, 0, ERR,
                                      pcbnew.ERROR_OUTSIDE)
    others.Simplify()

    def site(members):
        """A point inside this component's plane copper with room for a via.

        The island is shrunk by the via radius plus clearance first, so any
        point still inside the shrunk shape has a via's worth of copper all
        round it. Testing the un-shrunk shape only proves the CENTRE is on
        copper, which would put half the via over the edge.
        """
        r = int(vd / 2 + clear)
        best = None
        for k in members:
            if nodes[k][0] != "island":
                continue
            ps = nodes[k][3]
            area = pcbnew.ToMM(pcbnew.ToMM(ps.Area()))
            if best is not None and area <= best[0]:
                continue
            inner = pcbnew.SHAPE_POLY_SET(ps)
            inner.Inflate(-r, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, ERR)
            if inner.OutlineCount() == 0:
                continue                      # island too small for a via
            bb = inner.BBox()
            step = pcbnew.FromMM(0.5)
            found = None
            y = bb.GetTop()
            while y <= bb.GetBottom() and found is None:
                x = bb.GetLeft()
                while x <= bb.GetRight():
                    pt = pcbnew.VECTOR2I(int(x), int(y))
                    if inner.Contains(pt, -1) and not others.Collide(pt, r):
                        found = pt
                        break
                    x += step
                y += step
            if found is not None:
                best = (area, found)
        return best[1] if best else None

    sites = {}
    for r, m in live.items():
        s = site(m)
        if s is not None:
            sites[r] = s
    print(f"via sites found for {len(sites)} of {len(live)} components")

    # --- minimum spanning tree over the sites ----------------------------
    keys = list(sites)
    done = {keys[0]}
    edges = []
    while len(done) < len(keys):
        best = None
        for a in done:
            for bkey in keys:
                if bkey in done:
                    continue
                pa, pb = sites[a], sites[bkey]
                d = (pa - pb).EuclideanNorm()
                if best is None or d < best[0]:
                    best = (d, a, bkey)
        edges.append((best[1], best[2]))
        done.add(best[2])

    # --- lay each crossing on the back -----------------------------------
    blocked = pcbnew.SHAPE_POLY_SET()
    for t in board.GetTracks():
        if t.GetNetCode() != code and t.IsOnLayer(over):
            t.TransformShapeToPolygon(blocked, over, 0, ERR,
                                      pcbnew.ERROR_OUTSIDE)
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetCode() != code and p.IsOnLayer(over):
                p.TransformShapeToPolygon(blocked, over, 0, ERR,
                                          pcbnew.ERROR_OUTSIDE)
    blocked.Simplify()

    def clean(a, b):
        seg = pcbnew.SHAPE_POLY_SET()
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(a)
        t.SetEnd(b)
        t.SetWidth(tw)
        t.SetLayer(over)
        t.TransformShapeToPolygon(seg, over, int(clear), ERR,
                                  pcbnew.ERROR_OUTSIDE)
        return not blocked.Collide(seg, 0)

    made, failed = [], []
    for a, bkey in edges:
        pa, pb = sites[a], sites[bkey]
        path = None
        if clean(pa, pb):
            path = [pa, pb]
        else:
            for corner in (pcbnew.VECTOR2I(pa.x, pb.y),
                           pcbnew.VECTOR2I(pb.x, pa.y)):
                if clean(pa, corner) and clean(corner, pb):
                    path = [pa, corner, pb]
                    break
        if path is None:
            failed.append((a, bkey))
            continue
        made.append((a, bkey, path))

    print(f"bridges: {len(made)} laid, {len(failed)} could not be routed "
          f"straight or as an L")
    if args.check:
        return 1 if failed else 0

    for a, bkey, path in made:
        for pt in (path[0], path[-1]):
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(pt)
            v.SetWidth(vd)
            v.SetDrill(vh)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(plane_layer, over)
            v.SetNet(net)
            board.Add(v)
        for p, q in zip(path, path[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(p)
            t.SetEnd(q)
            t.SetWidth(tw)
            t.SetLayer(over)
            t.SetNet(net)
            board.Add(t)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(args.pcb, board)
    print(f"saved {args.pcb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
