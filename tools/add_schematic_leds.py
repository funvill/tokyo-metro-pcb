"""One-off: grow the Vancouver schematic's 68-LED chain to Montréal's 73.

The sheet is rows of WS2812 symbols between a GND rail (above) and a +5V
rail (below), rows chained through ROWn global labels, the last LED's DO on
ROW8 (the LED_OUT test point). This adds

    LED69, LED70   in the two free slots at the end of the last row
    LED71..LED73   in a new row below, with its own rails and power symbols

and re-threads the chain LED68 -> 69 -> 70 -(ROW9)-> 71 -> 72 -> 73 -> ROW8.
New blocks are clones of existing ones (LED68, the last row's power symbols
and labels) with fresh uuids, so the file stays in KiCad's own dialect.

Run once on a fresh copy; it refuses if LED69 already exists. Verify with
    kicad-cli sch export netlist ... (see hardware/README.md)

Usage:  python add_schematic_leds.py ../hardware/tokyo-metro-pcb.kicad_sch
"""
import re
import sys
import uuid

PITCH_Y = 16.51                 # row pitch on the sheet
LAST_ROW_Y = 156.21
NEW_ROW_Y = LAST_ROW_Y + PITCH_Y
RAIL = 6.35                     # rails sit this far above (GND) / below (+5V) a row
# pin offsets from the symbol origin (the symbols are placed rotated 180)
DI, VDD, GND, DO = (-6.35, -1.27), (-6.35, 1.27), (7.62, -1.27), (7.62, 1.27)


def r(v):
    return f"{round(v, 4):g}"


def split_blocks(text):
    depth, blocks, start, first = 0, [], None, None
    for i, c in enumerate(text):
        if c == "(":
            depth += 1
            if depth == 2:
                start = i
                first = i if first is None else first
        elif c == ")":
            depth -= 1
            if depth == 1:
                blocks.append(text[start:i + 1])
                end = i + 1
    return text[:first], blocks, text[end:]


def shifted(block, dx, dy):
    """A copy of a block moved by (dx, dy), with every uuid replaced."""
    block = re.sub(r"\(at ([-\d.]+) ([-\d.]+)",
                   lambda m: f"(at {r(float(m[1]) + dx)} {r(float(m[2]) + dy)}", block)
    return re.sub(r'\(uuid "[^"]+"\)', lambda m: f'(uuid "{uuid.uuid4()}")', block)


def renamed(block, old, new):
    return block.replace(f'"{old}"', f'"{new}"')


def at(block):
    m = re.search(r"\(at ([-\d.]+) ([-\d.]+)", block)
    return float(m[1]), float(m[2])


def ref(block):
    m = re.search(r'\(property "Reference" "([^"]+)"', block)
    return m[1] if m else None


def wire(*pts):
    out = []
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        out.append(f'(wire\n\t\t(pts\n\t\t\t(xy {r(x1)} {r(y1)}) (xy {r(x2)} {r(y2)})\n\t\t)\n'
                   f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
                   f'\t\t(uuid "{uuid.uuid4()}")\n\t)')
    return out


def junction(x, y):
    return (f'(junction\n\t\t(at {r(x)} {r(y)})\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n'
            f'\t\t(uuid "{uuid.uuid4()}")\n\t)')


def main(path):
    text = open(path, encoding="utf-8").read()
    head, blocks, tail = split_blocks(text)
    by_ref = {ref(b): b for b in blocks if b.startswith("(symbol")}
    assert "LED68" in by_ref and "LED69" not in by_ref, "expected a 68-LED sheet"
    led68 = by_ref["LED68"]
    x68, y68 = at(led68)
    assert abs(y68 - LAST_ROW_Y) < 0.01, at(led68)

    def labels(name, shape):
        return [b for b in blocks if b.startswith(f'(global_label "{name}"')
                and f"(shape {shape})" in b]

    row8_out, = labels("ROW8", "output")            # on LED68's DO today
    assert max(abs(at(row8_out)[0] - x68 - DO[0]), abs(at(row8_out)[1] - y68 - DO[1])) < 0.01, at(row8_out)
    row7_in, = labels("ROW7", "input")              # template for a row's entry label
    gnd_sym, vdd_sym = by_ref["#PWR024"], by_ref["#PWR025"]   # last row's rail symbols
    rail_x = at(gnd_sym)[0]

    # (ref, x, y) of the new LEDs
    new = [("LED69", x68 + 19.05, LAST_ROW_Y), ("LED70", x68 + 38.1, LAST_ROW_Y),
           ("LED71", 76.2, NEW_ROW_Y), ("LED72", 95.25, NEW_ROW_Y), ("LED73", 114.3, NEW_ROW_Y)]
    add = []
    for name, x, y in new:
        add.append(renamed(shifted(led68, x - x68, y - y68), "LED68", name))
        add += wire((x + VDD[0], y + VDD[1]), (x + VDD[0], y + RAIL))      # VDD down to +5V
        add += wire((x + GND[0], y + GND[1]), (x + GND[0], y - RAIL))      # GND up to GND rail

    def link(a, b):
        """DO of LED a to DI of the next LED b in the same row."""
        (_, xa, ya), (_, xb, yb) = a, b
        return wire((xa + DO[0], ya + DO[1]), (xa + DO[0] + 1.27, ya + DO[1]),
                    (xa + DO[0] + 1.27, yb + DI[1]), (xb + DI[0], yb + DI[1]))

    led68_t = ("LED68", x68, y68)
    add += link(led68_t, new[0]) + link(new[0], new[1])          # 68 -> 69 -> 70
    add += link(new[2], new[3]) + link(new[3], new[4])           # 71 -> 72 -> 73

    # last row: its rails already run to the capacitor past LED70 - tap them
    for _, x, y in new[:2]:
        add += [junction(x + VDD[0], y + RAIL), junction(x + GND[0], y - RAIL)]
    # LED70 DO -> ROW9 -> LED71 DI
    blocks.remove(row8_out)
    add.append(renamed(shifted(row8_out, new[1][1] - x68, 0), "ROW8", "ROW9"))
    rx, ry = at(row7_in)
    add.append(renamed(shifted(row7_in, new[2][1] + DI[0] - rx, new[2][2] + DI[1] - ry),
                       "ROW7", "ROW9"))
    # LED73 DO -> ROW8 (the LED_OUT test point), as LED68's was
    add.append(shifted(row8_out, new[4][1] - x68, new[4][2] - y68))

    # new row: rails from the power symbols at the left to the last pin
    gy, vy = NEW_ROW_Y - RAIL, NEW_ROW_Y + RAIL
    add.append(renamed(shifted(gnd_sym, 0, gy - at(gnd_sym)[1]), "#PWR024", "#PWR026"))
    add.append(renamed(shifted(vdd_sym, 0, vy - at(vdd_sym)[1]), "#PWR025", "#PWR027"))
    add += wire((rail_x, gy), *[(x + GND[0], gy) for _, x, _ in new[2:]])
    add += wire((rail_x, vy), *[(x + VDD[0], vy) for _, x, _ in new[2:]])
    add += [junction(x + GND[0], gy) for _, x, _ in new[2:4]]
    add += [junction(x + VDD[0], vy) for _, x, _ in new[2:4]]

    # keep (sheet_instances ...) and (embedded_fonts ...) last, as KiCad writes them
    cut = next(i for i, b in enumerate(blocks) if b.startswith("(sheet_instances"))
    blocks[cut:cut] = add
    open(path, "w", encoding="utf-8", newline="\n").write(
        head + "\n\t".join(blocks) + tail)
    print(f"added {', '.join(n for n, _, _ in new)}: {len(add)} blocks")


if __name__ == "__main__":
    main(sys.argv[1])
