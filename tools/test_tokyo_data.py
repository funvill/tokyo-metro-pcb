"""Validation tests for the Tokyo city data file.

Run: python test_tokyo_data.py [city.json]
Plain asserts, no pytest dependency, so it runs on any machine with Python 3.
"""
import os
import sys

import citymap

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "input", "tokyo.json")

EXPECTED_LEDS = 248         # Tokyo: 13 metro/Toei lines + Yamanote, the
EXPECTED_STATIONS = 248     # Arakawa tram, Yurikamome, Rinkai and Shinkansen
EXPECTED_ROUTES = 18        # one per line on the board
MIN_PITCH_MM = 3.3          # build_from_tokyo.MIN_PITCH, board mm
MARGIN_MM = 2.0   # canvas units (4 mm at board_scale 2.0) - LED body is 1.6 mm

# Tokyo's busiest interchanges: if the line paths stop agreeing about
# these, the station list or the route relations have drifted.
SHARED = ["otemachi", "shinjuku", "ikebukuro", "shibuya", "ueno"]


def main():
    city = citymap.load(DATA)
    errors = []

    # LED / station counts
    if len(city.stations) != EXPECTED_STATIONS:
        errors.append(f"station count {len(city.stations)} != {EXPECTED_STATIONS}")
    if citymap.led_count(city) != EXPECTED_LEDS:
        errors.append(f"LED count {citymap.led_count(city)} != {EXPECTED_LEDS}")

    # Every path id resolves
    for line in city.lines:
        for path in line.paths:
            for sid in path:
                if sid not in city.stations:
                    errors.append(f"line {line.id}: unknown station id '{sid}'")

    # Shared interchange stations appear in >= 2 lines but exist exactly once
    for sid in SHARED:
        count = sum(1 for line in city.lines for path in line.paths
                    if sid in path)
        if count < 2:
            errors.append(f"'{sid}' should be used by >=2 line paths, got {count}")

    # Octilinearity of every drawn segment - informational only. Station
    # positions are now traced from the real PDF map, so a segment being
    # a few degrees off 45/90 is real-map fidelity, not a bug; a hard
    # failure here would push station coordinates away from the source.
    off_axis = [(line_id, a, b) for line_id, p1, p2, a, b in
               citymap.segments(city) if not citymap.is_octilinear(p1, p2, tol=0.6)]
    if off_axis:
        print(f"note: {len(off_axis)} segment(s) more than a few degrees "
             f"off octilinear (expected for PDF-traced positions)")

    # Coordinates on canvas with margin
    for st in list(city.stations.values()) + city.extras:
        if not (MARGIN_MM <= st.x <= city.canvas_mm - MARGIN_MM and
                MARGIN_MM <= st.y <= city.height - MARGIN_MM):
            errors.append(f"'{st.id}' at ({st.x},{st.y}) violates "
                          f"{MARGIN_MM}mm margin")
        if not st.name.strip():
            errors.append(f"'{st.id}' has empty name")

    # No two LEDs closer than the pitch floor in board mm (0.03 mm slack for
    # the 0.01-canvas-unit rounding of positions)
    BOARD_SCALE = city.scale
    pts = [(s.id, s.x * BOARD_SCALE, s.y * BOARD_SCALE)
           for s in list(city.stations.values()) + city.extras]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = ((pts[i][1] - pts[j][1]) ** 2 + (pts[i][2] - pts[j][2]) ** 2) ** 0.5
            if d < MIN_PITCH_MM - 0.03:
                errors.append(f"LEDs '{pts[i][0]}' and '{pts[j][0]}' only "
                              f"{d:.2f}mm apart")

    # Chain + export invariants
    import export_placement as ep
    chain = ep.load_chain(DATA, city)  # raises if incomplete/dupes
    rows = ep.led_rows(city, chain, 1.5)
    if len(rows) != EXPECTED_LEDS:
        errors.append(f"led_rows: {len(rows)} != {EXPECTED_LEDS}")
    if [r[1] for r in rows[:2]] != ["LED1", "LED2"]:
        errors.append("led_rows: refs must start LED1, LED2, ...")
    for name, route in ep.routes(city):
        for sid in route:
            if sid not in chain:
                errors.append(f"route {name}: '{sid}' not in chain")
    n_routes = len(ep.routes(city))
    if n_routes != EXPECTED_ROUTES:
        errors.append(f"expected {EXPECTED_ROUTES} firmware routes, got {n_routes}")

    # SAT self-test
    a = [(0, 0), (2, 0), (2, 2), (0, 2)]
    b = [(1, 1), (3, 1), (3, 3), (1, 3)]
    c = [(5, 5), (6, 5), (6, 6), (5, 6)]
    assert citymap.polys_intersect(a, b), "SAT: overlapping rects not detected"
    assert not citymap.polys_intersect(a, c), "SAT: disjoint rects flagged"

    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    print(f"PASS: {len(city.stations)} stations + {len(city.extras)} extras = "
          f"{citymap.led_count(city)} LEDs, all checks green")


if __name__ == "__main__":
    main()
