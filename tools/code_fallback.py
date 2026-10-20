"""Give a station its Tokyo station code to show when its name will not fit.

Forty-six of the 248 stations have no collision-free label position at all -
not one of the ~200 candidates the optimiser tries. For those the scoring
weights are irrelevant, which is why making leaders or rotation cheaper
changed nothing: the optimiser is already choosing the least bad of a set
that is entirely bad.

Shrinking the text barely helps (46 -> 35 at 0.9 mm, below the size the
font was chosen for). What does help is saying less. Tokyo already has the
answer: every station carries a line letter and a number, and the official
map prints them. "G-09" is four characters where "Ginza-itchome" is
thirteen, and on this map it drops the unlabelled count from 46 to 22.

This writes the code into each stuck station's `short` field, which
auto_label and citymap already understand - it costs +8 in the score, so a
station only falls back to its code when the full name genuinely will not
place.

    python code_fallback.py ../input/tokyo.json
"""
import io
import json
import sys

import check_fit
import citymap

import auto_label


def stuck_stations(path):
    city = citymap.load(path)
    ctx = check_fit.Context(city, city.scale, citymap.TEXT_H, False)
    out = []
    for st in list(city.stations.values()):
        keep = dict(st.label)
        clean = False
        for cand in auto_label.candidates(st):
            st.label = cand
            if not ctx.collisions_for(st.id, getattr(ctx, "boxes", None)):
                clean = True
                break
        st.label = keep
        if not clean:
            out.append(st.id)
    return out


def main():
    path = sys.argv[1]
    stuck = stuck_stations(path)
    d = json.load(io.open(path, encoding="utf-8"))
    given, missing = 0, []
    for sid in stuck:
        codes = d["stations"][sid].get("codes") or []
        if not codes:
            missing.append(sid)
            continue
        d["stations"][sid]["short"] = codes[0]
        given += 1
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"{len(stuck)} stations have no clean label position")
    print(f"  gave {given} of them their station code as a fallback")
    if missing:
        print(f"  {len(missing)} have no code at all: {', '.join(sorted(missing))}")


if __name__ == "__main__":
    main()
