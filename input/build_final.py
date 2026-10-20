"""The style the board is being built in, assembled from the ones that won.

    python -X utf8 build_final.py

Settled 2026-10-18 after the eight-style comparison in docs/styles.md:

* **the tighter crop** - the layout built with `--leg-cap 15`, so a leg
  longer than 15 mm is drawn at 15 mm and the outer tails stop spending
  board on Chiba;
* **style A geometry** - octolinear runs with rounded bends, on true-scale
  land placed rigidly;
* **the thick weight** - routes at ROUTE_MM, not the Vancouver hairline;
* **English names** at the real 1.1 mm silkscreen height;
* **one offset corridor** - the eight-leg Yurakucho + Fukutoshin run in the
  north-west is drawn as two parallel tracks; every other shared corridor
  keeps a single centreline, because a one-leg corridor tapers in and out
  over so little distance that it reads as a drawing error.

The corridor machinery is imported from `style_c`'s sibling
`style_d_offset.py` rather than copied, so there is one implementation of it.
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "tools"))

import style_sheet                      # noqa: E402
import style_d_offset as OFFSET         # noqa: E402

DATA = os.path.join(HERE, "tokyo-schematic-cap15.json")
OUT = os.path.join(HERE, "..", "test-results")

MIN_CORRIDOR_LEGS = 3    # below this an offset corridor reads as a lens
                         # (--offset none turns offsetting off altogether,
                         #  which is the settled choice: on the board every
                         #  route is the same white silkscreen, so two
                         #  parallel tracks say nothing a single one does
                         #  not, and the overlap is honest about the two
                         #  lines sharing the tunnel)
GAP_MM = 1.6             # between the two tracks; the LED body is ~2.5 mm
ROUTE_MM = 0.9           # silkscreen route width - the thick weight
TEXT_MM = 1.1            # silkscreen text height, as Montreal
# KiCad 10 plots TrueType, and a condensed face is both narrower and - at
# this height - thicker in the stem than KiCad's own stroke font. See
# docs/styles.md: 0.70 mm per character against 1.03, and a 0.164 mm stem
# against 0.140 mm, so it is easier to print as well as easier to fit.
LABEL_FONT = "Franklin Gothic Medium Cond"

# style_sheet draws the 400 mm board 17 inches wide, so a millimetre on the
# board is this many points on the figure. Line widths and text sizes are
# written in millimetres and converted here, rather than guessed in points.
PT_PER_MM = 17.0 * 72.0 / style_sheet.BOARD_W_MM


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--offset", choices=["long", "none"], default="none",
                    help="long: draw corridors of 3+ legs as parallel tracks. "
                         "none: every shared corridor overlaps on one track.")
    args = ap.parse_args()
    d, MM, lines, _, rings = style_sheet.load(args.data)
    # The board size travels with the data: a square board renders square.
    board = (d["canvas_mm"] * d["board_scale"], d["canvas_h_mm"] * d["board_scale"])
    names = {k: v["name"] for k, v in d["stations"].items()}

    shared = OFFSET.shared_legs(lines)
    cors = OFFSET.corridors(shared)
    keep = ([] if args.offset == "none"
            else [c for c in cors if len(c["stations"]) - 1 >= MIN_CORRIDOR_LEGS])
    drop = [c for c in cors if c not in keep]
    print(f"{len(shared)} shared legs in {len(cors)} corridors")
    for c in keep:
        print(f"  offset:  {'+'.join(c['lines']):26s} "
              f"{len(c['stations']) - 1} legs: {c['stations'][0]} .. {c['stations'][-1]}")
    for c in drop:
        print(f"  single:  {'+'.join(c['lines']):26s} "
              f"{len(c['stations']) - 1} leg(s)")

    off, which = OFFSET.leg_offsets(keep, MM, GAP_MM)
    track, out_lines, shapes = OFFSET.build_tracks(lines, MM, off, which)

    notes = [os.path.basename(args.data),
             f"board {board[0]:.0f} x {board[1]:.0f} mm",
             f"routes {ROUTE_MM:.1f} mm, names {TEXT_MM:.1f} mm",
             (f"{len(keep)} corridor offset at {GAP_MM:.1f} mm, {len(drop)} overlapped"
              if keep else f"all {len(cors)} shared corridors overlapped on one track"),
             f"{len(d['stations'])} LEDs"]
    title = "The board style: A, tighter crop, thick routes, names"

    sfx = args.suffix
    style_sheet.render(os.path.join(OUT, f"style-final{sfx}.png"), title=title,
                       notes=notes, MM=track, lines=out_lines, shapes=shapes,
                       rings=rings, palette="colour", board=board,
                       line_w=ROUTE_MM * PT_PER_MM, station="dot",
                       station_ms=4.0)
    style_sheet.render(os.path.join(OUT, f"style-final-board{sfx}.png"),
                       title=title + "  —  as etched", notes=notes, MM=track,
                       lines=out_lines, shapes=shapes, rings=rings,
                       palette="board", board=board,
                       line_w=ROUTE_MM * PT_PER_MM,
                       station="ring", station_ms=5.0)
    style_sheet.render(os.path.join(OUT, f"style-final-names{sfx}.png"),
                       title=title + "  —  with every name",
                       notes=notes + ["labels unplaced: straight off the station"],
                       MM=track, lines=out_lines, shapes=shapes, rings=rings,
                       palette="board", board=board,
                       line_w=ROUTE_MM * PT_PER_MM,
                       station="ring", station_ms=4.0,
                       labels=names, label_size=TEXT_MM * PT_PER_MM,
                       label_font=LABEL_FONT)

    if keep:
        xs = [MM[s][0] for s in keep[0]["stations"]]
        ys = [MM[s][1] for s in keep[0]["stations"]]
        OFFSET.crop(os.path.join(OUT, f"style-final-corridor{sfx}.png"),
                    f"{' + '.join(keep[0]['lines'])} offset {GAP_MM:.1f} mm",
                    track, out_lines, shapes, rings,
                    ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2),
                    ((max(xs) - min(xs)) / 2 + 10, (max(ys) - min(ys)) / 2 + 10))

    cx, cy = MM["otemachi"]
    OFFSET.crop(os.path.join(OUT, f"style-final-core{sfx}.png"),
                "the central cluster at the thick weight",
                track, out_lines, shapes, rings, (cx, cy), (55, 42))


if __name__ == "__main__":
    main()
