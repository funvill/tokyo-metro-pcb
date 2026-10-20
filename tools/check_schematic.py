"""Check a schematic for symbols that overlap each other.

    python -X utf8 check_schematic.py ../hardware/tokyo-metro-pcb.kicad_sch [-v]

A generated sheet can be electrically perfect and still unreadable: nothing
in the netlist notices that a decoupling capacitor is sitting on top of a
global label. KiCad's own ERC does not check it either.

Each symbol's outline comes from its library definition - the rectangles,
polylines, circles and pin endpoints in `lib_symbols` - so the box is the
symbol's real extent rather than a guess. The box is then rotated and moved
to the instance's position. Two symbols overlap when their boxes do, with a
small tolerance so touching edges are not reported.

Power symbols and labels are deliberately placed close to things, so the
tolerance is generous; the point is to catch a body sitting on a body.
"""
import argparse
import io
import math
import re
import sys
from collections import defaultdict

TOL = 0.2        # mm of overlap to ignore (touching edges, pin stubs)
TEXT_W = 0.9     # character width as a fraction of text height, measured
                 # from a render: KiCad's stroke font runs about 0.85 x
                 # size and a little wider in practice (lesson B6)


def top_blocks(text):
    out, depth, start = [], 0, None
    for i, c in enumerate(text):
        if c == "(":
            if depth == 1:
                start = i
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 1 and start is not None:
                out.append(text[start:i + 1])
                start = None
    return out


def lib_boxes(text):
    """{lib symbol name: (minx, miny, maxx, maxy)} from lib_symbols."""
    m = re.search(r'\(lib_symbols\b', text)
    if not m:
        return {}
    # the lib_symbols block, balanced
    depth, start = 0, m.start()
    for i in range(m.start(), len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                lib = text[start:i + 1]
                break
    else:
        return {}

    boxes = {}
    # each top-level (symbol "name" ...) inside lib_symbols
    # entries are keyed by the full lib_id, "JLCPCB-C5349954:XL-1615..."
    for m in re.finditer(r'\n\t\t\(symbol "([^"]+)"', lib):
        name = m.group(1)
        depth, start = 0, m.start()
        for i in range(m.start(), len(lib)):
            if lib[i] == "(":
                depth += 1
            elif lib[i] == ")":
                depth -= 1
                if depth == 0:
                    body = lib[start:i + 1]
                    break
        else:
            continue
        xs, ys = [], []
        for a, b in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', body):
            xs.append(float(a)); ys.append(float(b))
        for tag in ("start", "end", "center", "mid"):
            for a, b in re.findall(r'\(' + tag + r' ([-\d.]+) ([-\d.]+)\)', body):
                xs.append(float(a)); ys.append(float(b))
        for a, b in re.findall(r'\(pin \w+ \w+\s*\(at ([-\d.]+) ([-\d.]+)', body):
            xs.append(float(a)); ys.append(float(b))
        if xs:
            boxes[name] = (min(xs), min(ys), max(xs), max(ys))
    return boxes


def rotate_box(box, deg):
    x0, y0, x1, y1 = box
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = [(x * ca - y * sa, x * sa + y * ca) for x, y in corners]
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def overlap(a, b, tol=TOL):
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return ox > tol and oy > tol


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sch")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--tol", type=float, default=TOL)
    args = ap.parse_args()

    with io.open(args.sch, encoding="utf-8") as f:
        s = f.read()
    s_all = s
    boxes = lib_boxes(s)
    if args.verbose:
        print(f"{len(boxes)} library symbols with an outline")

    placed = []
    missing = set()
    for b in top_blocks(s):
        if not b.startswith("(symbol"):
            continue
        lib = re.search(r'\(lib_id "([^"]+)"\)', b)
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', b)
        ref = re.search(r'\(property "Reference" "([^"]+)"', b)
        if not (lib and at):
            continue
        name = lib.group(1)
        if name not in boxes:
            missing.add(name)
            continue
        x, y, rot = float(at.group(1)), float(at.group(2)), float(at.group(3))
        bx = rotate_box(boxes[name], rot)
        # KiCad's schematic y axis points down relative to library space
        placed.append((ref.group(1) if ref else "?",
                       (x + bx[0], y - bx[3], x + bx[2], y - bx[1])))
        # Visible property text prints, so it collides like anything else.
        # The cloned row capacitors' reference text ran straight through the
        # row's input label and the symbol outlines never touched.
        for pm in re.finditer(r'\(property "([^"]+)" "([^"]*)"\s*\(at '
                              r'([-\d.]+) ([-\d.]+)( [-\d.]+)?\)', b):
            pname, pval, px, py, _ = pm.groups()
            # Only Reference and Value print by default; Datasheet,
            # Description, Footprint and the JLCPCB fields are metadata and
            # are hidden, so counting them buries the real collisions in
            # 900 false ones.
            if pname not in ("Reference", "Value") or not pval:
                continue
            # The whole property block, balanced - a fixed window misses the
            # (hide yes) on a long one, which is how every LED's hidden Value
            # text ended up being reported as colliding with its neighbour's.
            depth, k = 0, pm.start()
            while k < len(b):
                if b[k] == "(":
                    depth += 1
                elif b[k] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                k += 1
            tail = b[pm.end():k]
            if "(hide yes)" in tail:
                continue
            size = re.search(r'\(size ([\d.]+) ([\d.]+)\)', tail)
            h = float(size.group(2)) if size else 1.27
            w = len(pval) * h * TEXT_W
            px, py = float(px), float(py)
            if "(justify right)" in tail:
                tb = (px - w, py - h / 2, px, py + h / 2)
            elif "(justify left)" in tail:
                tb = (px, py - h / 2, px + w, py + h / 2)
            else:
                tb = (px - w / 2, py - h / 2, px + w / 2, py + h / 2)
            placed.append((f"{ref.group(1) if ref else '?'}.{pname}", tb))

    if missing:
        print(f"  no outline for: {', '.join(sorted(missing))}")

    # Global labels are not symbols, but a label sitting on a capacitor is
    # exactly the kind of collision this is for. Their box is estimated from
    # the text: KiCad's default label text is 1.27 mm high and about 0.6 of
    # that per character, plus the pointed end.
    for b in top_blocks(s_all):
        if not b.startswith("(global_label") and not b.startswith("(label"):
            continue
        nm = re.match(r'\((?:global_)?label "([^"]+)"', b)
        at = re.search(r'\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)', b)
        if not (nm and at):
            continue
        x, y, rot = float(at.group(1)), float(at.group(2)), float(at.group(3))
        w = len(nm.group(1)) * 1.27 * TEXT_W + 2.6
        h = 1.9
        box = (0, -h / 2, w, h / 2) if rot in (0, 360) else (-w, -h / 2, 0, h / 2)
        if rot in (90, 270):
            box = (-h / 2, 0, h / 2, w) if rot == 90 else (-h / 2, -w, h / 2, 0)
        placed.append((f"label:{nm.group(1)}",
                       (x + box[0], y + box[1], x + box[2], y + box[3])))

    # bucket by grid cell so this stays quick at 300+ symbols
    CELL = 25.0
    grid = defaultdict(list)
    for i, (ref, bx) in enumerate(placed):
        for cx in range(int(bx[0] // CELL), int(bx[2] // CELL) + 1):
            for cy in range(int(bx[1] // CELL), int(bx[3] // CELL) + 1):
                grid[(cx, cy)].append(i)

    hits = set()
    for cell in grid.values():
        for ii in range(len(cell)):
            for jj in range(ii + 1, len(cell)):
                i, j = cell[ii], cell[jj]
                if not overlap(placed[i][1], placed[j][1], args.tol):
                    continue
                # a symbol overlapping its own reference or value text is
                # ordinary KiCad placement, not a collision
                ra = placed[i][0].split(".")[0]
                rb = placed[j][0].split(".")[0]
                if ra == rb:
                    continue
                hits.add((min(i, j), max(i, j)))

    print(f"{len(placed)} placed symbols, {len(hits)} overlapping pair(s)")
    by_ref = defaultdict(int)
    for i, j in sorted(hits):
        a, b = placed[i], placed[j]
        by_ref[a[0]] += 1
        by_ref[b[0]] += 1
        if args.verbose or len(hits) <= 40:
            ox = min(a[1][2], b[1][2]) - max(a[1][0], b[1][0])
            oy = min(a[1][3], b[1][3]) - max(a[1][1], b[1][1])
            print(f"    {a[0]:>10s} x {b[0]:<10s} overlap {ox:.2f} x {oy:.2f} mm "
                  f"at ({max(a[1][0], b[1][0]):.1f}, {max(a[1][1], b[1][1]):.1f})")
    if hits and not args.verbose and len(hits) > 40:
        worst = sorted(by_ref.items(), key=lambda kv: -kv[1])[:10]
        print("    most involved:", ", ".join(f"{r}({n})" for r, n in worst))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
