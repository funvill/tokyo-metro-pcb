"""Turn the OSM structures into per-leg alignments for build_tokyo --crossings.

The official Tokyo subway map draws no water at all and ignores every
structure: the Tozai Line's 1,236 m Arakawa truss is an unremarked straight
segment, and the Rainbow Bridge is not depicted. Drawing the real alignment
is therefore a deliberate departure, not a correction - but on a map that
does show the coastline, a line cutting the bay in a straight diagonal is
the one thing that reads as plainly wrong.

Only the crossings with a structure worth honouring are listed. The subway
crossings of the Sumida are plain bored tunnel with no named structure, so
there is nothing there to follow and the straight line is right.

    python make_crossings.py osm/crossings.json crossings.json
"""
import io
import json
import math
import sys

# leg -> the OSM ways that carry it, and what the structure is
LEGS = {
    "yurikamome": {
        "shibaura-futo|odaiba-kaihinkoen": {
            "ways": [500180268, 275936305],
            "what": "Rainbow Bridge lower deck, with the Shibaura loop ramp",
        },
    },
    "tozai": {
        "minami-sunamachi|nishi-kasai": {
            "ways": [172320499],
            "what": "Arakawa-Nakagawa Bridge, 1,236 m Warren truss over both rivers",
        },
    },
    "rinkai": {
        "tokyo-teleport|tennozu-isle": {
            "ways": [4854227, 361135388],
            "what": "Tokyo Port Tunnel, immersed tube under the bay",
        },
        "shin-kiba|shinonome": {
            "ways": [241575820, 862831396],
            "what": "viaduct over the Tatsumi and Akebono canals",
        },
    },
    "yurakucho": {
        "tatsumi|shin-kiba": {
            "ways": [241575938, 793837465],
            "what": "viaduct over the Akebono canal, its only crossing above ground",
        },
    },
}


def chain(ways, geoms):
    """Join the ways end to end, flipping each as needed.

    They come back from Overpass in whatever order the ids were given and
    each may run either way, so matching endpoints is the only thing that
    puts the spiral at Shibaura the right way round.
    """
    runs = [list(geoms[w]) for w in ways if w in geoms]
    if not runs:
        return []
    out = runs.pop(0)
    while runs:
        best = None
        for i, r in enumerate(runs):
            for flip in (False, True):
                cand = r[::-1] if flip else r
                for tail in (False, True):
                    anchor = out[0] if tail else out[-1]
                    d = math.dist(anchor, cand[0] if not tail else cand[-1])
                    if best is None or d < best[0]:
                        best = (d, i, flip, tail)
        _, i, flip, tail = best
        r = runs.pop(i)
        if flip:
            r = r[::-1]
        out = (r + out) if tail else (out + r)
    return out


def main():
    src, dst = sys.argv[1], sys.argv[2]
    data = json.load(io.open(src, encoding="utf-8"))
    geoms = {e["id"]: [(p["lat"], p["lon"]) for p in e.get("geometry", [])]
             for e in data.get("elements", [])}

    out = {}
    for lid, legs in LEGS.items():
        for key, spec in legs.items():
            pts = chain(spec["ways"], geoms)
            if len(pts) < 3:
                print(f"  {lid} {key}: no geometry, skipped")
                continue
            # Simplify by SHAPE, not by spacing. Even thinning keeps a
            # point every N metres along a straight truss, and each of
            # those short sub-segments lands in its own corridor bucket,
            # so the fanned lanes hop from one to the next and the bridge
            # draws as a zigzag. Douglas-Peucker keeps the spiral and
            # throws away the straight, which is what the map needs.
            from shapely.geometry import LineString
            simple = LineString(pts).simplify(0.00025)    # about 28 m
            keep = list(simple.coords)
            out.setdefault(lid, {})[key] = [[round(a, 6), round(b, 6)]
                                            for a, b in keep]
            print(f"  {lid:11s} {key:38s} {len(pts):3d} -> {len(keep):3d} pts"
                  f"  {spec['what']}")

    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", dst)


if __name__ == "__main__":
    main()
