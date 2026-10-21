"""Bring the KiCad board in line with the schematic and the data file.
Run with KiCad's own Python (it needs pcbnew):

    "C:/Program Files/KiCad/10.0/bin/python.exe" port_board.py BOARD.kicad_pcb \
        NETLIST.net LEDS.csv PARTS.csv [--strip]

What it does, every run (idempotent):
  * adds a footprint for every LEDn in the netlist that the board lacks
    (a copy of an existing LED), linked to its schematic symbol
  * sets every pad's net from the netlist - the scriptable part of
    "Update PCB from Schematic"
  * moves each LED to its station (leds.csv) and turns it so DOUT faces the
    next LED in the chain; the last one faces away from the previous
  * moves the parts listed in parts.csv (capacitors, mounting holes)
  * fits the copper zones to the board outline

With --strip, first removes what was inherited from the board this one was
copied from: every track and via, and every drawing on the front copper,
mask and silkscreen (the previous map's art). Use it once, on the fresh copy.

The netlist comes from:
    kicad-cli sch export netlist --format kicadsexpr -o NETLIST.net BOARD.kicad_sch
"""
import csv
import math
import re
import sys

import pcbnew

ART_LAYERS = {"F.Cu", "F.Mask", "F.Silkscreen"}
ZONE_INSET_MM = 0.5


def read_netlist(path):
    s = open(path, encoding="utf-8").read()
    pin_net = {}
    for m in re.finditer(r'\(net\s*\(code "?\d+"?\)\s*\(name "([^"]*)"\)(.*?)(?=\(net\s*\(code|\Z)',
                         s, re.S):
        for ref, pin in re.findall(r'\(node\s*\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', m[2]):
            pin_net[(ref, pin)] = m[1]
    sym = {}
    val = {}
    for chunk in s.split("(comp")[1:]:
        ref = re.search(r'\(ref "([^"]+)"\)', chunk)
        stamps = re.findall(r'\(tstamps "([^"]+)"\)', chunk.split("(libparts")[0])
        if ref and stamps:
            sym[ref[1]] = stamps[-1]          # the symbol's own uuid; the first is the sheet path
        v = re.search(r'\(value "([^"]*)"\)', chunk.split("(libsource")[0])
        if ref and v:
            val[ref[1]] = v[1]
    return pin_net, sym, val


def mm(v):
    return pcbnew.FromMM(float(v))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strip = "--strip" in sys.argv
    pcb_path, net_path, leds_path, parts_path = args
    board = pcbnew.LoadBoard(pcb_path)
    pin_net, sym_uuid, sym_val = read_netlist(net_path)
    leds = list(csv.DictReader(open(leds_path, encoding="utf-8")))
    parts = list(csv.DictReader(open(parts_path, encoding="utf-8")))

    if strip:
        tracks = list(board.GetTracks())
        for t in tracks:
            board.Remove(t)
        art = [d for d in board.GetDrawings() if board.GetLayerName(d.GetLayer()) in ART_LAYERS]
        for d in art:
            board.Remove(d)
        print(f"stripped {len(tracks)} tracks/vias and {len(art)} front art items")

    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}

    # --- footprints for new parts -----------------------------------------
    # A bigger city needs more of everything the smaller one had: Tokyo is
    # 248 LEDs against Montreal's 73, and 13 row capacitors against 8. Each
    # missing part is cloned from the first of its own kind, so it carries
    # that kind's footprint, and is linked to its schematic symbol by uuid.
    def clone_missing(rows, template_ref):
        template = by_ref[template_ref]
        added = []
        for row in rows:
            ref = row["ref"]
            if ref in by_ref:
                continue
            if ref not in sym_uuid:
                print(f"  warning: {ref} is on the board list but not in the schematic")
                continue
            fp = pcbnew.Cast_to_FOOTPRINT(template.Duplicate(False))
            fp.SetReference(ref)
            fp.SetPath(pcbnew.KIID_PATH("/" + sym_uuid[ref]))
            board.Add(fp)
            by_ref[ref] = fp
            added.append(ref)
        return added

    added = clone_missing(leds, "LED1")
    print(f"added LED footprints: {len(added)}"
          + (f" ({added[0]}..{added[-1]})" if added else " (none)"))
    for kind, template_ref in (("ROW", "ROW0"), ("H", "H1")):
        rows = [r for r in parts if re.fullmatch(kind + r"\d+", r["ref"])]
        if not rows or template_ref not in by_ref:
            continue
        got = clone_missing(rows, template_ref)
        if got:
            print(f"added {template_ref[:len(kind)]} footprints: {', '.join(got)}")

    # --- nets from the schematic ------------------------------------------
    nets = board.GetNetsByName()
    changed = 0
    for (ref, pin), name in pin_net.items():
        fp = by_ref.get(ref)
        if fp is None:
            print(f"  warning: {ref} is in the schematic but not on the board")
            continue
        if not nets.has_key(name):
            board.Add(pcbnew.NETINFO_ITEM(board, name))
            nets = board.GetNetsByName()
        for pad in fp.Pads():
            if pad.GetNumber() == pin and pad.GetNetname() != name:
                pad.SetNet(nets[name])
                changed += 1
    print(f"pad nets changed: {changed}")

    # Values follow the schematic too. KiCad's own "Update PCB from
    # Schematic" does this; leaving it out meant changing the decoupling
    # caps from 10uF,10V,X5R to 1uF,16V,X5R in the generator produced 52
    # footprint_symbol_mismatch parity errors and a board whose silk and
    # fab layers named a part the BOM no longer had.
    revalued = 0
    for ref, v in sym_val.items():
        fp = by_ref.get(ref)
        if fp is not None and fp.GetValue() != v:
            fp.SetValue(v)
            revalued += 1
    print(f"values updated from the schematic: {revalued}")

    # --- LEDs: position, all at ONE orientation, pin 1 up ----------------
    # Every LED is turned the same way. The alternative - turning each one
    # so DOUT faces the next in the chain, which is what this did until
    # 2026-10-20 - gives the router a shorter hop but puts the parts at
    # eight different angles, and then the only thing standing between a
    # correct board and 248 parts fitted backwards is whether the assembler
    # reads a 0.26 mm dot correctly at eight different rotations. Pads 1
    # and 4 share the part's long edge, so a 180-degree error swaps GND
    # with DI and +5V with DO. One orientation makes the whole board a
    # single thing to check, by eye or in a photo.
    #
    # LED_ROT = 270 puts pad 1 at (-0.45, -0.75) and the silk pin-1 dot at
    # (-0.45, -1.50): the pin-1 edge along the TOP of the part, with the
    # dot directly above it. (KiCad's y runs down, so up is -y.)
    LED_ROT = 270.0
    for row in leds:
        fp = by_ref[row["ref"]]
        fp.SetPosition(pcbnew.VECTOR2I(mm(float(row["x_mm"])), mm(float(row["y_mm"]))))
        fp.SetOrientationDegrees(LED_ROT)
    print(f"placed {len(leds)} LEDs, all at {LED_ROT:g} deg (pin 1 up)")

    # --- other parts ---------------------------------------------------------
    for row in parts:
        fp = by_ref.get(row["ref"])
        if fp is None:
            continue
        fp.SetPosition(pcbnew.VECTOR2I(mm(row["x_mm"]), mm(row["y_mm"])))
        fp.SetOrientationDegrees(float(row["rotation"]))
    print(f"placed {sum(1 for r in parts if r['ref'] in by_ref)} other parts")

    # --- zones follow the outline -------------------------------------------
    bb = board.GetBoardEdgesBoundingBox()
    if bb.GetWidth() > 0:
        inset = pcbnew.FromMM(ZONE_INSET_MM)
        x0, y0, x1, y1 = (bb.GetLeft() + inset, bb.GetTop() + inset,
                          bb.GetRight() - inset, bb.GetBottom() - inset)
        for zone in board.Zones():
            outline = zone.Outline()
            outline.RemoveAllContours()
            outline.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                outline.Append(x, y)
            zone.UnFill()
        print(f"fitted {len(board.Zones())} zone(s) to the outline")

    pcbnew.SaveBoard(pcb_path, board)
    print("saved", pcb_path)


if __name__ == "__main__":
    main()
