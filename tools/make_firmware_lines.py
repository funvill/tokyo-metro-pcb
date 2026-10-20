"""Write the firmware's line colour table from the data, in place.

    python -X utf8 make_firmware_lines.py [../input/tokyo_lines.json] \
        [../firmware/src/main.cpp]

The per-line LED index arrays (`LINE_GINZA`, `LINE_GINZA_COUNT`, ...) are
generated into `firmware/include/firmware_tables.h` by `export_placement.py`.
This writes the other half: one `CRGB` per line in the operator's own colour,
and the `routes[]` table that drives the animation. It replaces everything
between the two markers in main.cpp, so re-running it after a line is added
or a colour corrected is safe.

Train counts are one per twelve stations, one to four, so a 38-station Ōedo
loop carries more traffic than an 8-station Rinkai line.

Two colour pairs are close enough to be worth knowing about on real LEDs:
Chiyoda (#00BB85) against Namboku (#00AC9B), and Rinkai (#00389E) against
the Shinkansen (#2E3192). They are the operators' own colours, so they stay;
the animation can tell them apart by never running both at once if it turns
out to matter.
"""
import io
import json
import os
import sys

START = "// --- generated line table: make_firmware_lines.py ---"
END = "// --- end generated line table ---"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    lines_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        here, "..", "input", "tokyo_lines.json")
    cpp_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        here, "..", "firmware", "src", "main.cpp")

    with io.open(lines_path, encoding="utf-8") as f:
        lines = json.load(f)

    out = [START,
           "// One CRGB per line, in the operator's own colour, and the",
           "// routes[] table the animation walks. Generated - do not edit."]
    rows = []
    for lid, l in sorted(lines.items(), key=lambda kv: -kv[1]["stations"]):
        base = lid.upper().replace("-", "_")
        c = l["colour"].lstrip("#")
        trains = max(1, min(4, round(l["stations"] / 12)))
        rows.append((base, l["name"], c, trains, l["stations"]))
    for base, name, c, trains, n in rows:
        out.append(f"const CRGB COLOR_{base} = CRGB(0x{c[0:2]}, 0x{c[2:4]}, "
                   f"0x{c[4:6]});  // {name}, {n} stations")
    out.append("")
    out.append("Route routes[] = {")
    for base, name, c, trains, n in rows:
        out.append(f"  {{LINE_{base}, LINE_{base}_COUNT, COLOR_{base}, "
                   f"{trains}, {{0}}, {{0}}}},")
    out.append("};")
    out.append(END)
    block = "\n".join(out)

    with io.open(cpp_path, encoding="utf-8") as f:
        src = f.read()
    if START in src and END in src:
        a = src.index(START)
        b = src.index(END) + len(END)
        src = src[:a] + block + src[b:]
    else:
        raise SystemExit(
            f"markers not found in {cpp_path}; add\n  {START}\n  {END}\n"
            "around the colour and routes[] block first")
    with io.open(cpp_path, "w", encoding="utf-8") as f:
        f.write(src)
    print(f"wrote {len(rows)} lines into {os.path.basename(cpp_path)}")


if __name__ == "__main__":
    main()
