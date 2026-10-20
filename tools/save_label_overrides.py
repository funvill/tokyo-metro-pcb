"""Freeze the labels in a data file as hand placements.

After editing labels in KiCad:
    python import_labels.py DATA.json BOARD.kicad_pcb      # board -> data
    python save_label_overrides.py DATA.json OVERRIDES.json

Every station's label (and its line breaks, where set) goes into
OVERRIDES.json. build_schematic.py re-applies that file on every build and
auto_label.py --fixed never moves what is in it, so the hand layout
survives any regeneration. Delete a station's entry to hand it back to the
optimiser.
"""
import json
import sys

data, out = sys.argv[1:3]
stations = json.load(open(data, encoding="utf-8"))["stations"]
overrides = {sid: {"label": s["label"], **({"wrap": s["wrap"]} if "wrap" in s else {})}
             for sid, s in stations.items()}
json.dump(overrides, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
print(f"froze {len(overrides)} labels -> {out}")
