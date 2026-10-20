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

- **67 LEDs sit in a hole cut out of the water**, so the front ground pour
  will be cut into islands and every one of them needs its own via to the
  back plane. Montréal shipped with *one* LED stranded, second in the chain,
  which would have left 71 of 73 dark. At 67 this cannot be eyeballed —
  Part C item 5 has to be a scripted gate.
- **38 of the 247 chain hops cross bare-copper water**, 174 mm in total.
  None of those can run on the front; they go down a via, across on the back,
  and up again.
- **248 LEDs is about 15 A at full white.** The firmware cap stays at 900 mA
  until the supply and the injection points are proven.

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
