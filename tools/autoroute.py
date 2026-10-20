"""Autoroute the board with Freerouting. Run with KiCad's own Python.

    python autoroute.py export BOARD.kicad_pcb OUT.dsn
    java -jar freerouting.jar -de OUT.dsn -do OUT.ses -mp 30
    python autoroute.py import BOARD.kicad_pcb OUT.ses
    python autoroute.py clear  BOARD.kicad_pcb            # remove every track and via

export writes a Specctra file from a throwaway copy of the board in which
every piece of front copper artwork (the bare-copper water and the copper
text) is covered by a keepout for tracks and vias. KiCad does not export
graphic copper to Specctra, so without this the router happily runs tracks
through the water, where they would short to it. The real board is not
touched until import.

import brings the routed session back into the real board. Existing tracks
are removed first, so it can be re-run.
"""
import os
import sys

import pcbnew

ART_CLEAR_MM = 0.35      # keepout = art outline grown by this much


def export(pcb_path, dsn_path):
    board = pcbnew.LoadBoard(pcb_path)
    f_cu = board.GetLayerID("F.Cu")
    grow = pcbnew.FromMM(ART_CLEAR_MM)
    shapes = []
    for d in board.GetDrawings():
        if d.GetLayer() != f_cu:
            continue
        if d.GetClass() == "PCB_SHAPE" and d.GetShape() == pcbnew.SHAPE_T_POLY:
            shapes.append(pcbnew.SHAPE_POLY_SET(d.GetPolyShape()))
        else:                                    # copper text, lines: bounding box
            bb = d.GetBoundingBox()
            sps = pcbnew.SHAPE_POLY_SET()
            sps.NewOutline()
            for x, y in ((bb.GetLeft(), bb.GetTop()), (bb.GetRight(), bb.GetTop()),
                         (bb.GetRight(), bb.GetBottom()), (bb.GetLeft(), bb.GetBottom())):
                sps.Append(x, y)
            shapes.append(sps)
    n = 0
    for sps in shapes:
        sps.Inflate(grow, pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, pcbnew.FromMM(0.02))
        sps.Simplify()
        # Islands are holes in the water. A zone outline here carries no
        # holes, so cut a slit to each one instead - otherwise every island
        # (and the station standing on it) is fenced off as water.
        sps.Fracture()
        for i in range(sps.OutlineCount()):
            zone = pcbnew.ZONE(board)
            zone.SetIsRuleArea(True)
            zone.SetDoNotAllowTracks(True)
            zone.SetDoNotAllowVias(True)
            zone.SetDoNotAllowPads(False)
            zone.SetDoNotAllowZoneFills(False)
            zone.SetDoNotAllowFootprints(False)
            zone.SetLayer(f_cu)
            outline = zone.Outline()
            outline.RemoveAllContours()
            outline.AddOutline(sps.Outline(i))
            board.Add(zone)
            n += 1
    # The pours stay on both layers in the real board, but the front one is
    # cut into islands by the artwork, so it cannot be trusted to carry
    # ground. Tell the router the plane is on the back only: it then drops a
    # via to the back pour for every ground pad.
    b_cu = board.GetLayerID("B.Cu")
    for zone in board.Zones():
        if not zone.GetIsRuleArea():
            ls = pcbnew.LSET()
            ls.AddLayer(b_cu)
            zone.SetLayerSet(ls)
    for t in list(board.GetTracks()):
        board.Remove(t)
    tmp = os.path.splitext(dsn_path)[0] + ".tmp.kicad_pcb"
    pcbnew.SaveBoard(tmp, board)
    board = pcbnew.LoadBoard(tmp)
    ok = pcbnew.ExportSpecctraDSN(board, dsn_path)
    print(f"{n} art keepouts; exported {dsn_path}: {ok}")


def import_ses(pcb_path, ses_path):
    board = pcbnew.LoadBoard(pcb_path)
    old = list(board.GetTracks())
    for t in old:
        board.Remove(t)
    ok = pcbnew.ImportSpecctraSES(board, ses_path)
    # the router necks tracks down a few microns under the board minimum
    floor = board.GetDesignSettings().m_TrackMinWidth
    thin = [t for t in board.GetTracks() if t.GetClass() != "PCB_VIA" and t.GetWidth() < floor]
    for t in thin:
        t.SetWidth(floor)
    print(f"widened {len(thin)} track segments to the {pcbnew.ToMM(floor)} mm minimum")
    tracks = board.GetTracks()
    vias = sum(1 for t in tracks if t.GetClass() == "PCB_VIA")
    print(f"removed {len(old)} old; imported {len(tracks) - vias} track segments, {vias} vias: {ok}")
    pcbnew.SaveBoard(pcb_path, board)


def clear(pcb_path, _=None):
    board = pcbnew.LoadBoard(pcb_path)
    old = list(board.GetTracks())
    for t in old:
        board.Remove(t)
    pcbnew.SaveBoard(pcb_path, board)
    print(f"removed {len(old)} tracks and vias")


if __name__ == "__main__":
    mode, pcb = sys.argv[1:3]
    other = sys.argv[3] if len(sys.argv) > 3 else None
    {"export": export, "import": import_ses, "clear": clear}[mode](pcb, other)
