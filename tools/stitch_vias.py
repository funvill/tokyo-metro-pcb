"""Drop a via beside every pad that needs one to reach its plane.

    "C:/Program Files/KiCad/10.0/bin/python.exe" stitch_vias.py BOARD.kicad_pcb \
        [--net GND] [--check] [--max-r 2.2]

Every LED pad on this board is surface mount and therefore front-only,
while the GND plane is on the back, so all 311 GND pads need a via each.
stitch_ground.py cannot do this: it stitches ONE named pad per run, only
ever to the largest fill island, lays a track rather than a via, and its
clearance test knows about tracks and pads but not about the 15,200 mm2 of
netless bare-copper water sitting on F.Cu. A via placed by it near the
coast would short the ground plane to the water.

For each pad of `net` that has no via already within reach, this tries a
ring of candidate positions outward from the pad centre and takes the
first that clears, by the board's own clearance:

  * every pad of a different net, and every track and via already placed
  * the netless art copper on F.Cu - the water and the wordmark
  * the board edge

Vias take the net's own size from the netclass. Idempotent: a pad that
already has a via within --max-r is left alone, so it can be re-run after
the router has done whatever it managed.
"""
import argparse
import math
import sys

import pcbnew

STEP_DEG = 15           # candidate directions around the pad
RING_STEP = 0.15        # and how far out to step each time


def board_clearance(board, net):
    ds = board.GetDesignSettings()
    try:
        return ds.GetNetClasses().GetDefaultPtr().GetClearance()
    except Exception:
        return pcbnew.FromMM(0.2)


def art_copper(board):
    """Netless F.Cu graphics: the water and the wordmark."""
    out = pcbnew.SHAPE_POLY_SET()
    err = pcbnew.FromMM(0.005)
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.F_Cu:
            d.TransformShapeToPolygon(out, pcbnew.F_Cu, 0, err,
                                      pcbnew.ERROR_OUTSIDE)
    out.Simplify()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pcb")
    ap.add_argument("--net", default="GND")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--max-r", type=float, default=2.2,
                    help="furthest a via may sit from the pad centre, mm")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.pcb)
    nets = board.GetNetsByName()
    net = nets.get(args.net) if hasattr(nets, "get") else None
    if net is None:
        try:
            net = nets[args.net]
        except Exception:
            print(f"no net called {args.net} on this board")
            return 1
    clear = board_clearance(board, net)
    art = art_copper(board)
    err = pcbnew.FromMM(0.005)

    # Only pads that are on the FRONT and not already on the plane's layer.
    # A back-side part's GND pad already sits in the back plane, so giving
    # it a via is noise - it was how GND1, SW2 and SW4 showed up as
    # "nowhere to put it".
    plane_layers = set()
    for z in board.Zones():
        if z.GetNetname() == args.net:
            plane_layers.update(z.GetLayerSet().Seq())
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetNetname() == args.net
            and not (set(p.GetLayerSet().Seq()) & plane_layers)]
    others = [p for fp in board.GetFootprints() for p in fp.Pads()
              if p.GetNetname() != args.net]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    tracks = [t for t in board.GetTracks() if t.GetClass() != "PCB_VIA"]

    ds = board.GetDesignSettings()
    vd, vh = ds.GetCurrentViaSize(), ds.GetCurrentViaDrill()
    reach = pcbnew.FromMM(args.max_r)
    outline = pcbnew.SHAPE_POLY_SET()
    board.GetBoardPolygonOutlines(outline, True)

    def free(pos):
        """Can a via of vd sit here?"""
        r = vd / 2 + clear
        for p in others:
            if p.GetBoundingBox().Inflate(int(r)).Contains(pos):
                sh = pcbnew.SHAPE_POLY_SET()
                p.TransformShapeToPolygon(sh, p.GetLayer(), 0, err,
                                          pcbnew.ERROR_OUTSIDE)
                if sh.Collide(pos, int(r)):
                    return False
        for t in tracks + vias:
            if t.GetNetname() != args.net and \
                    t.GetBoundingBox().Inflate(int(r)).Contains(pos):
                return False
        if art.Collide(pos, int(r)):
            return False
        if not outline.Contains(pos, 0):
            return False          # off the board
        return True

    placed, already, failed = 0, 0, []
    for p in pads:
        c = p.GetPosition()
        if any((v.GetPosition() - c).EuclideanNorm() <= reach
               and v.GetNetname() == args.net for v in vias):
            already += 1
            continue
        spot = None
        steps = int(args.max_r / RING_STEP)
        for k in range(2, steps + 1):
            rad = RING_STEP * k
            for a in range(0, 360, STEP_DEG):
                th = math.radians(a)
                cand = pcbnew.VECTOR2I(int(c.x + pcbnew.FromMM(rad * math.cos(th))),
                                       int(c.y + pcbnew.FromMM(rad * math.sin(th))))
                if free(cand):
                    spot = cand
                    break
            if spot:
                break
        if spot is None:
            failed.append(p.GetParentFootprint().GetReference())
            continue
        if not args.check:
            v = pcbnew.PCB_VIA(board)
            v.SetPosition(spot)
            v.SetWidth(vd)
            v.SetDrill(vh)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            v.SetNet(net)
            board.Add(v)
            vias.append(v)
            # and a stub from the pad to it, so the pad is tied on F.Cu even
            # where the front pour is a different net
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(c)
            t.SetEnd(spot)
            t.SetWidth(ds.GetCurrentTrackWidth())
            t.SetLayer(pcbnew.F_Cu)
            t.SetNet(net)
            board.Add(t)
            tracks.append(t)
        placed += 1

    print(f"{args.net}: {len(pads)} pads | {already} already had a via | "
          f"{placed} {'would get' if args.check else 'given'} one | "
          f"{len(failed)} with nowhere to put it")
    if failed:
        print("  no room: " + ", ".join(sorted(set(failed))[:12]))
    if not args.check and placed:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
        pcbnew.SaveBoard(args.pcb, board)
        print(f"saved {args.pcb}")
    return 1 if (args.check and placed) else 0


if __name__ == "__main__":
    sys.exit(main())
