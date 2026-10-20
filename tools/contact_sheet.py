"""Tile the labelled style renders into one sheet for side-by-side review.

    python -X utf8 contact_sheet.py ../test-results/style-sheet.png \
        ../test-results/style-a-schematic.png ../test-results/style-b-natural.png ...

Each input already carries its own title bar (see style_sheet.py), so this
only lays them out: two columns, in the order given, on the same dark
background.
"""
import os
import sys

from PIL import Image

COLS = 2
PAD = 24
BG = (17, 25, 15)


def main():
    out, sources = sys.argv[1], sys.argv[2:]
    if not sources:
        raise SystemExit("usage: contact_sheet.py OUT.png IN.png [IN.png ...]")
    images = []
    for s in sources:
        if not os.path.exists(s):
            print(f"  missing, skipped: {s}")
            continue
        images.append(Image.open(s).convert("RGB"))
    if not images:
        raise SystemExit("nothing to tile")

    cell_w = max(im.width for im in images)
    scaled = []
    for im in images:
        if im.width != cell_w:
            h = round(im.height * cell_w / im.width)
            im = im.resize((cell_w, h), Image.LANCZOS)
        scaled.append(im)

    rows = (len(scaled) + COLS - 1) // COLS
    row_h = [max(im.height for im in scaled[r * COLS:(r + 1) * COLS])
             for r in range(rows)]
    sheet = Image.new("RGB", (COLS * cell_w + (COLS + 1) * PAD,
                              sum(row_h) + (rows + 1) * PAD), BG)
    y = PAD
    for r in range(rows):
        x = PAD
        for im in scaled[r * COLS:(r + 1) * COLS]:
            sheet.paste(im, (x, y))
            x += cell_w + PAD
        y += row_h[r] + PAD
    sheet.save(out)
    print(f"wrote {os.path.normpath(out)}  ({sheet.width} x {sheet.height}, "
          f"{len(scaled)} styles)")


if __name__ == "__main__":
    main()
