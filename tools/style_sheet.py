"""One labelled frame for every candidate map style, so they compare.

Each style render carries its title and its facts burnt into the image, so a
screenshot is self-describing when it comes back as a markup.

    import style_sheet
    style_sheet.render(
        "../test-results/style-a.png",
        title="A - Schematic lines on true-scale land",
        notes=["octolinear runs, rounded bends", "land placed rigidly"],
        MM=positions_in_mm, lines=line_records, shapes=shapes_in_mm,
        water=shapely_geometry_in_mm)

Conventions, shared by every style so the comparison is fair:

* positions and all geometry are in **board millimetres**, origin top-left,
  y down, as the KiCad exporter uses;
* `lines` are the records from tokyo-*.json (`id`, `name`, `color`, `paths`);
* `shapes[line_id]["a|b"]` are the extra points drawn between a and b, in
  board mm (tokyo-*.json stores them in canvas units: multiply by
  `board_scale`);
* `water` is a shapely geometry, or None for a style that draws no land.

`palette="board"` renders what the board will actually look like - white
silkscreen routes on green solder mask with ENIG-gold bare-copper water -
rather than the operators' line colours. Both are worth looking at: the
colour version is how the map reads, the board version is what gets etched.
"""
import io
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

MASK = "#2f5442"        # green solder mask
COPPER = "#f2d43a"      # ENIG gold, bare copper
SILK = "#f4f4ee"        # white silkscreen
INK = "#11190f"

BOARD_W_MM = 400.0
BOARD_H_MM = 292.0
BAR_MM = 26.0           # title bar height, in board mm, above the board


def load(path):
    """A tokyo-*.json file -> (MM, lines, shapes, water_rings), all in mm."""
    with io.open(path, encoding="utf-8") as f:
        d = json.load(f)
    B = d["board_scale"]
    MM = {k: (v["x"] * B, v["y"] * B) for k, v in d["stations"].items()}
    shapes = {}
    for line in d["lines"]:
        if line.get("stubs"):
            line["stubs"] = [[[x * B, y * B] for x, y in e]
                             for e in line["stubs"]]
        if line.get("shape"):
            shapes[line["id"]] = {k: [(x * B, y * B) for x, y in v]
                                  for k, v in line["shape"].items()}
    rings = [[(x * B, y * B) for x, y in g["points"]] for g in d.get("geo", [])]
    return d, MM, d["lines"], shapes, rings


def render(out, title, notes, MM, lines, shapes=None, water=None, rings=None,
           palette="colour", line_w=2.4, station_ms=3.4, station="dot",
           board=(BOARD_W_MM, BOARD_H_MM), dpi=100, labels=None, label_size=3.6,
           label_font=None):
    """Draw one style into a labelled frame. See the module docstring."""
    shapes = shapes or {}
    bw, bh = board
    fig_w = 17.0
    fig_h = fig_w * (bh + BAR_MM) / bw
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor(INK)
    ax.set_position([0, 0, 1, 1])
    ax.set_xlim(0, bw)
    ax.set_ylim(bh, -BAR_MM)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)

    # the board itself
    ax.add_patch(Rectangle((0, 0), bw, bh, facecolor=MASK, edgecolor="none",
                           zorder=0))

    water_colour = COPPER
    for ring in (rings or []):
        ax.fill([p[0] for p in ring], [p[1] for p in ring],
                color=water_colour, lw=0, zorder=1)
    if water is not None:
        for g in getattr(water, "geoms", [water]):
            if getattr(g, "geom_type", "") != "Polygon":
                continue
            x, y = g.exterior.xy
            ax.fill(x, y, color=water_colour, lw=0, zorder=1)
            for r in g.interiors:
                x, y = r.xy
                ax.fill(x, y, color=MASK, lw=0, zorder=1)

    for line in lines:
        colour = SILK if palette == "board" else line["color"]
        # A line may ask to be drawn heavier than the rest: the Shinkansen
        # is not a metro line and should not read as one.
        lw = line_w * line.get("weight", 1.0)
        # A line that leaves the map runs on to the board edge rather than
        # stopping at its last station: the board is a window on a bigger
        # network, and a track that stops dead reads as a terminus.
        for (x0, y0), (x1, y1) in line.get("stubs", []):
            ax.plot([x0, x1], [y0, y1], color=colour, lw=lw,
                    solid_capstyle="butt", zorder=2)
        shape = shapes.get(line["id"], {})
        for path in line["paths"]:
            for a, b in zip(path, path[1:]):
                if a == b or a not in MM or b not in MM:
                    continue
                via = shape.get(f"{a}|{b}") or shape.get(f"{b}|{a}") or []
                pts = [MM[a]] + list(via) + [MM[b]]
                ax.plot([p[0] for p in pts], [p[1] for p in pts], color=colour,
                        lw=lw, solid_capstyle="round", zorder=2)

    if station != "none":
        for sid, (x, y) in MM.items():
            if station == "ring":
                ax.plot(x, y, "o", ms=station_ms, mfc="none",
                        mec=SILK if palette == "board" else "#1a1a1a",
                        mew=0.9, zorder=3)
            else:
                ax.plot(x, y, "o", ms=station_ms, mfc=SILK if palette == "board" else "white",
                        mec=INK if palette == "board" else "#1a1a1a", mew=0.6, zorder=3)
    for sid, text in (labels or {}).items():
        if sid in MM:
            x, y = MM[sid]
            ax.text(x + 1.0, y - 1.0, text, fontsize=label_size, color=SILK,
                    zorder=4, ha="left", va="bottom",
                    **({"fontname": label_font} if label_font else {}))

    # title bar
    ax.add_patch(Rectangle((0, -BAR_MM), bw, BAR_MM, facecolor=INK,
                           edgecolor="none", zorder=5))
    ax.text(5, -BAR_MM + 10.5, title, color="#ffffff", fontsize=17,
            va="center", ha="left", zorder=6, fontweight="bold")
    ax.text(5, -BAR_MM + 20.0, "   ".join(notes), color="#9fb8a6", fontsize=10,
            va="center", ha="left", zorder=6)
    plt.savefig(out, dpi=dpi, facecolor=INK)
    plt.close(fig)
    print("wrote", os.path.normpath(out))
    return out
