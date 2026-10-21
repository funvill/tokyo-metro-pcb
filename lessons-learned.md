# Lessons learned — building a transit-map LED PCB

Written for the next board of this kind (another city, another network), so
each lesson says what to do, not just what went wrong.

- **Part D** is the Tokyo board (October 2026: 248 LEDs, 320 × 280 mm). It
  is the first in the series big enough to break the pipeline's own
  assumptions, so most of what it learned is about scale.
- **Part A** is the Montréal Métro board (October 2026: 73 LEDs, 160 × 160
  mm, sent to JLCPCB on 2026-10-18). It ran from data to fab files in about
  ten days.
- **Part C** is the checklist to run before ordering, built from both.
- **Part B**, at the end, is the Vancouver SkyTrain v3 board this one was
  ported from. Every lesson there still holds; Part A adds to it.

---

# Part D — Tokyo

248 LEDs on 320 × 280 mm: Tokyo Metro's nine lines, Toei's four, the
Yamanote loop, the Arakawa tram, the Yurikamome, the Rinkai line and the
Shinkansen. Three and a half times Montréal's station count, and that is
where nearly every lesson here comes from — the pipeline worked, but most of
its constants and a few of its algorithms were sized for 70 stations.

## D1. At 3× the stations, the tools stop being fast enough to iterate with

The label optimiser cost **3.34 s per station**: one greedy pass over 251
stations was 14 minutes and the 40,000-iteration anneal on top was hours. A
first run died silently inside a timeout having produced nothing.

Profiling found 80 % of it in one place: `box_poly_overlap` walking every
point of every water polygon for every candidate placement of every label,
and Tokyo Bay alone is thousands of points. Two changes, neither of which
alters an answer:

- a **bounding-box prefilter** on every static obstacle — routes, silk
  furniture, annotations, water (3.34 s → 1.67 s);
- a **grid index over each water polygon's edges** (8 mm cells), so a label
  box tests only the edges in the cells it covers, plus one point-in-polygon
  for the box-inside-polygon case and a bbox test for a pond small enough to
  sit entirely under a label (1.67 s → **0.34 s**).

Verified against the original on 9,900 box/polygon pairs: identical answers.
**Profile before optimising and check equivalence after** — the win was 10×
and it was all in one function nobody would have guessed.

## D2. The annealer does not survive the scale change; greedy plus polish does

Montréal's simulated annealing starts at T = 60. At 251 stations that is hot
enough that it spends the whole run worse than where it started — it peaked
at 12,512 against a greedy score of 6,072 and never beat it, on the full
board or on a 71-station subset. Only the polish pass improved anything
(6,072 → 5,885).

Either scale the temperature with the station count or drop the anneal. A
tuning constant that was right for one city is not a constant.

## D3. The label floor is the optimiser's, not the map's

From 1,428 collisions to **25**, and then it stops: a second run with
everything else frozen improved the score and not the count, trading one
crowded label for another. 10 % needing a human matches lesson B4; what is
new is knowing it is a *floor* rather than slow progress, which is the
difference between running it again and opening KiCad.

All but two are white text crossing a white route. That is not a warning to
accept — it is unreadable — so they are hand work.

## D4. A better font is worth 40 mm of board, and the obvious choice is wrong

KiCad 10 plots TrueType, so the stroke font is a choice. Measured over all
279 station names at a 1.1 mm cap height, with stems measured by rendering
and scanning the glyphs:

| font | per character | thinnest stem |
|---|---|---|
| KiCad stroke font | 1.030 mm | 0.140 mm (set explicitly) |
| Arial | 0.786 mm | 0.136 mm |
| **Archivo Narrow SemiBold** | **0.709 mm** | **0.171 mm** |
| Archivo Narrow Regular | 0.682 mm | 0.131 mm |
| Gill Sans MT Condensed | 0.524 mm | 0.119 mm |

The narrowest faces are the ones that will not print: at 1.1 mm a regular
weight has stems of 0.12–0.14 mm, under JLCPCB's 0.15 mm silkscreen
minimum. A condensed **medium or semibold** is 30 % narrower than the stroke
font *and* thicker in the stem — easier to fit and easier to print at once.
It took the crowded-label count from 121 of 251 to 87, worth about 40 mm of
board.

Two traps: a variable font's default instance is usually Regular, so cut a
static instance of the weight you want (fontTools `instancer`) rather than
trusting KiCad to pick one. And pick a licence that lets the font live in
the repo — Franklin Gothic measured just as well and ships with Office, so
it cannot be committed and the build would not be reproducible.

## D5. Measure the footprint before changing any art that sits on a part

Two requests in one session came back as measurements rather than changes:

- **"Halve the station rings."** The XL-1615's pads reach 1.15 mm from the
  part centre; a halved ring is 0.70 mm at its outer edge, so it is under the
  pads — and silkscreen cannot print on a mask opening (lesson A6), so it is
  clipped out of the gerbers rather than merely hidden. It would not exist.
- **"Remove the holes cut out of the water."** The water is an F.Cu polygon
  with **no net**, so a pad inside it is shorted to it. The hole cannot go;
  it can only shrink to the electrical floor, 1.15 mm of pad plus 0.25 mm of
  clearance = 1.4 mm, at which point it hides under the LED body.

Both answers were better than the request, and both needed one number out of
the footprint file. **Read the footprint, do not recall it.**

## D6. The clearance disc was sized for a via that almost nothing needs

Cutting the water keepout from 2.2 mm to 1.4 mm everywhere except the
stations with water all the way round them — **two of 248** — took the water
from 26 separate pieces to 16, because those discs were chopping narrow
rivers into fragments at every station on them.

The 2.2 mm was right: it is pads + clearance + room for an escape via. It
was just being applied to all 248 when 246 of them can reach the back plane
from the land side.

## D7. The least-squares layout can fold a line back on itself

Minimising the sideways part of a leg is just as happy with the leg
*reversed*, and if the direction is re-snapped from the current positions
each round, a flipped leg stays flipped. That drew the Ginza line turning
−171° at Tameike-sanno where the city turns +33°, and +167° at
Akasaka-mitsuke where it turns −68°: a visible U-turn through two stations.

Fix: snap against the **geography**, not the iterate — a leg may be turned at
most 67.5° from its true bearing — and report *legs folded past a right
angle from the truth*, which must be zero. It costs some straightness - legs within 1° of a 45°
direction fall from 185 of 267 to 159 - and removes the defect. Worth it: a
U-turn is a thing anyone can see, and 26 legs a degree or two off is not.

## D8. Identity is the name, not the position

Ueno-hirokōji and Ueno-okachimachi are 25 m apart and are two stations with
two LEDs; clustering by position merged them and lost an LED. Japanese names
are canonical and shared across operators, so **the name is the identity** —
after normalising the small and large katakana ke (市ヶ谷 / 市ケ谷), a 駅
suffix, and the bracketed subtitles one operator uses and the other does not
(押上〈スカイツリー前〉).

Then cross-check the result against something the route data did not
produce: every station carries its official code (G-09, M-17) in OSM's `ref`,
and all thirteen subway lines matched their official numbering exactly. That
check replaced the official map PDF, which turned out to have no extractable
text anyway.

## D9. Scope grows cheaply when the pipeline is parameterised

Adding four non-subway lines took an afternoon because the station identity,
the layout, the labels and the renderer were all driven by data. The
Yamanote loop was the bargain: 18 of its 30 stations were already LEDs, so
the loop that makes Tokyo legible cost **12**.

The rule that kept it honest: **a line is only drawn if nearly all of it is
inside the map.** Six of thirteen stations reads as broken, not as a line.
That ruled out the Nippori-Toneri Liner, the Tokyo Monorail and the Setagaya
line.

## D10. Cropping is not the same as building smaller

The layout fits itself to whatever board it is given, so rebuilding at a
smaller size just draws the same map smaller — the proportions, and the
amount of bay along the bottom, do not change. To remove part of the map the
scale has to stay put and the board edge has to move in; that is a separate
operation (`tools/crop_board.py`) which clips the water, drops the stations
that fall off, takes them out of the paths, chain, shapes and labels, moves
the mounting holes and the wordmark, and stubs any line that lost its end.

Cropping 340 × 340 to 320 × 280 removed 22 % of the board area for three
LEDs **with the core spacing unchanged**. Rebuilding at 320 × 280 would have
shrunk the core by 7 % and cropped nothing.

## D11. Hand work has to survive every rebuild, and the rebuild has to be one command

Changing a clearance meant rebuilding the data file, which would have thrown
away 251 label placements and the chain. `build_tokyo.py` now takes
`--labels` and `--chain` and re-applies them, reporting what it restored and
what is orphaned; `input/rebuild.sh` runs the whole pipeline from the cached
OSM responses to the final `tokyo.json` in one command, so every
intermediate is disposable and none of them is kept in the repo.

One ordering trap: the chain is a permutation of the **cropped** station
set, so it is re-applied after the crop, not before — handing it to the
uncropped build gets it rejected for being 248 long against 251 stations.

## D12. Git Bash mangles UTF-8 on the way to curl

An Overpass query with Japanese tag values (`東京メトロ`, `都営地下鉄`)
inline in the shell arrives as `?????` and Overpass rejects the regular
expression with "static error: Invalid regular expression". Put each query
in its own `.ql` file and send it with `--data-urlencode "data@FILE"`. The
queries are worth keeping as files anyway.

## D13. What is waiting in the hardware stage

- **44 LEDs sit in a hole cut out of the water** (across 9 holes; none
  stands on live water copper — the earlier figure of 67 counted stations
  near the water, not inside it), so the front ground pour will be cut into
  islands and every one of them needs its own via to the back plane.
  Montréal shipped with *one* LED stranded, second in the chain, which would
  have left 71 of 73 dark. At 44 this cannot be eyeballed — Part C item 5
  has to be a scripted gate.
- **Sixteen GND pads reach the pour by a single thermal spoke** and want an
  explicit via at the pad: LED18, 19, 30, 35, 37, 47, 58, 82, 98, 99, 109,
  133, 136, 158, 239, 244. These are the `starved_thermal` reports, and they
  are not cosmetic — they are all on cut-up islands.
- **There is no way to get power into the board.** Every `+5V` node is an
  LED, a cap, U1's VBUS, or a 3 × 3 mm test pad. Fix it in the schematic
  before routing, not after.
- **38 of the 247 chain hops cross bare-copper water**, 174 mm in total.
  None of those can run on the front; they go down a via, across on the back,
  and up again.
- **248 LEDs is about 15 A at full white** *if* each draws the 5050
  WS2812B's 60 mA. The XL-1615 is a 1.6 × 1.5 mm part and is likely well
  under 20 mA, which would put the board nearer 4–5 A — but no datasheet is
  in the repo and the symbol's Datasheet field is empty, so the number is
  unverified either way. The firmware cap stays at 900 mA until the supply
  and the injection points are proven.

## D14. A check that only tests the middle of a chain passes a dead board

The deepest bug in the project was found by a review, not by a check:
`make_schematic.py` deleted the `LED_DATA` and `LED_IN` labels off R1's pins
and never inserted the replacements it had built, so `GPIO1` dead-ended at
its test point, both of R1's pads fell to `unconnected-(R1-Pad*)`, and
LED1's DI sat alone on a one-node net. **Not one LED would have lit.**

Everything passed. `check_led_chain.py` asserted `DO[n] == DI[n+1]` for all
247 hops and they were all fine — the chain was continuous, it just had
nothing driving it. The script even *printed* `data in: LED_IN [('LED1',
'2')]`, a one-node net, and said PASS. Schematic parity was clean, because
the board faithfully reproduced the broken netlist.

- **Check the ends, not just the links.** A chain test must walk from the
  driver to the far end: GPIO → series resistor → first DI, and last DO →
  out. The checker now does, and refuses any single-node net on the path.
- **Printing a value is not checking it.** If a script prints a number worth
  looking at, assert on it.
- **Deleting and re-adding in one pass needs the re-add verified.** The
  generator built its replacement blocks into a list, logged
  "2 label(s) moved off R1", and then appended only the *other* list. The
  log line was true and the output was wrong.
- **Dead code does not get its geometry checked.** The replacement blocks
  had been wrong since the day they were written — both labels ran their
  text back across the resistor — and nobody could see it, because nothing
  ever rendered them. Fixing the insertion exposed a second bug underneath.
- **For a vertical schematic label, the angle does not choose the side;
  the justify does.** KiCad always sets vertical text bottom-to-top, so 90
  and 270 put the glyphs on the same side of the anchor and only
  `(justify left|right)` moves them. `check_schematic.py` derived the box
  from the angle, so it modelled `LED_IN` as running down into empty space
  while it actually ran up into R1's body, and reported **0 overlapping
  pairs on a sheet that had one**. `LED_IN` was the only 90-degree label on
  the sheet: the one label the model got wrong was the only one exercising
  that branch. Verify a text-placement model against rendered ink
  (`kicad-cli sch export svg`, then measure), not against itself.
- **A rail checked by NAME is not checked at all.** `check_led_chain.py`
  asserted every LED's pin 3 sat on a net called `+5V`. Drop the `+5V`
  label off U1's VBUS pin the way `LED_DATA` was dropped off R1 and all 248
  LEDs are still on a net called `+5V`, fed by nothing, and the script
  prints PASS. It now requires each rail to reach the controller.

## D15. Zero-width seams are real geometry to the DRC, invisible to shapely

`gr_poly` carries one ring, so each hole is bridged into the outer ring by a
seam traversed out and back. Both copies of `ring_with_holes` joined the
outer ring to `hole[0]` — whichever vertex shapely happened to start the
ring at — making the seam an arbitrary chord. For Tsukishima it ran 3.9 mm
from the far shore straight through the middle of the LED's own keepout
hole, across LED20's pads.

Every geometric check in the pipeline said the water was 2.995 mm away,
because `buffer(0)` collapses a doubled edge before anything measures it.
KiCad's DRC reads the seam as boundary and called it two shorts and a
clearance violation. Both fill rules (even-odd and non-zero) agree the point
is *outside* the polygon — the fill was never the problem, the edge was.

- **Bridge at the nearest pair**, searching both rings. The seam then
  arrives at the hole's rim instead of crossing its interior. One line of
  fix; it cleared all three violations.
- **A check that runs on `buffer(0)` output cannot see self-touching
  geometry.** If you emit invalid-as-written rings on purpose, test the
  *segments*, not the resolved polygon.
- **When your geometry and the DRC disagree, the DRC is describing the
  board.** Two hours went into hypotheses about KiCad's fill rule; the
  answer was an edge list anyone could have printed.

## D17. Every LED the same way up beats every LED the shortest way round

The LEDs were each turned so DOUT faced the next station in the chain -
eight different angles across the board, which is the right answer if the
router is what you are optimising. It is the wrong answer for the person
who has to fit 248 parts: pads 1 and 4 share the part's long edge, so the
only thing between a correct board and 248 parts fitted backwards is a
0.26 mm dot read correctly at eight different rotations. All 248 now sit at
270 degrees, pin 1 up. The routing gets harder; the assembly gets checkable
in one glance, and in one photograph.

## D18. Growing a generated schematic breaks it in the gaps you didn't grow

Going from 13 decoupling caps to 52 took three tries, and each failure was
silent:

1. The new caps went in the gaps between LED columns. The bodies fit; the
   Value text is 11.3 mm wide and ran into the next LED - 74 overlapping
   pairs. Where a cap sits on the SHEET is cosmetic (they all bridge the
   same two rails, and `place_parts.py` decides the board position), so
   they moved to the clear band right of each row.
2. The power rail still stopped at the last LED, so all 39 new caps sat
   with both pads on `unconnected-(ROWn-Pad*)`. **`check_led_chain.py`
   printed PASS** - it had never looked at a capacitor.
3. Extending the rail past the last LED turned that LED's stub from an
   end-to-end meeting into a T-junction, and in KiCad a wire ending in the
   middle of another wire is not connected without an explicit junction.
   One LED per row went dark, 13 of them, along with all 52 caps.

- **When a generated rail grows, re-check what was at its END.** The thing
  that used to be the endpoint is now a tee.
- **Add the assertion with the feature.** Caps were invisible to every
  check in the repo, so the netlist was the only thing that noticed.
  `check_led_chain.py` now requires every `ROWn` to bridge +5V and GND, and
  that check fails on the broken version.

## D19. A weight of zero is not a preference

`W_LINE` - the cost of a label lying on a route - was set to 0 because at
100 it drove most of the rotations and leaders. Zero does not mean "mildly
discouraged", it means the optimiser cannot see it, and 140 of 248 capsules
ended up taking a bite out of a line. It is now 6: far below W_ROT (150)
and W_GEO (60), so a label will still sit on a track rather than rotate or
move onto the water, but between two otherwise equal spots it takes the
clear one.

## D20. Repair what is wrong; do not re-solve what is right

Enlarging the station ring from 0.63 to 1.65 left 240 of 248 capsules
overlapping a ring. Re-running the optimiser would have fixed it and thrown
away every hand placement. `push_labels.py` instead pushes only the
offending labels straight out along their own direction, keeping the angle,
the anchor and the side that were chosen by hand - and writes the result
back to `label_overrides.json` so it survives a rebuild. 195 cleared every
ring; the 45 downtown ones, where the rings are 3.3 mm across and 2.8 mm
apart and no distance along their own direction misses all of them, clear
their OWN ring, which is the overlap you actually see.

## D16a. A mark nobody can read is not a mark

Pads 1 and 4 of the XL-1615 are on the SAME side of the part, so the
vendor's silk dot — on that side but centred between them — says which side
and not which corner. A part fitted 180 degrees out looked identical on
silkscreen, and that error swaps GND with DI and +5V with DO. The F.Fab
layer was always unambiguous (arrow, dot and a "1" in pad 1's own corner);
silkscreen was not. Moving the dot onto pad 1's row costs no extra ink.

Then the harder half. The dot is white silk in a map made of white silk:
with the station ring at 1.65 mm its band ran straight through the dot on
every LED, and **not one of the 248 dots had half its ink standing clear**.
Cutting the dot out of the routes and notching it out of the ring took that
to 184 fully clear and 190 at 90 % or better. The ring still reads as a
circle; the notch is at pin 1, which is a second polarity cue for free.

- **Measure legibility, not just position.** Every dot was geometrically
  perfect and a third of them were invisible. The check that matters is
  "how much of this ink is not on top of other ink".
- **Thirteen dots are still buried under a station name's glyphs**
  (LED125, 151, 83, 211, 136, 237, 50, 20, 141, 100, 119, 156, 194). The
  label optimiser does not know the dots exist. Nudge those labels, or
  teach `check_fit` the dot keepout.

## D16b. The constant and the comment above it disagreed for two days

`RING_R` was halved to 0.63 on request. Directly above it the comment said
*"1.33 mm is the smallest radius that clears the pads… silkscreen cannot
print on a solder-mask opening anyway, so it would be clipped away."*
Nobody read it, and **60.7 % of every ring's ink was sitting on a pad
opening** — all 248 would have printed as four arcs with four gaps.

And the comment was itself out of date: it quoted the 1.15 mm pad reach,
but the binding constraint is the **corner** of the pad's mask opening at
1.4407 mm. Sizing to the comment's 1.33 still clipped 15 %. The ring's
inner edge has to clear the corner, which is 1.65 with a 0.25 stroke.

- **When you change a constant, read the comment attached to it.** If the
  comment is now wrong, it was load-bearing and you just broke something.
- **Derive the clearance from the real geometry**, not from a number in
  prose: pad reach, plus mask expansion, on the diagonal.

## D16c. Solder-mask expansion is a board setting and it was 4x too big

`pad_to_mask_clearance` was **0.2 mm** and no LED footprint overrode it, so
each 0.8 x 0.65 mm pad got a 1.2 x 1.05 mm opening and the 0.25 mm gaps
between pads disappeared entirely. That was 199 `solder_mask_bridge`
warnings — a check the project had set to `ignore`, so nobody saw them. At
the standard 0.05 mm the dams come out at 0.150 mm, which JLCPCB makes in
any colour at 1 oz (their minimum is 0.10 mm; **0.20 mm at 2 oz, so order
1 oz**). The 0.2 mm expansion was also printing the footprint's own silk
body lines on top of the mask openings on all 248 parts.

- **A DRC check set to "ignore" is a check you have deleted.** Turn it on,
  look at what falls out, and fix the cause rather than the severity.

## D16d. Mask cutting kept a side file, and the side file lied

`mask_under_silk.py` replaces each water mask opening with pieces cut round
the silkscreen, and records the originals so it can re-run. But `export_art`
rewrites the water every run, so after it ran the recorded uuids were
"missing from the board" and the tool **restored the previous run's
openings alongside the new ones, every run, for ever**: 7 of 11 recorded
openings were ghosts of water shapes that no longer existed, left as bare
copper beside LED100's pads. The art manifest is the discriminator — a uuid
export_art no longer claims must not come back.

Worse, two `geo` shapes were both called `water-0` (both `crop_board`
splits keep the parent's name), and the block uuid is `uuid5` of the name:
**two board items with the same uuid**. `mask_under_silk` keys its drawings
by uuid in a dict, so one of the pair was silently dropped and its opening
was never cut — leaving 374 mm² of front silk over a bare copper opening,
which the fab clips away. Both fixed; silk-on-opening is now 0.000 mm².

- **A deterministic uuid needs a unique key.** If a shape can split, the
  piece index belongs in the name.
- **Deleting a tool's state file is not a clean slate** if its previous
  output is still on the board. Without the record, those pieces became
  "originals" and got cut again — 9 openings became 158. The tool now
  discards anything the manifest does not claim.

## D16. Duplicated zones manufacture their own DRC noise

Three GND zones sat stacked with byte-identical outlines and priorities 2, 0
and 1. Their fills split arbitrarily (151 787 / 4 100 / 7 mm²), and the
4 107 mm² of slivers belonging to the two redundant copies accounted for
**all 32 `isolated_copper` reports**. Deleting them and refilling took the
count to zero and changed nothing electrical — same net, same outline.

Also: `solder_mask_bridge` was set to `ignore` in the project file, which is
the one check that would have caught a mask aperture spanning two nets. It
is now `warning`. 199 of its 200 hits are pad-to-pad *inside* a single LED
footprint, whose own inter-pad gap is 0.250 mm — a fab mask-dam question
about the footprint, not an artwork bug, but worth seeing rather than
suppressing.

---

# Part A — Montréal

## A1. Settle scope and style early; keep every style as a variant

The map went through four styles before the user settled:

| Round | Style | Verdict |
|---|---|---|
| 1 | Natural map, 2:1, 200 mm (the Vancouver recipe) | Kept as `montreal.json`, but too sparse downtown |
| 2 | STM-style schematic: straight lines, 45° bends | Liked the lines, wanted real land |
| 3 | Schematic lines on natural land, rounded bends | Right idea, wrong frame |
| 4 | **Square 1:1, 160 × 160 mm, schematic lines, true-scale land** | Built and ordered |

What made this cheap:

- **Every style is a variant in one builder** (`build_schematic.py`'s
  `VARIANTS` table, plus the separate natural builder), not a rewrite. The
  user could compare them side by side and change their mind without losing
  work.
- **When asked for options, give two or three with a recommendation.**
  "What do you think looks best?" moved faster than open-ended iterations.
- **Ask the scope questions first**: metro only or commuter rail too? Under
  construction lines included? Here the Blue line extension went in because
  the board outlives the construction timeline. That decision fixed the LED
  count (73) before any layout work.

## A2. Schematic lines on real land: move the land rigidly, never warp it

A schematic moves stations off their true positions; the land has to follow
somehow. Stretching or bending the land to meet the stations gave "looks too
stretched, doesn't look realistic", every time. What held:

- **Fit the land to the stations with a similarity transform only**
  (scale, rotation, translation; Procrustes). Weight the shore stations
  heavily (`SHORE_STATIONS`, weight 6) and ignore stations the schematic
  deliberately displaces (`FIT_IGNORE`: Jean-Drapeau, Longueuil).
- **Exaggerate the station-to-shore distance, not the coastline.** The user
  allowed stations to sit further from the water than they really are. They
  did not allow the shore itself to move.
- **Project at true scale** (turn off any warp left over from the natural
  map). Real proportions are what made it read as Montréal.
- **Detail comes from the water, not the land**: the port's piers, the
  Lachine Canal, rivers east of downtown. Use area thresholds for small
  water bodies, keep named water at a lower threshold, and drop islands
  below a minimum area *and* width so slivers don't etch.

## A3. OSM water and Overpass specifics

- **`out body geom`, not `out tags geom`.** The latter drops relation
  members, so multipolygon water (the St. Lawrence, the river islands)
  silently vanished.
- Overpass returns busy/500 under load: retry and fall back to a mirror,
  and cache the raw responses in the repo (`input/osm/`).
- Future stations (the Blue line extension) are not in OSM as nodes. Their
  positions came from the planned alignment intersected with cross streets.
  Record where each hand-made position came from.

## A4. Labels: learn the human's method, then make it the default

The optimiser's first output was technically clear of overlaps and still
wrong to the user. Their markups taught the rules, in this order:

1. **Cartographic rule of thumb:** upper right of the station, then lower
   right, upper left, lower left, middle right, middle left.
2. **The user's hand method**, inferred from their KiCad edits: put the
   label beside the station and level with it, close in; keep the same side
   along a run of stations; alternate sides on a level run; wrap the name
   rather than let it cross water.
3. **Horizontal text wherever possible**, and as few leader lines as
   possible. A leader is a last resort, not a placement option.
4. **Official names with their hyphens**, line-broken at the hyphen
   (Mary-Two-/Axe-Earley), never abbreviated.

Then encode it: the optimiser's cost function (`position_cost()` in
`auto_label.py`) now scores exactly those preferences. **Treat the hand
pass in KiCad as the truth**: `import_labels.py` →
`save_label_overrides.py` freezes every hand placement in
`label_overrides-square.json`, which every build re-applies. The water is
cut away under labels (`LABEL_CLEAR_MM`), so a label never has to dodge
it.

**Always import and freeze before any rebuild.** The user kept editing
labels between sessions (13 more edits turned up during the PCB review).
An unimported edit is one rebuild away from being lost.

## A5. Exposed-copper water fights the ground pour; plan for islands

The water is bare copper on the front with no net. It cuts the front ground
pour into islands, and a hand-routed board will have islands that carry LED
ground pads but never reach the back pour. The first review of the
hand-routed board found the map would have stayed almost entirely dark:

- **LED2 (Jean-Drapeau)** sat on a 22 mm² ground island with an
  unconnected +5V stub. It was second in the chain, so LEDs 3–73 would
  have received no data.
- **An 835 mm² front island** under LEDs 58–64 had no via to the back pour.
- **The XIAO's ground pad** sat between two pads closer together than the
  pour clearance, so the pour never reached it.
- Two decoupling capacitors were never joined to +5V, and three LEDs had
  starved thermal reliefs.

What to do:

- **Treat the back pour as the ground plane and the front pour as
  decoration.** Every front ground pad gets a via to the back. Give the
  controller's ground pad an explicit track.
- **Count the islands, don't eyeball them.** Refill the zones, then list
  each front pour piece with its vias and pads (a KiCad Python loop over
  `GetFilledPolysList`). "0 unconnected after refill" is the bar; one via
  for a 3000 mm² island is legal but weak, so add more.
- **One ground zone, not three.** Copying zones during editing left
  duplicates whose leftover slivers show up as isolated-copper warnings.
- **The autorouter is a useful proof, not the answer.** Freerouting got the
  board DRC-clean (commit `b02ee1b`): art keepouts with `Fracture()` so
  island holes stay open, ground plane declared on the back only. The user
  still routed by hand for looks. Keep the autorouted version in history
  as evidence the board is routable.

## A6. The fab clips silkscreen over exposed copper — close the mask under the ink

The board was already uploaded when the user spotted it in JLCPCB's gerber
viewer. The yellow line's route over the water, the Jean-Drapeau ring and
its leader were missing.

- **Silkscreen cannot print on a solder-mask opening.** JLCPCB clips it,
  and so does `kicad-cli` with `--subtract-soldermask`. The water *is* a
  mask opening.
- **KiCad's 3D render does not show this.** It draws silk over the
  opening as if it will print, so every render looked right.
- **Fix:** close the mask opening under the ink with a margin (0.2 mm;
  JLCPCB wants ≥ 0.15 mm), keeping the copper. `tools/mask_under_silk.py`
  does it, and `rebuild_board.sh` runs it after every `export_art.py`.
- **Verify with a clipped plot, not a render**:
  `kicad-cli pcb export pdf -l F.Mask,F.SilkS --subtract-soldermask` or the
  fab's own gerber viewer. Measure silk ∩ mask opening in KiCad Python;
  it must be 0 mm².

## A7. Saved zone fills are what gets plotted

Gerber export plots the fill as last saved. A +5V via added after the last
fill sat inside the saved ground pour: the plotted copper would have
shorted +5V to ground even though the editor showed nothing wrong.

**Refill (press B) and save before exporting**, and export with
`--check-zones`. Run DRC both with and without `--refill-zones`; a
difference between the two runs means the saved fill is stale.

## A8. Parts: query JLCPCB's library, don't guess, and keep fields honest

- **Look parts up instead of recalling them.** JLCPCB's parts API
  (`selectSmtComponentList`, with `componentLibraryType: "base"`) answers
  "is there a basic part for X" in one call. There is no basic aluminium
  electrolytic at 100–470 µF. The basic choices were a 100 µF 6.3 V 1206
  ceramic (C15008) and a 100 µF 6.3 V tantalum (C16133). The ceramic won:
  a 6.3 V tantalum on a 5 V USB rail is under-derated and fails short.
  Ceramic DC-bias derating leaves roughly 20–30 µF at 5 V; say so.
- **The Value field and the LCSC number must agree.** The ROW capacitors
  say "10uF,10V,X5R" but C52923 is a 1 µF part, and the Value text
  becomes the BOM comment JLCPCB shows. Check every BOM line against its
  part number.
- **Put every assembled part on one side.** The user moved everything JLCPCB
  places to the top: one-sided assembly is cheaper. The XIAO is soldered by
  hand; the buttons are do-not-populate with bare pads for hand fitting.
- **Mark test points, art and holes as excluded from the BOM and position
  files**, or they clutter the assembly order.
- **Add the cheap insurance parts**: a 330 Ω series resistor on the LED
  data line (C25104, basic) and a bulk capacitor at the power entry. Both
  cost cents; a missing footprint costs a board spin.

## A9. KiCad 10 scripting gotchas

- **Check for lock files before editing** (`~*.kicad_pcb.lck`). When the
  user has the board open, a script's changes are overwritten the next
  time they save. Tell them to close without saving and reopen.
- **After `board.Remove()`, the Python wrappers go bad**: objects come
  back as bare `SwigPyObject`s with no methods. Read and add everything
  first, remove last.
- Use `COutline()` (const) rather than `Outline()`, and
  `TransformShapeToPolygon` rather than `GetPolyShape()`, when you only
  need to read a polygon.
- `Duplicate(False)` (not `Duplicate()`) when cloning a footprint;
  `LSET()` + `AddLayer()` to build layer sets.
- KiCad's bundled Python has no shapely. Do the geometry with
  `SHAPE_POLY_SET` (`BooleanXor`, `BooleanSubtract`, `Fracture`) or in a
  separate system-Python step.
- **Polygons with holes need `Fracture()`** before they become a
  `gr_poly`, a zone outline or a keepout. Otherwise islands fill in (the
  autorouter fenced off Jean-Drapeau until this was fixed).

## A10. Artwork from an SVG: one board-only footprint

The back-side owl came as a one-bit SVG (a single even-odd path).
`tools/svg_to_silk.py` turns it into one footprint (`LOGO1`):

- **board-only, excluded from the BOM and position files**, so it doesn't
  upset schematic parity or the assembly order;
- **built for the front, then flipped**, so it reads correctly from the
  back;
- **movable as one piece** in KiCad, and regenerated in place by re-running
  the tool.

Size the art to the space the parts leave free (here, the top 2/3 of the
back), and check it against every back-side part.

## A11. Process

- **Screenshots with markups were the fastest review loop.** The user's
  annotated images ("move this up", "remove these islands", "parallel
  leaders here") turned into concrete changes with no ambiguity. Ask for
  them.
- **Review the hand-routed board from the files, not the picture.** The
  screenshot looked finished; DRC with `--refill-zones`, schematic parity
  and a pour-island analysis found every critical fault.
- **Timestamp fab outputs and delete superseded sets.** Generate
  `montreal-skytrain-pcb-<YYYY-MM-DD-HHMM>-*` files, and delete a set as
  soon as it is known to be wrong (the `-1117` set had the clipped silk),
  so nobody uploads it.
- **Keep the exact package that was sent** (`manufactured/`) and check it
  byte for byte against the repo's outputs.
- **Commit as the agent identity**, every time: `git -c
  user.name="SWS-Chipkin" -c user.email="sws-dev@chipkin.com" commit`.
- **Shipping:** JLCPCB's cheapest tracked line ("Global Standard Direct
  Line") greys out above its weight and size limits; a 160 mm assembled
  order can exceed them. Budget for the next tier.

## A12. Known issues in the board as ordered

Check these when the boards arrive, and fix them in the next revision:

- **LED rotation** in JLCPCB's placement. Their part orientation for
  C5349954 may differ from the footprint's by a constant.
- **ROW0–7 Value text** reads 10 µF; the parts are 1 µF (C52923).
- **USB-C sits 26 mm in from the bottom edge**, so the cable plugs into
  the middle of the back. Move the XIAO to an edge if the board will hang
  on a wall.
- **The northern front ground pour** joins the back through a single via.
- **Copper scraps:** a redundant `gnd` zone leaves three tiny scraps
  (warnings only).
- **The LED data line is 3.3 V into 5 V LEDs**, with a series resistor
  but no level shifter. If the first LED misbehaves, a 74AHCT1G125 is the
  fix.
- **Power:** the firmware caps brightness at 900 mA. Full white on 73 LEDs
  is about 4.4 A, beyond USB.

---

# Part C — Before you order

Run all of it, every time:

1. Import and freeze any hand label edits (`import_labels.py`,
   `save_label_overrides.py`).
2. If the artwork was regenerated, run `mask_under_silk.py`.
3. Refill all zones and save.
4. DRC with `--refill-zones --schematic-parity`: 0 errors, 0 unconnected,
   0 parity issues. Read every remaining warning and say why it's
   acceptable.
5. Pour-island analysis: every front ground piece with pads has at least
   one via; the controller's ground pad is tracked. **Script it and compare
   against the expected count** - Tokyo has 67 LEDs sitting in holes cut out
   of the water, so the islands cannot be counted by eye, and one stranded
   LED early in the chain darkens everything after it.
5a. Every chain hop that crosses bare-copper water is routed on the back.
   Tokyo has 38 of them, 174 mm of water in total; the front water is a mask
   opening with no net, so a front-side track across it is a short.
6. Clipped silk check: a `--subtract-soldermask` plot, and silk ∩ mask
   opening = 0 mm².
7. BOM check: every Value matches its LCSC part; every assembled part is on
   one side; non-parts are excluded.
8. Export with `--check-zones`; timestamp the files; delete superseded
   sets.
9. Open the zip in the fab's gerber viewer and look at the silkscreen
   over the water, the board edge and the drill holes.
10. After upload, save the exact package in `manufactured/` and record the
    date in the README.

---

# Part B — Vancouver SkyTrain v3

Collected while building v3 of the Vancouver SkyTrain board, the project
this one was ported from.


## B1. Get the landmass right first, on its own, before anything touches the PCB

The single biggest time sink of this project was geography. Five
successive sources were tried before the shape was right:

| Attempt | Source | Why it failed |
|---|---|---|
| 1 | Hand-authored polygons "resembling" Vancouver | Invented coastline; every review found something wrong |
| 2 | TransLink's schematic network map (PDF, vector-traced) | A schematic is not a map: its page is 1.26:1 where the region is 2:1, so everything south of Broadway was stretched and the Fraser became a 45° band; it also draws no coastline where it doesn't need one, so "the left edge should end in water" had no data behind it |
| 3 | The v1 project's hand-drawn "natural" map | Better shape, but a hand drawing: squeezed north–south, station layout not geographic, and it had to be registered to the board by fitting dots in a PNG |
| 4 | OpenStreetMap coastline via Overpass | Correct where it exists — but in this region OSM's `natural=coastline` stops at Burrard Inlet; the Fraser's arms are `natural=water` riverbank polygons that were never loaded, so Sea Island, Lulu Island and the whole estuary collapsed into land |
| 5 | **BC Freshwater Atlas (provincial 1:20k hydrography, WFS)** | Worked first time |

What made #5 work is worth generalising:

- **Prefer sources that give polygons, not lines.** Assembling coastline
  *lines* into land/sea faces (polygonize + orientation votes) is where
  the OSM attempt went wrong. The FWA gives land (watershed groups end at
  the coast → sea = frame − land), rivers and lakes all as polygons; there
  was nothing to assemble.
- **Prefer the national / provincial mapping agency over crowd-sourced
  data for water.** Look for a WFS with a bbox parameter (BC:
  `openmaps.gov.bc.ca/geo/pub/wfs`; most provinces/states/countries have
  an equivalent). Cache the raw responses in the repo so the build runs
  offline and is reproducible.
- **Make a standalone geography render** (`geo_fwa.py`) and get it
  approved before wiring it into the board pipeline. Iterating on the
  shape through KiCad renders costs minutes per round; matplotlib costs
  seconds.
- **Simplify deliberately, not by accident.** A morphological open/close
  (`buffer(-d).buffer(2d).buffer(-d)`) plus `simplify()` removes nooks;
  filling river islands below a size threshold and dropping bay tips that
  are mostly outside the frame keeps the picture clean. Keep lakes by a
  *name whitelist* — an area threshold lets 10 ha ponds in.
- **Check the obvious landmarks by eye**: the airport island, the river
  reaching the sea, the big lakes. Every one of those was missing at some
  point and no checker caught it; a human did.

## B2. Use real station positions, then bend them only where physics demands

Station positions came, in order, from a schematic, a hand drawing and
finally OSM nodes (`railway=station` + `station=subway`). Real positions
put stations on the correct side of rivers automatically — "Surrey
Central is in the water" is a symptom of a bad source, not something to
patch.

The only justified distortion is the LED pitch: downtown stations are
~500 m apart, which is 1.6 mm at 3.1 mm/km. Spread them along their own
line direction, then run a global pairwise separation, and record the
floor as a constant with the reason next to it. **The floor is 3.3 mm,
not the 2.5 mm the package suggests**: LED footprints rotate to aim DOUT
at the next LED, and two diagonal neighbours' pads overlap at 2.8 mm.
Found by DRC after the layout looked fine.

## B3. Size the board to the map's aspect, not the other way round

A square board for a 2:1 region wastes half the area and pushes the map
scale down until labels stop fitting. Decide the frame (lat/lon box)
first, derive the board size from it at the largest width the fab and
budget allow, and treat "leave a blank band" as a warning sign. Going
from 150 mm square to 200 × 109 mm raised the scale 40 % and solved more
label problems than any algorithm did.

## B4. Labels: the tight cluster decides everything — plan for it

Downtown (six stations inside 1 km, three lines crossing) is where every
labelling scheme broke. What eventually held:

- One shared text height (1.1 mm, 0.14 mm stroke — a 1:8 ratio keeps the
  stroke font's counters open), a fixed standoff from the LED, two-line
  wrapping at the name's en-dash instead of abbreviations, a "beside the
  line" candidate so labels can run along a corridor, and leader lines
  as a last resort.
- A checker that models everything on the board — other labels with a
  breathing gap, pads (own and others'), routes including the label's
  own segment beyond the standoff, leaders vs everything, silk furniture,
  copper text — because every unmodelled thing became a real overlap.
- **Greedy placement does not converge in a cluster**; a repair loop
  cycled forever. Simulated annealing over all labels found joint layouts
  the greedy pass couldn't, and even that left a handful for a human.
  Budget for a hand pass and make it round-trip safe (next lesson).
- Some things are not label problems: "Vancouver City Centre" and
  "Granville" are 300 m apart; no layout algorithm fixes that, a bigger
  board does.

## B5. Make hand edits survive regeneration — deterministic ids + an importer

The generated board is edited by hand in KiCad; the generator regenerates
it. Without a round trip, one of them always loses. What worked:

- Every generated item gets a **deterministic uuid** (`uuid5(namespace,
  key)`, keys like `label:waterfront`), and the exporter keeps a manifest
  of uuid → key so it can remove exactly what it wrote last time
  (idempotent regeneration, verified by running it twice and checking for
  duplicate uuids).
- An **importer** finds each item on the board by uuid and writes the
  human's changes back into the data (position, rotation, justification,
  text, deleted leaders). Things the human *deleted* are recorded as a
  `suppressed_art` list the exporter honours.
- Prove it with an import → export comparison on the real board: 0 of 99
  text items differing is the bar.

And the mistake that made this urgent: the user had started editing in
KiCad while the generator was still being run. `git add` swept their
edits into a commit, a regeneration overwrote them on disk, and a
"refresh the backup" step overwrote the backup too. Git had the edits.
**Take the backup before the first regeneration, never overwrite a backup,
and tag the commit.**

## B6. Model the fab's reality, not the editor's

- KiCad's stroke `type dash` line style is an **editor display hint**; it
  does not survive to gerbers, SVG export or 3D render. Draw dashes as
  real short segments.
- Text angles outside [−90°, 90°] render upside-down; rotation is rigid.
- KiCad's bold stroke font is ~10 % wider than a 0.85 × size-per-character
  estimate; the wordmark walked into a river because of it. Measure once
  from a render and put the factor in the code.
- Bare-copper "water" needs an F.Cu polygon **and** the same polygon on
  F.Mask; keep it 0.4 mm from the edge (and inside the corner radius) and
  ≥ 2 mm from every pad — carve clearance disks in the data, and repel
  edges again at export time. A real coastline puts stations *inside*
  water (ferry terminals, river banks); nudge those onto land.
- `silk_over_copper`, `silk_overlap` and `solder_mask_bridge` DRC warnings
  are the price of this aesthetic; `clearance`, `copper_edge_clearance`
  and `shorting_items` are not negotiable. Say which is which in the
  README so the next person doesn't panic (or ignore the wrong one).
- A newer KiCad silently upgrades the file format on save; an older
  `kicad-cli` then fails with "Failed to load board". Pin the CLI to the
  newest install.

## B7. Process lessons

- **Verify against the source, not against the previous fix.** Two rounds
  were spent adding a "missing" peninsula that the source map never
  showed. Re-read the source before patching a mismatch.
- **Sub-agent design critiques were worth it**: an independent
  composition / cartography / labelling review produced the list that
  drove the whole redesign (water to the edge, thin uniform routes,
  station rings, wordmark on land, drop the legend).
- **Keep every generated intermediate in the repo** (cached WFS/Overpass
  responses, station tables, preview PNGs). Builds stay reproducible and
  reviewers can see what changed.
- **Write the "what's wrong with this picture" checklist down**: river
  reaches the sea, airport island present, big lakes present, all
  stations on land, no label on bare copper, wordmark on land, nothing
  in the corner radius. Run it by eye on every render.
- **Automate the screenshot.** `kicad-cli pcb render` (and the matplotlib
  preview) after every change meant problems were seen the same minute
  they were made.

## B8. Reusing this for another city

The pipeline is city-agnostic below `vancouver.json`. For a new city you
need: (a) a lat/lon frame and board width in `geo_fwa.py`'s successor,
(b) polygon hydrography for the region (agency WFS first, OSM
`natural=water` second), (c) station lat/lon (OSM nodes, checked by eye),
(d) the line definitions and LED chain order, (e) a pitch floor for the
LED package and footprint rotation you use. Then: geography preview →
approve → data build → `auto_label` → `preview_map` → hand pass in KiCad
→ `import_labels` → verification list → render.
