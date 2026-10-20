"""Turn the cached Overpass responses into the project's station list.

    python -X utf8 build_station_latlon.py

Reads  osm/routes.json    route relations with their stop members in order
       osm/stations.json  canonical station nodes with names and codes
       future_stations.json  the hand-placed stations OSM has no node for
Writes tokyo_station_latlon.json  {"station-id": [lat, lon]}
       tokyo_stations.json        id -> names, station codes, lines
       tokyo_lines.json           per line: colour, ref, ordered paths

De-duplication is **by Japanese name, not by position** (lesson B2: a wrong
station list costs a board respin). Positions alone merge stations that are
genuinely separate: Ueno-hirokoji and Ueno-okachimachi are 25 m apart and
are two stations with two LEDs. Japanese names are canonical and shared
across operators, so they are the identity. A same-name cluster more than
1 km across is reported rather than merged.
"""
import io, json, math, os, re, sys, unicodedata
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
OSM = os.path.join(HERE, "osm")

# Line metadata. Colours are the operators' official line colours; OSM's
# colour tags disagree with each other and with the official map, so these
# are written down here rather than read from the data.
LINES = {
    # Tokyo Metro
    ("東京メトロ", "G"): ("ginza",       "Ginza Line",       "#FF9500"),
    ("東京メトロ", "M"): ("marunouchi",  "Marunouchi Line",  "#F62E36"),
    ("東京メトロ", "H"): ("hibiya",      "Hibiya Line",      "#B5B5AC"),
    ("東京メトロ", "T"): ("tozai",       "Tozai Line",       "#009BBF"),
    ("東京メトロ", "C"): ("chiyoda",     "Chiyoda Line",     "#00BB85"),
    ("東京メトロ", "Y"): ("yurakucho",   "Yurakucho Line",   "#C1A470"),
    ("東京メトロ", "Z"): ("hanzomon",    "Hanzomon Line",    "#8F76D6"),
    ("東京メトロ", "N"): ("namboku",     "Namboku Line",     "#00AC9B"),
    ("東京メトロ", "F"): ("fukutoshin",  "Fukutoshin Line",  "#9C5E31"),
    # Toei
    ("都営地下鉄", "A"): ("asakusa",     "Asakusa Line",     "#E85298"),
    ("都営地下鉄", "I"): ("mita",        "Mita Line",        "#0079C2"),
    ("都営地下鉄", "S"): ("shinjuku",    "Shinjuku Line",    "#6CBB5A"),
    ("都営地下鉄", "E"): ("oedo",        "Oedo Line",        "#B6007A"),
}

OUR_REFS = {ref for _, ref in LINES}

# Lines that are not subways but are on the board, from
# osm/other_rail_stops.json. A line is here only if nearly all of it falls
# inside the map: a line showing six of its thirteen stations reads as
# broken, not as a line. That rules out the Nippori-Toneri Liner (6 of 13 in
# the crop), the Tokyo Monorail (2 of 11) and the Tokyu Setagaya line (4 of
# 10), all of which run off the edge.
#
#   SA  Toden Arakawa line / Tokyo Sakura Tram - Toei, so inside the scope
#       "Tokyo Metro + Toei"; it is a tram, which is why the subway query
#       never saw it
#   U   Yurikamome - the bay-front guideway, Tokyo-owned
#   R   Rinkai line - Tokyo-owned, joins the bay to Osaki
#   JY  JR Yamanote - not Toei and not a subway, but the loop the city is
#       read by, and 18 of its 30 stations are already LEDs, so it costs 12
EXTRA_LINES = {
    "SA": ("arakawa",   "Toden Arakawa Line", "Toei"),
    "U":  ("yurikamome", "Yurikamome",        "Yurikamome"),
    "R":  ("rinkai",     "Rinkai Line",       "Tokyo Waterfront"),
    "JY": ("yamanote",   "JR Yamanote Line",  "JR East"),
}

# Relations that are service patterns rather than routes: express and
# airport-limited-express variants whose stops are a subset of the line.
SKIP_REFS = {"Al"}

# Romanisation fixes. OSM's name:en is inconsistent: some stations carry
# macrons, some do not, some carry a parenthetical. Phase 0 settled on
# official spellings without macrons (KiCad's stroke font has no dependable
# macron glyph), so macrons are stripped and these names are pinned.
# Japanese names that are the same station under two spellings. The Toei
# Shinjuku line's western terminus is 新宿 (S-01), but its route relation
# stops at the 新線新宿 node — the Keio New Line's old name for the platforms
# the two railways share. Without this the board would carry a
# "Shinsen-Shinjuku" LED and no Shinjuku on the Shinjuku line.
ALIAS_JA = {
    "新線新宿": "新宿",
}

NAME_FIXES = {
    "明治神宮前": "Meiji-jingumae",
    "押上": "Oshiage",
    "二重橋前": "Nijubashimae",
    "溜池山王": "Tameike-sanno",
    "国会議事堂前": "Kokkai-gijidomae",
    "東京": "Tokyo",
    "大手町": "Otemachi",
    "日本橋": "Nihombashi",
    "新橋": "Shimbashi",
    "神保町": "Jimbocho",
    "三田": "Mita",
}

MACRONS = str.maketrans({
    "ā": "a", "ī": "i", "ū": "u", "ē": "e", "ō": "o",
    "Ā": "A", "Ī": "I", "Ū": "U", "Ē": "E", "Ō": "O",
})


def km(lat, lon, lat0=35.68):
    """Equirectangular projection, kilometres. Same as the Montreal build."""
    return (lon * 111.32 * math.cos(math.radians(lat0)), lat * 110.57)


def norm_ja(name):
    """Canonical form of a Japanese station name.

    The same station arrives under several spellings, and each difference
    costs it an LED or splits it into two:

    * the small and large katakana ke (市ヶ谷 / 市ケ谷) — Ichigaya,
      Nishigahara;
    * a 駅 suffix on some stop nodes;
    * the bracketed subtitle that two stations carry on one operator's
      nodes and not the other's (押上〈スカイツリー前〉 and 押上,
      二重橋前〈丸の内〉, 明治神宮前〈原宿〉);
    * ALIAS_JA, for the one station the two operators do not agree about.
    """
    name = unicodedata.normalize("NFC", name).strip()
    name = name.replace("ヶ", "ケ").replace("ヵ", "カ")
    name = re.sub(r"[〈（(][^〉）)]*[〉）)]", "", name)
    if name.endswith("駅"):
        name = name[:-1]
    name = name.strip()
    return ALIAS_JA.get(name, name)


def plain(name):
    """Official English spelling without macrons or parentheticals."""
    name = unicodedata.normalize("NFC", name).translate(MACRONS)
    name = re.sub(r"\s*[（(〈][^）)〉]*[）)〉]", "", name)
    name = name.replace("'", "").replace("’", "")
    return name.strip()


def slug(name):
    s = plain(name).lower()
    s = s.replace("ʼ", "").replace(".", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load(name):
    with io.open(os.path.join(OSM, name), encoding="utf-8") as f:
        return json.load(f)["elements"]


def main():
    routes = load("routes.json")
    rels = [e for e in routes if e["type"] == "relation"]
    stops = {e["id"]: e for e in routes if e["type"] == "node"}
    st_nodes = [e for e in load("stations.json") if e["type"] == "node"]
    try:
        other = load("other_rail_stops.json")
    except FileNotFoundError:
        other = []
    other_rels = [e for e in other if e["type"] == "relation"
                  and e["tags"].get("ref") in EXTRA_LINES]
    other_stops = {e["id"]: e for e in other if e["type"] == "node"}

    # --- stations, identified by Japanese name -------------------------
    by_ja = defaultdict(list)
    for n in st_nodes:
        t = n.get("tags", {})
        ja = t.get("name")
        if not ja:
            continue
        by_ja[norm_ja(ja)].append(n)

    def stop_ja(node):
        t = node.get("tags", {})
        ja = t.get("name")
        return norm_ja(ja) if ja else None

    # Stop nodes grouped the same way, as the fallback for a station with no
    # station node of its own: Yoyogi-Uehara is an Odakyu station and is not
    # tagged as a subway station, but the Chiyoda line terminates there.
    stops_by_ja = defaultdict(list)
    for n in list(stops.values()) + list(other_stops.values()):
        ja = stop_ja(n)
        if ja:
            stops_by_ja[ja].append(n)

    # Every stop node of a route must resolve to a station. Stop nodes are
    # on the track and carry the station's name, so the name is the join;
    # anything that fails to join is reported, never guessed.
    stations = {}       # id -> record
    ja_to_id = {}
    unresolved = defaultdict(int)

    def station_id(ja):
        if ja in ja_to_id:
            return ja_to_id[ja]
        nodes = by_ja.get(ja)
        fallback = False
        if not nodes:
            nodes = stops_by_ja.get(ja)
            fallback = True
        if not nodes:
            return None
        pts = [(n["lat"], n["lon"]) for n in nodes]
        xs = [km(*p)[0] for p in pts]
        ys = [km(*p)[1] for p in pts]
        spread = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        # Nodes whose raw Japanese name IS the canonical one come first, so
        # the English name is taken from them. Otherwise an alias wins and
        # the board gets a station called "Shinsen-Shinjuku" where Shinjuku
        # should be: the node carrying the Keio New Line's old name happened
        # to be read first.
        tags = {}
        for n in sorted(nodes, key=lambda n: n.get("tags", {}).get("name") != ja):
            for k, v in n.get("tags", {}).items():
                tags.setdefault(k, v)
        en = NAME_FIXES.get(ja) or plain(tags.get("name:en") or ja)
        sid = slug(en) or slug(ja)
        while sid in stations and stations[sid]["name_ja"] != ja:
            sid += "-2"
        # Station codes live in `ref`, semicolon-separated, and include
        # codes for lines this board does not carry (TY03, MG01 and such).
        # Only the thirteen subway letters are kept.
        # A station with several lines has one node per operator, each
        # carrying only its own codes, so the codes are unioned over the
        # whole cluster. Taking them from the first node loses most of them.
        codes = set()
        for n in nodes:
            for raw in re.split(r"[;,/]", n.get("tags", {}).get("ref", "")):
                m = re.fullmatch(r"([A-Za-z])-?(\d{1,2})", raw.strip())
                if m and m.group(1).upper() in OUR_REFS:
                    codes.add(f"{m.group(1).upper()}-{int(m.group(2)):02d}")
        codes = sorted(codes, key=lambda c: (c[0], int(c[2:])))
        stations[sid] = {
            "name": en,
            "name_ja": ja,
            "codes": codes,
            "lat": sum(p[0] for p in pts) / len(pts),
            "lon": sum(p[1] for p in pts) / len(pts),
            "nodes": len(nodes),
            "spread_km": round(spread, 3),
            "lines": [],
        }
        if fallback:
            # Position comes from the platform stop nodes, not a station
            # node; good to about 100 m, which is under a tenth of the LED
            # pitch at this scale.
            stations[sid]["from_stop_nodes"] = True
        if spread > 1.0:
            print(f"  WARNING: {ja} ({en}) has nodes {spread:.1f} km apart - "
                  f"two different stations sharing a name?")
        ja_to_id[ja] = sid
        return sid

    # --- lines and their station order ---------------------------------
    lines = {}
    for rel in rels:
        t = rel["tags"]
        key = (t.get("network"), t.get("ref"))
        if t.get("ref") in SKIP_REFS or key not in LINES:
            continue
        seq = []
        for m in rel.get("members", []):
            if m["type"] != "node" or m["ref"] not in stops:
                continue
            ja = stop_ja(stops[m["ref"]])
            if not ja:
                continue
            sid = station_id(ja)
            if sid is None:
                unresolved[ja] += 1
                continue
            if not seq or seq[-1] != sid:
                seq.append(sid)
        if len(seq) < 2:
            continue
        lines.setdefault(key, []).append((rel["id"], t.get("name", ""), seq))

    out_lines = {}
    for key, variants in sorted(lines.items(), key=lambda kv: LINES[kv[0]][0]):
        lid, lname, colour = LINES[key]
        variants.sort(key=lambda v: -len(v[2]))
        paths = []
        covered = set()
        for rid, rname, seq in variants:
            s = set(seq)
            if s <= covered:                # a direction or an express
                continue                    # pattern we already have
            if not paths:
                paths.append(seq)
            else:
                new = s - covered
                if len(new) < 1:
                    continue
                paths.append(seq)
                print(f"  {lid}: extra path from relation {rid} "
                      f"({rname[:40]}) adds {sorted(new)}")
            covered |= s
        for sid in covered:
            stations[sid]["lines"].append(lid)
        out_lines[lid] = {
            "id": lid, "name": lname, "ref": key[1], "colour": colour,
            "operator": "Tokyo Metro" if key[0] == "東京メトロ" else "Toei",
            "paths": paths,
            "stations": len(covered),
        }

    # --- the lines that are not subways --------------------------------
    for ref, (lid, lname, operator) in EXTRA_LINES.items():
        best, colour = None, None
        for rel in other_rels:
            if rel["tags"].get("ref") != ref:
                continue
            seq = []
            for m in rel.get("members", []):
                if m["type"] != "node" or m["ref"] not in other_stops:
                    continue
                ja = stop_ja(other_stops[m["ref"]])
                if not ja:
                    continue
                sid = station_id(ja)
                if sid and (not seq or seq[-1] != sid):
                    seq.append(sid)
            if best is None or len(seq) > len(best):
                best, colour = seq, rel["tags"].get("colour")
        if not best or len(best) < 2:
            print(f"  WARNING: no usable route for {ref} ({lname})")
            continue
        for sid in best:
            if lid not in stations[sid]["lines"]:
                stations[sid]["lines"].append(lid)
        out_lines[lid] = {
            "id": lid, "name": lname, "ref": ref,
            "colour": colour or "#888888", "operator": operator,
            "paths": [best], "stations": len(set(best)), "mode": "other",
        }

    # --- lines drawn by hand -------------------------------------------
    hpath = os.path.join(HERE, "hand_lines.json")
    if os.path.exists(hpath):
        with io.open(hpath, encoding="utf-8") as f:
            hand = json.load(f)
        for rec in hand["lines"]:
            missing = [s for p in rec["paths"] for s in p if s not in stations]
            if missing:
                print(f"  WARNING: {rec['id']} wants stations that do not "
                      f"exist: {missing}")
                continue
            for sid in {s for p in rec["paths"] for s in p}:
                if rec["id"] not in stations[sid]["lines"]:
                    stations[sid]["lines"].append(rec["id"])
            out_lines[rec["id"]] = {
                "id": rec["id"], "name": rec["name"], "ref": rec["ref"],
                "colour": rec["colour"], "operator": rec["operator"],
                "paths": rec["paths"], "weight": rec.get("weight", 1.0),
                "off_board": rec.get("off_board", []),
                "stations": len({s for p in rec["paths"] for s in p}),
                "mode": "hand",
            }

    # --- stations OSM has no node for ----------------------------------
    fpath = os.path.join(HERE, "future_stations.json")
    if os.path.exists(fpath):
        with io.open(fpath, encoding="utf-8") as f:
            future = json.load(f)
        for rec in future["stations"]:
            sid = rec["id"]
            stations[sid] = {
                "name": rec["name"], "name_ja": rec["name_ja"],
                "codes": rec.get("codes", []),
                "lat": rec["lat"], "lon": rec["lon"],
                "nodes": 0, "spread_km": 0.0, "lines": [],
                "status": rec["status"], "source": rec["source"],
            }
        for ins in future["insert"]:
            line = out_lines[ins["line"]]
            if ins.get("new_path"):
                line["paths"].append(ins["path"])
            else:
                path = line["paths"][ins.get("path_index", 0)]
                at = path.index(ins["after"]) + 1
                for off, sid in enumerate(ins["path"]):
                    path.insert(at + off, sid)
            for sid in ins["path"]:
                if ins["line"] not in stations[sid]["lines"]:
                    stations[sid]["lines"].append(ins["line"])
            line["stations"] = len({s for p in line["paths"] for s in p})

    # --- report and write ----------------------------------------------
    for sid, rec in stations.items():
        rec["lines"] = sorted(set(rec["lines"]))
    used = {s for l in out_lines.values() for p in l["paths"] for s in p}
    orphans = sorted(set(stations) - used)
    for sid in orphans:
        del stations[sid]

    if unresolved:
        print("\n  Stop nodes with no station node (not in the list):")
        for ja, n in sorted(unresolved.items(), key=lambda kv: -kv[1]):
            print(f"    {ja} x{n}")

    # --- cross-check the line membership against the station codes -----
    # Every station carries its official codes (G-09, M-17...) in OSM's
    # `ref` tag, assigned independently of the route relations. If a line's
    # stations are exactly the stations holding that line's letter, and the
    # highest number equals the count, the list matches the official
    # numbering — the check the official numbering map would have given us.
    print("\n  Cross-check against the official station codes:")
    for lid, l in sorted(out_lines.items(), key=lambda kv: kv[1]["ref"]):
        ref = l["ref"]
        on_line = {s for p in l["paths"] for s in p}
        coded = {sid for sid, r in stations.items()
                 if any(c[0] == ref for c in r["codes"])}
        nums = sorted(int(c[2:]) for sid in on_line for c in stations[sid]["codes"]
                      if c[0] == ref)
        missing = sorted(on_line - coded)        # on the line, no code
        extra = sorted(coded - on_line)          # coded, not on the line
        gaps = [n for n in range(1, (max(nums) if nums else 0) + 1) if n not in nums]
        ok = not missing and not extra and not gaps and len(on_line) == len(nums)
        print(f"    {ref:2s} {'OK ' if ok else 'CHECK'} {len(on_line):3d} stations, "
              f"codes {ref}-01..{ref}-{max(nums) if nums else 0:02d}"
              + (f", no code: {missing}" if missing else "")
              + (f", coded but not on the line: {extra}" if extra else "")
              + (f", numbering gaps: {gaps}" if gaps else ""))

    byop = {}
    for l in out_lines.values():
        byop.setdefault(l["operator"], set()).update(
            s for p in l["paths"] for s in p)
    metro = byop.get("Tokyo Metro", set())
    toei = byop.get("Toei", set())
    print()
    for lid, l in sorted(out_lines.items(), key=lambda kv: kv[1]["ref"]):
        print(f"  {l['ref']:2s} {l['name']:18s} {l['stations']:3d} stations"
              f"{'  (' + str(len(l['paths'])) + ' paths)' if len(l['paths']) > 1 else ''}")
    print()
    for op, st in sorted(byop.items(), key=lambda kv: -len(kv[1])):
        print(f"  {op:18s} {len(st):3d} stations")
    print(f"  Tokyo Metro and Toei share {len(metro & toei)}")
    print(f"  TOTAL {len(stations)} stations = {len(stations)} LEDs")
    print(f"  line-stations (sum per line) {sum(l['stations'] for l in out_lines.values())}")

    def write(name, obj):
        with io.open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        print(f"  wrote {name}")

    write("tokyo_station_latlon.json",
          {sid: [round(r["lat"], 6), round(r["lon"], 6)] for sid, r in stations.items()})
    write("tokyo_stations.json", stations)
    write("tokyo_lines.json", out_lines)


if __name__ == "__main__":
    main()
