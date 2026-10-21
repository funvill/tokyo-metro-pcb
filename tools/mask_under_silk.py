"""Close the water's solder-mask opening under the silkscreen. Run with
KiCad's own Python, after export_art.py:

    python mask_under_silk.py BOARD.kicad_pcb

The water is bare copper: an F.Cu polygon with a matching F.Mask opening.
Silkscreen cannot print on an opening (the fab clips it, and the gerber
export does too with --subtract-soldermask), so every route, ring, leader
and label crossing the water would vanish there. This cuts each piece of
front silk, grown by MASK_MARGIN_MM, out of the F.Mask water polygons: the
copper stays, the mask covers it under the ink, and the ink prints.

Re-runnable. The original openings it replaced and the pieces it wrote are
recorded in BOARD.kicad_pcb.silk-mask.json. Each run removes its old pieces
and starts again from the originals - or from export_art.py's fresh ones,
when that has re-run in between and put them back.
"""
import json
import os
import sys

import pcbnew

MASK_MARGIN_MM = 0.2     # mask web kept around the ink (JLC: >= 0.15)
MAX_ERR = pcbnew.FromMM(0.005)


def silk(board):
    """Front silkscreen as one polygon set, grown by the margin."""
    out = pcbnew.SHAPE_POLY_SET()
    grow = pcbnew.FromMM(MASK_MARGIN_MM)
    items = list(board.GetDrawings())
    for fp in board.GetFootprints():
        items += list(fp.GraphicalItems())
        items += [t for t in (fp.Reference(), fp.Value()) if t.IsVisible()]
    for it in items:
        if it.GetLayer() == pcbnew.F_SilkS:
            it.TransformShapeToPolygon(out, pcbnew.F_SilkS, grow, MAX_ERR, pcbnew.ERROR_OUTSIDE)
    out.Simplify()
    return out


def poly_from(points):
    sps = pcbnew.SHAPE_POLY_SET()
    for outline in points:
        chain = pcbnew.SHAPE_LINE_CHAIN()
        for x, y in outline:
            chain.Append(x, y)
        chain.SetClosed(True)
        sps.AddOutline(chain)
    return sps


def points_of(sps):
    sps = pcbnew.SHAPE_POLY_SET(sps)
    sps.Fracture()                      # holes (islands) become slits
    return [[(sps.COutline(i).CPoint(k).x, sps.COutline(i).CPoint(k).y)
             for k in range(sps.COutline(i).PointCount())]
            for i in range(sps.OutlineCount())]


def main(pcb_path):
    side = pcb_path + ".silk-mask.json"
    state = json.load(open(side)) if os.path.exists(side) else {"originals": {}, "pieces": []}
    board = pcbnew.LoadBoard(pcb_path)
    # What export_art.py says the real openings are: {uuid: key}. It is the
    # authority both for spotting our own orphaned pieces below and for
    # refusing to restore an opening export_art has since dropped.
    man_path = pcb_path + ".art-manifest.json"
    claimed = set(json.load(open(man_path)) if os.path.exists(man_path) else [])

    # In KiCad 10 the Python wrappers go bad after a board.Remove() (objects
    # come back as bare SwigPyObjects), so everything is read and added
    # first and the removals happen last, in `doomed`.
    on_board = {d.m_Uuid.AsString(): d for d in board.GetDrawings()
                if d.GetLayer() == pcbnew.F_Mask and d.GetClass() == "PCB_SHAPE"
                and d.GetShape() == pcbnew.SHAPE_T_POLY}
    ink = silk(board)
    doomed = [on_board.pop(u) for u in set(state["pieces"]) & set(on_board)]
    # Anything left that export_art does not claim is one of OUR pieces from
    # an earlier run whose record we have lost. Cutting it again would cut
    # pieces out of pieces: with the state file deleted, 9 openings became
    # 158 and the board collected 192 orphaned fragments. The manifest is
    # the authority on what a real opening is, so drop the rest and let the
    # pieces be rebuilt from the openings themselves.
    orphans = [u for u in on_board if u not in claimed]
    if orphans:
        print(f"  discarding {len(orphans)} unrecorded mask piece(s) from an "
              f"earlier run - RE-RUN export_art.py AND THEN THIS, because "
              f"the openings they were cut from went with them")
        for u in orphans:
            doomed.append(on_board.pop(u))
    # every water opening, by its original uuid: fresh from export_art if it
    # is on the board, otherwise the copy recorded the last time it was cut
    originals = {}
    for u, d in on_board.items():
        originals[u] = pcbnew.SHAPE_POLY_SET()
        d.TransformShapeToPolygon(originals[u], pcbnew.F_Mask, 0, MAX_ERR, pcbnew.ERROR_INSIDE)
    # A recorded original is only worth restoring if export_art.py still
    # claims it. export_art rewrites the water with FRESH uuids on every
    # run, so after it re-runs, every uuid recorded here is missing from
    # the board - and restoring them all put the PREVIOUS run's openings
    # back alongside the new ones, every run, for ever. Seven of eleven
    # recorded openings were ghosts of water shapes that no longer exist,
    # left as bare copper next to LED100's pads. export_art's manifest is
    # the discriminator: it lists what the current artwork wrote, so a uuid
    # it no longer names was dropped by export_art and must not come back.
    ghosts = [u for u in state["originals"]
              if u not in originals and u not in claimed]
    if ghosts:
        print(f"  dropping {len(ghosts)} stale opening(s) from a previous "
              f"export_art run: {', '.join(u[:8] for u in ghosts)}")
    stored = {u: pts for u, pts in state["originals"].items()
              if u not in originals and u in claimed}
    for u, pts in stored.items():
        originals[u] = poly_from(pts)

    new_state = {"originals": {}, "pieces": []}
    cut = 0
    for u, shape in originals.items():
        before = shape.Area()
        rest = pcbnew.SHAPE_POLY_SET(shape)
        rest.BooleanSubtract(ink)
        if abs(rest.Area() - before) < 1e3 and u in on_board:
            continue                                    # no ink over this one
        new_state["originals"][u] = stored[u] if u in stored else points_of(shape)
        if u in on_board:
            doomed.append(on_board[u])
        rest.Fracture()
        for i in range(rest.OutlineCount()):
            piece = pcbnew.SHAPE_POLY_SET()
            piece.AddOutline(rest.COutline(i))
            d = pcbnew.PCB_SHAPE(board, pcbnew.SHAPE_T_POLY)
            d.SetPolyShape(piece)
            d.SetFilled(True)
            d.SetWidth(0)
            d.SetLayer(pcbnew.F_Mask)
            board.Add(d)
            new_state["pieces"].append(d.m_Uuid.AsString())
        cut += 1
        print(f"  {u[:8]}: {(before - rest.Area()) / 1e12:.1f} mm² of opening closed under ink, "
              f"{rest.OutlineCount()} piece(s)")
    for d in doomed:
        board.Remove(d)
    pcbnew.SaveBoard(pcb_path, board)
    with open(side, "w") as f:
        json.dump(new_state, f)
    print(f"{cut} of {len(originals)} water openings cut back under the silkscreen")


if __name__ == "__main__":
    main(sys.argv[1])
