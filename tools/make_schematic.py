"""Build the LED chain sheet for N LEDs, keeping the controller block.

    python -X utf8 make_schematic.py ../hardware/tokyo-metro-pcb.kicad_sch 248

Montréal's `add_schematic_leds.py` was a one-off that grew a 68-LED chain to
73 by cloning two blocks at hard-coded coordinates. Tokyo needs 248, which is
a different job: the sheet has to be re-laid out, not extended. This
regenerates the whole LED section from computed geometry and leaves
everything else - the XIAO, the buttons, the test points, the mounting
holes, the series resistor and the bulk capacitor - exactly where it is.

The layout, from the template's own conventions:

* symbols are placed at rotation 180, so the pins sit at
  DI (x-6.35, y-1.27), VDD (x-6.35, y+1.27), GND (x+7.62, y-1.27),
  DO (x+7.62, y+1.27) relative to the symbol origin;
* a row is LEDS_PER_ROW symbols at X_PITCH, with a GND rail RAIL above it
  and a +5V rail RAIL below;
* DO jogs to the next DI between neighbours;
* rows chain through ROWn global labels, so the sheet reads left to right,
  top to bottom, in chain order.

Every stub that meets a rail gets a junction, because KiCad does not connect
a wire end to the middle of another wire without one.

Verify by exporting the netlist and running check_led_chain.py - a schematic
that loads is not the same as a schematic that is wired right.
"""
import argparse
import io
import math
import os
import re
import sys
import uuid as uuidlib

# geometry, in schematic mm
X_PITCH = 20.32
Y_PITCH = 16.51
RAIL = 6.35          # rail offset above (GND) and below (+5V) a row
PIN = {"DI": (-6.35, -1.27), "VDD": (-6.35, 1.27),
       "GND": (7.62, -1.27), "DO": (7.62, 1.27)}
JOG = 1.27           # how far past DO the jog turns

NS = uuidlib.UUID("7c3f6a54-9e21-4a3b-9c0e-5d8b1f2a6c40")


def det_uuid(key):
    """Deterministic uuid, so regenerating does not churn the file."""
    return str(uuidlib.uuid5(NS, key))


def top_blocks(text):
    """(start, end) of every depth-1 s-expression in the file body."""
    out, depth, start = [], 0, None
    for i, c in enumerate(text):
        if c == "(":
            if depth == 1:
                start = i
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 1 and start is not None:
                out.append((start, i + 1))
                start = None
    return out


GRID_TOP = 50.0     # the LED grid is everything below this y ...
GRID_LEFT = 60.0    # ... and right of this x. Above and left is the
                    # controller block and the test-point column, both kept
                    # exactly as they are - the test points sit at x = 24
                    # and run down to y = 83, so a y threshold alone takes
                    # their wiring with the grid and leaves LED_OUT floating


def block_y(b):
    """The y of a block's first (at ...), or None."""
    m = re.search(r'\(at ([-\d.]+) ([-\d.]+)', b)
    return float(m.group(2)) if m else None


def wire_ys(b):
    return [float(y) for _, y in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', b)]


def block_ref(b):
    m = re.search(r'\(property "Reference" "([^"]+)"', b)
    return m.group(1) if m else None


def wire(a, b, key):
    return (f'\t(wire\n\t\t(pts\n\t\t\t(xy {a[0]:g} {a[1]:g}) (xy {b[0]:g} {b[1]:g})\n\t\t)\n'
            f'\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n\t\t)\n'
            f'\t\t(uuid "{det_uuid(key)}")\n\t)\n')


def junction(p, key):
    return (f'\t(junction\n\t\t(at {p[0]:g} {p[1]:g})\n\t\t(diameter 0)\n'
            f'\t\t(color 0 0 0 0)\n\t\t(uuid "{det_uuid(key)}")\n\t)\n')


POWER_N = [0]


def power(kind, p, key, angle=0):
    """A +5V or GND power symbol at p.

    Power symbols need real references (#PWR01, ...) or kicad-cli reports
    "schematic has annotation errors" and the board update has nothing to
    match them against.
    """
    # Numbered from 900 so they cannot collide with the controller block's
    # own #PWR001..#PWR029, which are kept. A duplicate reference is what
    # "schematic has annotation errors" means, and it stops the board
    # update matching symbols to footprints.
    POWER_N[0] += 1
    ref = f"#PWR{900 + POWER_N[0]:03d}"
    lib = "power:+5V" if kind == "+5V" else "power:GND"
    return (f'\t(symbol\n\t\t(lib_id "{lib}")\n\t\t(at {p[0]:g} {p[1]:g} {angle})\n'
            f'\t\t(unit 1)\n\t\t(exclude_from_sim no)\n\t\t(in_bom no)\n'
            f'\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(fields_autoplaced yes)\n'
            f'\t\t(uuid "{det_uuid(key)}")\n'
            f'\t\t(property "Reference" "{ref}"\n\t\t\t(at {p[0]:g} {p[1] + 2.54:g} 0)\n'
            f'\t\t\t(hide yes)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
            f'\t\t\t\t)\n\t\t\t)\n\t\t)\n'
            f'\t\t(property "Value" "{kind}"\n\t\t\t(at {p[0]:g} {p[1] - 3.81 if kind == "+5V" else p[1] + 3.81:g} 0)\n'
            f'\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n'
            f'\t\t(instances\n\t\t\t(project ""\n\t\t\t\t(path "/{SHEET_UUID}"\n'
            f'\t\t\t\t\t(reference "{ref}")\n\t\t\t\t\t(unit 1)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n')


def glabel(name, p, angle, justify, key):
    return (f'\t(global_label "{name}"\n\t\t(shape input)\n'
            f'\t\t(at {p[0]:g} {p[1]:g} {angle})\n\t\t(fields_autoplaced yes)\n'
            f'\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            f'\t\t\t(justify {justify})\n\t\t)\n\t\t(uuid "{det_uuid(key)}")\n\t)\n')


def reuuid(block, prefix):
    """Give every uuid in a cloned block its own deterministic value.

    A symbol block holds more than one: the symbol's own, and one per
    property. Replacing only the first leaves every clone sharing the rest,
    which is exactly the duplicate-uuid failure lesson B5 says to check for
    (the bar is zero, and cloning 248 LEDs made it four).
    """
    n = [0]

    def sub(m):
        n[0] += 1
        return f'(uuid "{det_uuid(f"{prefix}:{n[0]}")}")'

    return re.sub(r'\(uuid "[^"]+"\)', sub, block)


def move_properties(block, dx, dy):
    """Shift every property's position by the same delta as the symbol.

    A symbol block carries its own (at x y rot) and one per property. Moving
    only the symbol leaves all 248 clones' reference and value text piled up
    at the template's original coordinates - invisible when the properties
    are hidden, a black smear when they are not.
    """
    seen = [0]

    def sub(m):
        seen[0] += 1
        if seen[0] == 1:          # the symbol's own position, already set
            return m.group(0)
        rest = m.group(3) or ""
        return f'(at {float(m.group(1)) + dx:g} {float(m.group(2)) + dy:g}{rest}'

    return re.sub(r'\(at ([-\d.]+) ([-\d.]+)( [-\d.]+)?', sub, block)


def place(template, p, rot, prefix, ref_pat, ref_new):
    """Clone a symbol block: move it, move its text, re-reference, re-uuid."""
    old = re.search(r'\(at ([-\d.]+) ([-\d.]+)', template)
    ox, oy = float(old.group(1)), float(old.group(2))
    b = re.sub(r'\(at [-\d.]+ [-\d.]+ [-\d.]+\)',
               f'(at {p[0]:g} {p[1]:g} {rot})', template, count=1)
    b = move_properties(b, p[0] - ox, p[1] - oy)
    b = reuuid(b, prefix)
    b = re.sub(r'\(property "Reference" "' + ref_pat + r'"',
               f'(property "Reference" "{ref_new}"', b)
    b = re.sub(r'\(reference "' + ref_pat + r'"\)', f'(reference "{ref_new}")', b)
    return b


def led_symbol(template, n, p):
    """The template LED block, re-referenced, re-placed and re-uuid'd."""
    return place(template, p, 180, f"led:{n}", r"LED\d+", f"LED{n}")


CAP_PIN = 2.54      # the row decoupling cap's pins, above and below centre


def cap_symbol(template, n, p):
    """One row decoupling capacitor, re-referenced and re-placed."""
    return place(template, p, 0, f"cap:{n}", r"ROW\d+", f"ROW{n}")


def main():
    global SHEET_UUID
    ap = argparse.ArgumentParser()
    ap.add_argument("sch")
    ap.add_argument("count", type=int)
    ap.add_argument("--template", default=None,
                    help="the pristine sheet to build from; default <sch>.template")
    ap.add_argument("--per-row", type=int, default=20)
    ap.add_argument("--origin", default="95,70",
                    help="first LED, x,y mm. 95 rather than 80 so the row "
                         "capacitors and their power symbols fit between the "
                         "mounting-hole column (text out to x=43) and the "
                         "row's input label; the A2 sheet has 128 mm spare "
                         "on the right")
    ap.add_argument("--paper", default="A2")
    args = ap.parse_args()

    # Always build from a pristine template, never from the last output.
    # Reading its own result makes the generator depend on where it put
    # things last time: moving the row capacitors left pushed the generated
    # power symbols outside the region the dropper recognises, so a second
    # run kept them AND added more - 130 duplicate uuids and 29 overlaps.
    tpl = args.template or (args.sch + ".template")
    if not os.path.exists(tpl):
        raise SystemExit(f"no template at {tpl}; it is the sheet this is "
                         f"generated from and belongs in the repo")
    with io.open(tpl, encoding="utf-8") as f:
        s = f.read()
    SHEET_UUID = re.search(r'\(uuid "([^"]+)"\)', s).group(1)

    blocks = top_blocks(s)
    cap_tpl = [None]
    led_tpl = None
    keep, drop_spans = [], []
    for a, b in blocks:
        body = s[a:b]
        kind = body[1:body.find("\n")].strip() if "\n" in body[:30] else body[1:20]
        ref = block_ref(body)
        is_led = ref is not None and ref.startswith("LED") and ref[3:].isdigit()
        is_rowcap = ref is not None and ref.startswith("ROW") and ref[3:].isdigit()
        if is_led and led_tpl is None:
            led_tpl = body
        if is_rowcap and cap_tpl[0] is None:
            cap_tpl[0] = body
        # Everything belonging to the old LED grid goes; the controller
        # block stays, wiring and all. Dropping every wire on the sheet - as
        # the first version did - leaves U1, R1 and the test points floating
        # with nothing connected to LED_IN or LED_OUT.
        in_grid = False
        if kind.startswith("wire"):
            pts = [(float(x), float(y)) for x, y in
                   re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', body)]
            in_grid = bool(pts) and all(y >= GRID_TOP and x >= GRID_LEFT
                                        for x, y in pts)
        elif kind.startswith(("junction", "global_label")) or (ref or "").startswith("#PWR"):
            m = re.search(r'\(at ([-\d.]+) ([-\d.]+)', body)
            in_grid = (m is not None and float(m.group(2)) >= GRID_TOP
                       and float(m.group(1)) >= GRID_LEFT)
        # Montreal tied the chain's last output to the LED_OUT test point
        # with a second label, ROW8. With 13 rows this file generates a
        # ROW8 of its own, and the two shorted LED160 to the test point.
        # Generated boundary labels are CHAIN1..n, and any leftover ROW
        # label goes.
        if kind.startswith("global_label") and re.match(r'\(global_label "ROW\d+"', body):
            in_grid = True
        if is_led or is_rowcap or in_grid:
            drop_spans.append((a, b))
    if led_tpl is None:
        raise SystemExit("no LED symbol in the template to clone")

    print(f"template: {len(blocks)} blocks, dropping {len(drop_spans)} "
          f"(LED grid, its wiring and its power symbols)")

    # rebuild the file without the dropped blocks
    out, prev = [], 0
    for a, b in drop_spans:
        out.append(s[prev:a])
        prev = b
    out.append(s[prev:])
    body = "".join(out)
    body = re.sub(r"\n\t*\n(\t*\n)+", "\n\n", body)

    # --- generate the new grid ----------------------------------------
    ox, oy = (float(v) for v in args.origin.split(","))
    gen = []
    rows = math.ceil(args.count / args.per_row)
    for n in range(1, args.count + 1):
        i = n - 1
        row, col = divmod(i, args.per_row)
        x = ox + col * X_PITCH
        y = oy + row * Y_PITCH
        gen.append(led_symbol(led_tpl, n, (x, y)))
        gnd = (x + PIN["GND"][0], y + PIN["GND"][1])
        vdd = (x + PIN["VDD"][0], y + PIN["VDD"][1])
        rail_g, rail_v = y - RAIL, y + RAIL
        gen.append(wire(gnd, (gnd[0], rail_g), f"w:gnd:{n}"))
        gen.append(wire(vdd, (vdd[0], rail_v), f"w:vdd:{n}"))
        # chain: DO jogs across to the next DI, unless this is a row end
        do = (x + PIN["DO"][0], y + PIN["DO"][1])
        last_in_row = (col == args.per_row - 1) or n == args.count
        if not last_in_row:
            di = (x + X_PITCH + PIN["DI"][0], y + PIN["DI"][1])
            gen.append(wire(do, (do[0] + JOG, do[1]), f"w:do:{n}:a"))
            gen.append(wire((do[0] + JOG, do[1]), (do[0] + JOG, di[1]), f"w:do:{n}:b"))
            gen.append(wire((do[0] + JOG, di[1]), di, f"w:do:{n}:c"))
    # rails, one wire per row plus a junction at every stub
    for row in range(rows):
        first = row * args.per_row + 1
        last = min((row + 1) * args.per_row, args.count)
        y = oy + row * Y_PITCH
        x0 = ox + PIN["GND"][0] + 0            # leftmost stub x for GND
        xs_g = [ox + c * X_PITCH + PIN["GND"][0] for c in range(last - first + 1)]
        xs_v = [ox + c * X_PITCH + PIN["VDD"][0] for c in range(last - first + 1)]
        # the row's decoupling capacitor sits left of the first LED, between
        # the two rails, which run out to meet it
        # 30.48 mm clear of the first LED, not 12.7: the row's input label
        # (LED_IN / CHAIN*) is right-justified at ox - 11.43 and its text
        # runs left from there, straight over a cap placed any closer.
        # check_schematic.py found all thirteen of them.
        x_cap = ox - 30.48
        if cap_tpl[0] is not None:
            gen.append(cap_symbol(cap_tpl[0], row, (x_cap, y)))
            gen.append(wire((x_cap, y - CAP_PIN), (x_cap, y - RAIL), f"cap:{row}:g"))
            gen.append(wire((x_cap, y + CAP_PIN), (x_cap, y + RAIL), f"cap:{row}:v"))
        for xs, ry, kind, key in ((xs_g, y - RAIL, "GND", "g"), (xs_v, y + RAIL, "+5V", "v")):
            left = x_cap if cap_tpl[0] is not None else min(xs)
            gen.append(wire((left, ry), (max(xs), ry), f"rail:{key}:{row}"))
            for j, x in enumerate(xs):
                if j < len(xs) - 1:
                    gen.append(junction((x, ry), f"j:{key}:{row}:{j}"))
            if cap_tpl[0] is not None:
                gen.append(junction((x_cap, ry), f"j:cap:{key}:{row}"))
            # one power symbol per rail, hung off the left end
            gen.append(wire((left, ry), (left - 5.08, ry), f"rail:{key}:{row}:tail"))
            gen.append(power(kind, (left - 5.08, ry), f"pwr:{key}:{row}",
                             angle=270 if kind == "GND" else 90))
        # row chaining labels
        di_first = (ox + PIN["DI"][0], y + PIN["DI"][1])
        do_last = (ox + (last - first) * X_PITCH + PIN["DO"][0], y + PIN["DO"][1])
        in_name = "LED_IN" if row == 0 else f"CHAIN{row}"
        out_name = "LED_OUT" if last == args.count else f"CHAIN{row + 1}"
        gen.append(wire(di_first, (di_first[0] - 5.08, di_first[1]), f"lbl:in:{row}"))
        gen.append(glabel(in_name, (di_first[0] - 5.08, di_first[1]), 180, "right",
                          f"gl:in:{row}"))
        gen.append(wire(do_last, (do_last[0] + 5.08, do_last[1]), f"lbl:out:{row}"))
        gen.append(glabel(out_name, (do_last[0] + 5.08, do_last[1]), 0, "left",
                          f"gl:out:{row}"))

    # --- tidy the inherited controller block ---------------------------
    # Montreal hangs LED_DATA and LED_IN straight off R1's two pins with no
    # wire, so both labels' text runs back across the resistor body, and
    # C1's value text runs through R1's reference. Electrically fine,
    # unreadable on paper. Give each label a 5.08 mm stub to stand off on -
    # a wire from the pin to the label is the same net - and move C1's value
    # text clear. check_schematic.py counts what is left.
    # Removing a block means finding that exact block, not matching a
    # pattern across the file: a lazy [\s\S]*? between the label's name and
    # its position happily spans from an earlier LED_DATA label all the way
    # to this one and deletes the entire controller block in between. It
    # did, and the netlist went from 281 components to 261 before
    # check_led_chain noticed R1 had gone.
    tidy = []
    for name, pin, away, angle in (("LED_DATA", (120.65, 38.1), (120.65, 33.02), 90),
                                   ("LED_IN", (120.65, 45.72), (120.65, 50.8), 270)):
        want = f'(at {pin[0]:g} {pin[1]:g} '
        target = None
        for a, bnd in top_blocks(body):
            blk = body[a:bnd]
            if blk.startswith(f'(global_label "{name}"') and want in blk:
                target = (a, bnd)
                break
        if target is None:
            print(f"  note: {name} label at R1 not found, left as it was")
            continue
        body = body[:target[0]] + body[target[1]:]
        tidy.append(wire(pin, away, f"r1:{name}"))
        tidy.append(glabel(name, away, angle, "left", f"r1:lbl:{name}"))
    if tidy:
        print(f"tidied the controller: {len(tidy) // 2} label(s) moved off R1")
    # C1's value text is centred on the symbol and runs right, straight
    # through R1 and R1's reference. Left-justify it and pull it clear.
    c1 = re.search(r'(\(property "Value" "100uF,[\d.]+V,X5R"\s*\(at )'
                   r'([-\d.]+) ([-\d.]+)', body)
    if c1:
        body = body.replace(
            c1.group(0),
            # Not beside C1: the gap between U1's right edge and the +5V
            # symbol is 14.5 mm and this string is 16 mm wide. It goes in
            # the clear band below the controller, above the first LED row.
            f"{c1.group(1)}{float(c1.group(2)) - 15.57:g} "
            f"{float(c1.group(3)) + 11.36:g}")
        print("  moved C1's value text clear of R1")
    else:
        print("  note: C1's value text not found, left as it was")
    body = body.rstrip()
    assert body.endswith(")"), "unexpected end of schematic"
    body = body[:-1] + "".join(gen) + ")\n"
    body = re.sub(r'\(paper "[^"]+"\)', f'(paper "{args.paper}")', body, count=1)

    with io.open(args.sch, "w", encoding="utf-8") as f:
        f.write(body)
    print(f"from {os.path.basename(tpl)}")
    print(f"wrote {os.path.basename(args.sch)}: {args.count} LEDs in {rows} rows "
          f"of {args.per_row}, paper {args.paper}")
    print(f"  grid spans x {ox:.0f}..{ox + (args.per_row - 1) * X_PITCH:.0f} mm, "
          f"y {oy:.0f}..{oy + (rows - 1) * Y_PITCH:.0f} mm")


if __name__ == "__main__":
    main()
