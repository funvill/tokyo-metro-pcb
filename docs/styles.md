# Map styles considered

Rendered 2026-10-18, all from the same 219-station data, all at 400 × 292 mm
and 11.7 mm/km, so they differ only in style. Every render carries its title
and facts in the image (`tools/style_sheet.py`), and the sheet that tiles
them is `tools/contact_sheet.py`.

Lesson A1: keep every style as a variant rather than replacing it, so they
can be compared and nobody's mind-change costs work. Each style below is a
script of its own under `input/`, and none of them modifies the shared data.

## The thing that decides it

**On the board, every route is the same colour.** The routes are white
silkscreen; the water is bare ENIG copper; the only colour on the finished
board comes from the LEDs when they are lit. So a style has to be judged in
its `palette="board"` render, not its pretty one, and the question is the
only one that matters at arm's length: *can you follow one line with your
finger?*

That reframes two things. Colour-coding is not a tiebreaker, because there is
no colour. And overlapping lines are much less of a problem physically than
they look on screen, because two overlapping white strokes are
indistinguishable from one either way.

## The styles

| | Style | Render | Verdict |
|---|---|---|---|
| **A** | Schematic octolinear runs on true-scale land | `style-a-schematic.png` | **Recommended.** The Montréal winner, and it survives the board test |
| **B** | True geographic routes | `style-b-natural.png` | Honest but illegible in the core; the Vancouver recipe at 3× the stations |
| **C** | Official Tokyo Metro map look, no land | `style-c-official.png` | The prettiest map and the least honest LED placement |
| **D** | A, with shared corridors offset side by side | `style-d-offset.png` | Worth it for one corridor, a drawing error in six others |
| **E** | Smooth curves on true-scale land | `style-e-curves.png` | The best-looking render here and the worst board |
| **F** | A, rendered as the board etches | `style-f-board.png` | Not a style — the test every style has to pass |
| **G** | Thin uniform routes, station rings | `style-g-thin.png` | The Vancouver v3 aesthetic; water does the talking |
| **H** | A, with all 219 English names at 1.1 mm | `style-h-names.png` | The label problem, stated |
| **I** | A, labelled with station codes | `style-i-codes.png` | Half the ink, needs a legend the board cannot carry |

## A — schematic octolinear runs on true-scale land

Straight 0/45/90° runs with rounded bends, solved rather than hand-authored
(`input/build_tokyo.py`); the land is placed rigidly by a similarity fit, so
Tokyo Bay and the Imperial Palace moats keep their true proportions.

- 200 of 267 legs within 1° of a 45° direction; mean 1.1°, worst 15°.
- Stations moved from true: mean 4.5 mm (375 m), worst 14.7 mm (1230 m).
- Land at 11.7 mm/km, rotated 0.25° — essentially true scale, unrotated.

Why it wins the board test: a 45° bend is an event the eye can latch onto, so
a white-on-green track stays followable where a curve does not.

## B — true geographic routes

`input/tokyo-natural.json`, the same stations where they really are. Keeps
every station on the correct side of every river without being asked, which
is what the geographic source is for. But Tokyo's core puts six lines inside
a kilometre, and without the straightening the central cluster is a scribble.
Kept as the variant the data is checked against, not as a candidate.

## C — the official map look

`input/style_c_official.py`. Its own least-squares layout: every leg wants to
lie exactly on a 45-degree direction *and* to be one nominal pitch long,
which is over-constrained, so the pitch floor is settled first and the
direction term is annealed upward over 22 steps with the separation term held
proportionally hard. No land, no water, fat 1.5 mm strokes.

- Even spacing: mean leg 12.5 mm, median 14.1, sd 4.7 (the source data's
  sd is 5.5).
- 236 of 267 legs within 1 deg of a 45-degree direction, mean error 0.6 deg.
  Every one of the 19 legs over 2 deg is inside the
  Ginza / Shimbashi / Kasumigaseki / Otemachi knot, where the pitch floor
  overrules the angle.
- Closest pair 3.50 mm, so nothing is under the 3.3 mm floor.
- Corridors are found **geometrically** rather than from shared station
  pairs: only 17 of 267 legs are shared pair-wise, so sharing-by-stops would
  have missed almost everything. Legs that lie on the same infinite straight
  and overlap are a corridor. That found 26 corridors over 60 legs, drawn
  2.1 mm apart.

The objection is the hardware, not the drawing. The official look works
because the coloured strand and the station marker are separate objects; on
this board **the LED is the station**. A strand offset by up to 3 mm from its
own LED means the light does not sit on the line it belongs to, and at the
Otemachi and Ginza interchanges you get a lit dot in the middle of a bundle
with no strand under it. It would need the bundle pinched back to the LED at
every interchange, or a bigger board.

## D — shared corridors offset

`input/style_d_offset.py`. 17 legs are carried by two lines each (none by
three), chaining into 9 corridors; all are offset by 1.6 mm, tapering back to
the station over 3 mm at each end so both tracks reach the one LED.

- The eight-leg Yūrakuchō/Fukutoshin run in the north-west is a clear win: it
  is the most visible lie in the single-centreline version.
- The six single-leg corridors are not: 3 mm of taper at each end of a 14 mm
  leg leaves a lens shape that reads as a drawing error, worst at
  Hibiya–Kasumigaseki, in the busiest part of the map.
- 1.6 mm beats 2.2 mm because the LED body is about 2.5 mm wide, so the part
  itself still visibly bridges the two tracks.

Note: Asakusa/Ginza and Marunouchi/Ginza *look* like shared corridors on the
render and are not — they pass near each other through different stations.

## E — smooth curves

`input/style_e_curves.py`, centripetal Catmull–Rom (α = 0.5) over the true
geographic positions, converted per segment to cubic Bézier, sampled every
0.7 mm, with the control handles leashed to 0.30 × chord.

- Zero spline-induced self-crossings. The two crossings that remain are in
  the station order itself: the Ōedo line is a lasso and genuinely crosses.
- The curve passes within 1.1 mm of a foreign LED in exactly the 11 places
  the straight polyline already does — it adds no new pad conflicts.
- Curving the *octolinear* positions instead is worse than either parent:
  the straight runs stay straight, so the curvature piles up at the old
  corners and it reads as badly-drawn octolinear.

It is the best-looking colour render from this data and the worst board. In
single-colour silk the continuous curvature removes the last cue the eye has,
and the central cluster becomes untraceable. It also costs something
physical: the LED footprints rotate to aim DOUT along the track, and a
continuously changing direction means no two footprints share a rotation,
where octolinear gives eight.

## G — thin uniform routes, station rings

The aesthetic of the two boards already built: hairline routes, rings rather
than dots, and the water carrying the composition. At 219 stations the hairline
routes thin out the core usefully, and it is the most buildable of the
alternatives. The real difference from A is weight, not geometry, so it can
be chosen late — it is a line-width constant, not a layout.

## H and I — the label question

H is all 219 English names at the real 1.1 mm silkscreen height, dropped
straight off each station with no optimiser. Two thirds of the board is
already readable; only the central cluster piles up. That is a better
starting point than Vancouver's downtown was, and it means names are
affordable — the label pass has a dense core to solve, not a whole board.

I is the same map with station codes (G-09, M-17). Half the ink, but a code
needs a legend the board has no room for, and a visitor reads names. Codes
stay the fallback for the handful of stations whose name cannot be made to
fit (lesson A4).

## Recommendation

**Build A, at G's line weight, with D applied only to corridors of three or
more legs, labelled with names as in H.**

That is one style, assembled from the four that passed the board test:

1. **A is the base.** Octolinear runs on true-scale land is the only
   candidate that stays followable in white-on-green, and it is the one the
   Montréal board already proved. It also keeps the land, which is the
   reason these boards look like anything.
2. **G's weight, not A's.** Hairline routes and station rings. At 219
   stations the heavier stroke closes up the core, and the weight is a
   constant, not a layout — it can be settled late from a render.
3. **D, but only on the Yūrakuchō/Fukutoshin run.** Eight legs is long
   enough to read as two parallel routes; a single leg is not, and the six
   one-leg lenses look like drawing errors. On the board this buys nothing
   at all (both strands are the same white), so if the silkscreen is the
   only deliverable, drop D entirely and keep the single centreline.
4. **Names, not codes.** H shows the outer two thirds of the board already
   reads with no optimiser at all. Codes stay the fallback for the handful
   of stations in the core whose name cannot be placed.

**Rejected, with reasons worth keeping:**

- **C (official look)** loses on hardware, not looks: offsetting a strand
  from its station leaves the LED off its own line at exactly the
  interchanges where it matters most.
- **E (curves)** loses on the board test: in single-colour silk a corner is
  the only cue the eye has to follow a line, and curves have none. It also
  costs the octolinear footprint rotations — LEDs rotate to aim DOUT along
  the track, and a continuously changing direction means no two footprints
  share an angle.
- **B (true geographic)** stays as the variant the data is checked against.

**The open composition question**, which no style settles: the bay fills the
bottom-right quarter of the board and the south-west corner is empty land.
Cropping the frame tighter would raise mm/km for free and give the labels
more room, at the cost of the Tōzai line's eastern tail and the Ōedo line's
north-western one. That is a decision about what the board is of, not about
how the lines are drawn.

## Settled, 2026-10-18

**A, with the tighter crop, the thick weight, names, and one offset
corridor.** Built by `input/build_final.py`, which assembles the pieces
rather than reimplementing them: the layout comes from
`build_tokyo.py --leg-cap 15`, the corridor offset from
`style_d_offset.py`, the frame from `tools/style_sheet.py`.

| | |
|---|---|
| Layout | octolinear, legs capped at 15 mm |
| Routes | 0.9 mm silkscreen — the thick weight, not the Vancouver hairline |
| Labels | English names at 1.1 mm |
| Offset corridors | 1, the eight-leg Yūrakuchō + Fukutoshin run; the other 8 keep a single centreline |
| Board | 400 × 292 mm, 219 LEDs |

### What the tighter crop actually bought

Less than I implied when I offered it. The honest numbers, measured in the
60 mm around Ōtemachi:

| | core median leg | core nearest neighbour | drawing |
|---|---|---|---|
| no cap | 9.8 mm | 4.8 mm | 364 × 264 mm |
| cap 18 mm | 10.2 mm | 5.0 mm | 360 × 263 mm |
| **cap 15 mm** | **10.7 mm** | **5.2 mm** | 353 × 264 mm |

About +9 % of room in the core, not the large win a "tighter crop" sounds
like. The reason is that the board's **height** is the binding dimension and
the network's north–south extent is evenly populated — there is no vertical
tail to cut. The long legs that the cap does shorten (Motoyawata–Shinozaki
at 35 mm, Minami-sunamachi–Nishi-kasai at 32 mm, Kita-senju–Ayase at 31 mm)
are nearly all east–west, so shortening them frees width the board cannot
spend.

Two things had to be fixed for even that much to show up:

- the fit-to-board loop only ever **shrank** the drawing. Without scaling up
  as well, a leg cap just makes a smaller map on the same board and the core
  gains nothing.
- the cap is applied to the leg's *target* length inside the solve, not by
  moving stations afterwards, so the straightening keeps the run straight
  through the shortened leg.

## Four changes, 2026-10-18 (later)

**1. The Ginza line was doubling back, and it was a real defect.** At
Tameike-sanno the drawn line turned −171° where the city turns +33°, and at
Akasaka-mitsuke +167° where the city turns −68°: the line folded back
through both. The cause was in the solve. Minimising the sideways part of a
leg is just as happy with the leg *reversed*, and the direction was re-snapped
from the current positions each round, so once a leg flipped, the next round
snapped to the flipped direction and it stayed flipped. Fixed by snapping
against the geography instead: a leg may only be turned `MAX_TURN` (67.5°,
one and a half octants) from its true direction, and `build_tokyo.py` now
reports *legs folded past a right angle from the truth*, which must be none.

The cost is real: 159 of 267 legs now sit within 1° of a 45° direction,
against 185 before. Removing a visible U-turn is worth 26 slightly-off legs.
The Ginza line still has a sharp zig-zag there (+110°, −115°) because the
real line genuinely does — Toranomon to Tameike-sanno to Akasaka-mitsuke to
Aoyama-itchome goes north, then west, then south-west inside a kilometre.

**2. Shared corridors overlap again.** `--offset none` is now the default in
`build_final.py`. Both lines draw on one centreline, which is honest about
them sharing a tunnel and costs nothing on a board where every route is the
same white silkscreen.

**3. The map carries 219 LEDs, and leaves a great deal out** — see the next
section.

**4. A zoomed variant** (an intermediate, not kept; see `input/rebuild.sh`), built with
`--crop 35.615,139.655,35.765,139.885` and no leg cap: 183 LEDs, 36 stations
dropped, and the land placed at **17.6 mm/km instead of 11.7**.

| | LEDs | core median leg | core nearest neighbour |
|---|---|---|---|
| full network | 219 | 9.8 mm | 4.8 mm |
| full, legs capped at 15 mm | 219 | 11.0 mm | 5.7 mm |
| **zoomed crop** | **183** | **15.2 mm** | **6.2 mm** |

The crop beats the cap by a long way, and it makes the cap unnecessary: with
the outer tails gone there are no long legs left to cap, and capping them
only stopped the drawing growing into the board. What it costs is the ends of
nine lines — the Mita line north of Shimura-sakaue (8 stations), the Tōzai
line east of Urayasu (6), the Ōedo line's Nerima branch (4), Yūrakuchō and
Fukutoshin beyond Heiwadai (4, which also takes Wakōshi), the Shinjuku line
past Mizue (3), and the rest in ones and twos.

## What the board does not carry

219 LEDs is Tokyo Metro's 9 lines plus Toei's 4 **subway** lines. Counted
from OSM route relations inside the board's frame (`input/queries/
other_rail*.ql`, cached in `input/osm/`), this is what is left out:

| | Stations in frame | Note |
|---|---|---|
| JR Chūō / Chūō-Sōbu (JC, JB) | 60 / 39 | runs well past the frame |
| JR Keihin-Tōhoku (JK) | 47 | ditto |
| **JR Yamanote (JY)** | **30** | the loop everyone pictures when they think of Tokyo |
| **Toden Arakawa line / Tokyo Sakura Tram (SA)** | **30** | **Toei**, but a tram, so not in the subway data |
| JR Saikyō (JA) | 19 | |
| **Yurikamome (U)** | **16** | Shimbashi–Toyosu, over the bay the board already draws |
| **Nippori-Toneri Liner (NT)** | **13** | **Toei**, but an automated guideway |
| Tokyo Monorail (MO) | 11 | Hamamatsuchō–Haneda |
| Tōkyū Setagaya line (SG) | 10 | a tram |
| Rinkai line (R) | 8 | |

Plus every private railway in the frame — Tōkyū, Keiō, Odakyū, Seibu, Tōbu,
Keisei, Keikyū, Tsukuba Express, Hokusō, Tōyō Rapid, Saitama Rapid — most of
which through-run onto the subway lines the board does have.

Two of these deserve a decision rather than silence, because the scope was
written as "Tokyo Metro + Toei" and **Toei operates both**: the Arakawa tram
(30 stops) and the Nippori-Toneri Liner (13). Adding them would be 262 LEDs.
The Yamanote loop (30) is the other tempting one: it is not Toei and not a
subway, but it is the shape most people read Tokyo by, and the board
currently draws the city with a hole where it runs.

## More bay, and the lines that were missing (2026-10-18, later still)

### Four lines added

`build_station_latlon.py` now reads `osm/other_rail_stops.json` as well, and
carries four lines that are not subways:

| | | In the crop | New LEDs |
|---|---|---|---|
| **SA** Toden Arakawa line / Tokyo Sakura Tram | Toei — a tram, which is why the subway query never saw it | 30 of 30 | +29 |
| **JY** JR Yamanote | the loop the city is read by | 30 of 30 | **+12** |
| **U** Yurikamome | the bay-front guideway, Tokyo-owned | 16 of 16 | +13 |
| **R** Rinkai line | Tokyo-owned, the bay to Osaki | 6 of 8 | +5 |

The Yamanote is the bargain: 18 of its 30 stations are already LEDs, so the
loop costs 12.

**Three were left out, on one rule: a line is only drawn if nearly all of it
is inside the map.** A line showing six of its thirteen stations reads as
broken, not as a line. That rules out the Nippori-Toneri Liner (6 of 13 in
the crop, and Toei), the Tokyo Monorail (2 of 11 — it runs south to Haneda,
off the board) and the Tōkyū Setagaya line (4 of 10). Widening the crop to
the south would bring the monorail and the rest of the Rinkai line in, at
the cost of the scale the crop just bought.

Full network: **279 stations**. Inside the crop: **241**.

### More bay

The board is a fixed 400 × 292 mm window, so showing more of what lies
south-east of the network means putting the network in the north-west corner
and shrinking the drawing to make room. `build_tokyo.py` gained `--fill` and
`--anchor nw` for exactly that. It is a straight trade against scale:

| | LEDs | drawing | median core leg | land |
|---|---|---|---|---|
| zoom, filling the board | 241 | 326 × 262 mm | 13.9 mm | 16.1 mm/km |
| **zoom, `--fill 0.91 --anchor nw`** | 241 | 297 × 239 mm | 12.9 mm | 14.7 mm/km |
| **zoom, `--fill 0.84 --anchor nw`** | 241 | 275 × 221 mm | 12.1 mm | 13.6 mm/km |

Both bay versions still beat the full 219-station map's 9.8 mm, and the
0.84 version is about where the capped full map was (11.0 mm) while showing
two thirds more bay and 22 more stations.

## Centred, with the bay below (2026-10-18, final framing)

`--bay MM` reserves board height at the bottom and `--anchor n` centres the
drawing across the board above it, so the water gets room without the map
sliding into a corner.

The first attempt reserved 55 mm and kept the old crop: it worked, but it
left the bottom **left** corner empty — that corner is Ōta ward, which is
land, not bay, and its stations had been cropped away. The fix was to crop
*south* rather than reserve more height, bringing the Asakusa line's tail to
Nishi-magome back in to fill the corner, and to cut the reserve to 25 mm.

| | LEDs | core median leg | drawing | gap below |
|---|---|---|---|---|
| corner-anchored, fill 0.84 | 241 | 12.1 mm | 275 × 221 mm | 57 mm |
| centred, 55 mm reserved | 256 | 11.4 mm | 353 × 208 mm | 70 mm |
| **centred, cropped south, 25 mm reserved** | **262** | **11.3 mm** | 344 × 237 mm | 41 mm |

Crop `35.580,139.600,35.765,139.930`. **262 of 279 stations**, at 12.33
mm/km. Height is what binds the drawing, so stations to the east and west
came back almost free — Ogikubo and Minami-asagaya in the west, Urayasu,
Myōden and Gyōtoku in the east, the Shinjuku line out to Motoyawata, and the
Asakusa line down to Nishi-magome.

The 17 still cropped out are all in the far north and north-west, which
makes the cut explicable rather than arbitrary: the Mita line's Takashimadaira
branch (7), Namboku north of Oji (3), Yūrakuchō and Fukutoshin out to Wakōshi
(3), the Tōzai line past Urayasu (2), Kita-ayase and Motohasunuma.

## Square board (2026-10-18, final)

`build_tokyo.py --board WxH` sets the board size instead of taking the
frame's aspect, and the size now travels in the data file so the renders
follow it.

Crop `35.580,139.643,35.765,139.889` — about 4 km off each side — gives a
frame whose aspect suits a square board with 25 mm reserved at the bottom
for the bay. **251 stations**, and all four of the added lines are complete:
the Yamanote's 30, the Arakawa tram's 30, the Yurikamome's 16 and the Rinkai
line's 8.

| | LEDs | core median leg | board | area |
|---|---|---|---|---|
| 400 × 292 mm, 262 LEDs | 262 | 11.3 mm | 1.37 : 1 | 0.117 m² |
| **square 340 × 340 mm** | **251** | **12.8 mm** | 1 : 1 | **0.116 m²** |
| square 400 × 400 mm | 251 | 14.9 mm | 1 : 1 | 0.160 m² |

**340 × 340 mm is the one to take**: it is square, it holds the same board
area — and so roughly the same fabrication cost — as the 400 × 292 board it
replaces, and the core still gains, 11.3 mm to 12.8 mm, because the eleven
stations the narrower crop drops were all outer ones.

400 × 400 mm buys another 2 mm of core spacing for 37 % more board area,
which is 37 % more copper, more ENIG and a heavier parcel: lesson A11's
shipping tier is already a live concern at 400 mm.

The eleven dropped relative to the 262-LED framing are Ogikubo and
Minami-asagaya in the west, the Tōzai line past Urayasu, the Shinjuku line
past Funabori, and Hikarigaoka and Nerima-kasugachō on the Ōedo's
north-western arm.

## Lines run off the edge

A line that leaves the map now runs on to the board edge instead of stopping
at its last station, so the board reads as a window on a bigger network
rather than as a system with nine odd termini. `build_tokyo.py` records each
place a path was cut and the station it was heading for; the stub takes the
true bearing toward that station, snapped to the nearest 45° so it matches
the octolinear geometry, and runs to the edge. Nine of them on the 340 mm
board.

## How small the board can safely go

| board | min pitch | core median leg | names crowded | relative distortion | area |
|---|---|---|---|---|---|
| 340 × 340 | 3.48 mm | 12.8 mm | 121 of 251 | 287 m | 0.116 m² |
| 320 × 320 | 3.46 mm | 12.0 mm | 127 | 285 m | 0.102 m² |
| **300 × 300** | **3.45 mm** | **11.1 mm** | **136** | 276 m | **0.090 m²** |
| 280 × 280 | 3.34 mm | 10.2 mm | 142 | 284 m | 0.078 m² |
| 260 × 260 | 3.35 mm | 9.5 mm | 157 | 282 m | 0.068 m² |
| 240 × 240 | 3.31 mm | 8.7 mm | 167 | 278 m | 0.058 m² |

Three things this says:

1. **The LED pitch floor is not what stops you.** The solve holds 3.3 mm all
   the way down to 240 mm, because it buys the clearance by moving stations.
2. **Distortion does not get worse.** Measured against the best rigid
   alignment of the real geography and converted back to metres on the
   ground, it sits at about 280 m at every size — the map shrinks, and the
   error shrinks with it.
3. **Labels are the limit.** "Crowded" counts stations whose nearest
   neighbour is closer than half their own name plus a standoff, with the
   name 1.03 mm per character (1.1 mm text in KiCad's stroke font, which
   runs about 10 % wider than 0.85 × size — lesson B6). That count rises
   from 121 to 167 as the board shrinks, and every one of them is work for
   the label pass or a leader line.

**300 × 300 mm is the smallest I would call safe.** It keeps 0.15 mm of
margin above the pitch floor, its core spacing matches what the 400 × 292
board had, and it is 22 % less board area than 340 × 340. Below 280 mm the
minimum pitch sits within 0.04 mm of the floor, which is where a real DRC
run starts failing rather than warning.

## The font is worth more than 40 mm of board

KiCad 10 plots TrueType, so the stroke font is a choice, not a constraint.
Measured over all 279 station names at a 1.1 mm cap height, and with glyph
stems measured by rendering and scanning them:

| font | width per character | thinnest stem at 1.1 mm | height needed for a 0.15 mm stem |
|---|---|---|---|
| KiCad stroke font | 1.030 mm | 0.140 mm (set explicitly) | — |
| Arial | 0.786 mm | 0.136 mm | 1.22 mm |
| Tahoma | 0.757 mm | 0.135 mm | 1.22 mm |
| **Franklin Gothic Medium Cond** | **0.697 mm** | **0.164 mm** | 1.01 mm |
| Franklin Gothic Demi Cond | 0.721 mm | 0.205 mm | 0.81 mm |
| Gill Sans MT Condensed | 0.524 mm | 0.119 mm | 1.38 mm |

Two things fall out of that table.

**A condensed face is 32 % narrower *and* thicker in the stem.** Franklin
Gothic Medium Condensed draws a name in 0.697 mm per character against the
stroke font's 1.030, and its thinnest stem at that height is 0.164 mm —
above JLCPCB's 0.15 mm silkscreen minimum, where the stroke font sits at
0.140 mm and most regular-weight faces at 1.1 mm come out at 0.12–0.14 mm,
*under* it. The usual worry about outline fonts at small sizes is backwards
here: the right outline font is the safer one to print.

**It is worth about 40 mm of board.** Counting the stations whose nearest
neighbour is closer than half their own name plus a standoff:

| board | stroke font | Franklin Gothic Med Cond |
|---|---|---|
| 340 × 340 | 121 of 251 | **87** |
| 320 × 320 | 127 | 92 |
| 300 × 300 | 137 | **99** |
| 280 × 280 | 142 | 105 |
| 260 × 260 | 157 | 119 |

A 300 mm board in the condensed face (99 crowded) is a better place to start
the label pass than a 340 mm board in the stroke font (121). Either take the
font and keep 340 mm, which cuts the label work by 28 %, or take the font
and shrink the board.

**Licensing, which decides which face to actually use.** Franklin Gothic
ships with Microsoft Office and is not redistributable, so committing it
would not make the repo reproducible. KiCad plots text to polygons in the
gerbers, so the fab never needs the font — but anyone rebuilding the board
does. The libre equivalents to test next are Roboto Condensed, Archivo
Narrow, Liberation Sans Narrow and Noto Sans Condensed, all SIL OFL and all
fine to commit into the repo. None is installed on this machine yet, so the
numbers above are from Franklin Gothic; expect the libre faces to land
within a few per cent.

One correction to earlier renders: the label previews before this used
matplotlib's default DejaVu Sans at 0.864 mm per character, which is
*narrower* than the stroke font. They were slightly optimistic about how the
stroke font would crowd.

## The Shinkansen

On the board as a line of its own, drawn at **2.2 × the normal route width**
so it does not read as a metro line, from `input/hand_lines.json`.

It costs nothing: all three of its stations inside the frame — Ueno, Tokyo
and Shinagawa — are already LEDs. Two arms, Ueno–Tokyo and Tokyo–Shinagawa,
with short runs off each end toward Ōmiya and Shin-Yokohama.

Recorded simplifications: the Tōhoku and Tōkaidō Shinkansen are two separate
railways that meet at Tokyo, drawn here as one line, because on a board whose
point is "this one is different" a second colour would not earn its place.
OSM has the Tōhoku arm as relations 9326156 / 9349293; it has no Tōkaidō
Shinkansen route relation in this bbox, so that arm is hand-made from the two
stations it serves.

**Stubs are now bounded at 35 mm.** Unbounded, the Shinkansen's two ran
137 mm and 157 mm and cut a diagonal right across the map — because the
bearing to the next stop, Ōmiya 25 km away, is not the direction the track
leaves Ueno by. A stub whose next station is more than 5 km off now carries
on the way the line arrived instead. All eleven crop stubs are 16–33 mm, so
they still reach the board edge.

## The font, settled: Archivo Narrow SemiBold

Franklin Gothic measured well but ships with Office and cannot be committed,
so the repo now carries a libre equivalent in [`fonts/`](../fonts/):

| | per character at 1.1 mm | thinnest stem at 1.1 mm |
|---|---|---|
| KiCad stroke font | 1.030 mm | 0.140 mm |
| Franklin Gothic Medium Cond (not redistributable) | 0.697 mm | 0.164 mm |
| Archivo Narrow, weight 400 | 0.682 mm | 0.131 mm — **under the 0.15 mm fab minimum** |
| **Archivo Narrow SemiBold (weight 600)** | **0.709 mm** | **0.171 mm** |

`ArchivoNarrow-SemiBold.ttf` is a static instance cut from the variable font
with fontTools, because KiCad is likely to take a variable font's default
instance — which is weight 400, and whose 0.131 mm stems would print badly.
Licence: SIL OFL 1.1, `fonts/OFL.txt`, so it can live in the repo and anyone
can rebuild the board.

`citymap.CHAR_W` is now 0.65, from the measured 0.645 with a little margin.
It was 0.85 for the stroke font, so every label is 24 % narrower than the
optimiser previously assumed.

## Stubs run to the edge

`STUB_MAX_MM` is effectively off: a stub now runs all the way to the board
edge. The Shinkansen enters at the top edge, runs down through Ueno, Tokyo
and Shinagawa, and leaves at the bottom — 97 mm in and 111 mm out. What
keeps that honest is the direction rule rather than a length limit: a stub
whose next station is more than 5 km off the board follows the line's own
last leg instead of the bearing to that station, which is what turned the
Shinkansen's diagonal into the vertical spine it should be.

## Making the label optimiser usable at 251 stations

Montréal's optimiser took 3.34 s per station here, so one greedy pass over
251 stations was 14 minutes and the 40,000-iteration anneal on top of it was
hours. Two changes, neither of which alters an answer:

1. **Bounding-box prefilter** on every static obstacle — route segments,
   silk furniture, annotations, water. A label can only touch what overlaps
   its own bounding box. 3.34 s → 1.67 s.
2. **A grid index over each water polygon's edges** (`check_fit.GeoIndex`,
   8 mm cells). Profiling put 80 % of the time in `box_poly_overlap`:
   Tokyo Bay alone is thousands of points, and every candidate placement of
   every label walked all of them. The index tests only the edges in the
   cells the label box covers, then one point-in-polygon for the
   box-inside-polygon case, plus a bbox-containment test for a pond small
   enough to sit entirely under a label. 1.67 s → 0.34 s.

Checked against the original on 9,900 box/polygon pairs: identical answers.
A greedy pass is now 1.4 minutes.

## The first label pass

`auto_label.py` over all 251 stations, two greedy passes then the anneal and
the polish:

| | |
|---|---|
| Collisions before | 1,428 (1,019 label-on-line, 311 label-on-dot, 31 label-on-label) |
| **Collisions after** | **25** |
| Labels left horizontal | 212 of 251 |
| Rotated 45° | 31; vertical or odd angles, 8 |
| Leader lines | 21 |
| Two-line labels | 0 |

The 25 that remain are where lesson B4 said they would be — Ōtemachi,
Nihombashi, Mitsukoshimae, Ginza, Kyōbashi, Takaracho, Toranomon,
Uchisaiwaichō — plus three against the Shinkansen's heavy line, which is new
and worth watching: a 2.2× stroke is a much bigger obstacle than a normal
route.

**The annealer earned nothing here.** Its best never improved on the greedy
result (6,072) across 40,000 iterations; only the polish pass did,
6,072 → 5,885. Montréal's schedule starts at T=60, which at 251 stations is
hot enough that it spends the whole run worse than where it started — it
peaked at 12,512. Either the temperature should scale with the station count
or the anneal should be skipped and the time spent on the hand pass instead.

`preview_map.py` now draws in `fonts/ArchivoNarrow-SemiBold.ttf` rather than
DejaVu Sans Mono. The preview has to crowd exactly as the board will, and
`citymap.CHAR_W` is measured from that font — a preview in any other face
makes the label pass look better or worse than it is.

## Where the label pass stops, and what is left for the hand

A second run, with the 180 settled labels frozen and only the 71 stations
around the collisions free to move, and a longer anneal: the score improved
(5,885 → 5,739) and the collision count did not. **25 is the optimiser's
floor with the candidate set it has**, and the 25 are a slightly different
25 — it is trading one crowded label for another, not solving them.

That matches lesson B4: "even that left a handful for a human". The handful
is 10 % here, and it is the same streets every time — Ōtemachi, Nihombashi,
Mitsukoshimae, Ginza, Kyōbashi, Takaracho, Toranomon, Uchisaiwaichō,
Kasumigaseki — plus three against the Shinkansen's 2.2× stroke, which is a
new kind of obstacle for this pipeline.

All but two are label-on-line: white text crossing a white route. That is
not a warning to accept, it is unreadable, so these are hand work in KiCad
(Phase 7) and then frozen with `import_labels.py`.

**The annealer should go.** It contributed nothing on the full board and
nothing on the subset. Its schedule starts at T=60, which is hot enough at
this station count that it spends the whole run worse than where it started.
The greedy passes plus the polish do the work.

Also corrected: 59 labels already set on two lines, wrapped automatically at
the hyphen. An earlier count of "0" was reading the explicit override field
rather than what renders.

## The chain

`tools/build_chain.py`, nearest-neighbour from the LED closest to the
controller corner, then 2-opt and Or-opt:

| | |
|---|---|
| Data line, nearest-neighbour | 3,362 mm, worst hop 135 mm |
| **After 2-opt / Or-opt** | **3,106 mm**, worst hop 69 mm |
| Mean hop | 12.4 mm |

8 % shorter, and the worst hop more than halved — which is the number that
matters, because one long jump has to cross every line in its way.

**38 of the 250 hops cross bare-copper water, 174 mm of water in total.**
The front-side water is a solder-mask opening with no net, so none of those
crossings can run on the front: they go down a via, across on the back, and
back up. The worst are the bay crossings — Telecom Center to Shinagawa
Seaside, Shinagawa Seaside to Ariake — which is the price of having the
Yurikamome and the Rinkai line out on the islands.

## 67 LEDs sit in a hole cut out of the water

Not a defect to fix — it is what drawing Tokyo's rivers through the city
costs. But it is lesson A5 in advance: the front ground pour will be cut
into islands, and **every one of those 67 LEDs needs its own via to the back
plane**. Montréal shipped with one LED stranded on a 22 mm² island, second
in the chain, which would have left 71 of 73 LEDs dark. At 67, eyeballing it
is not an option; the pour-island count has to be a scripted check before
the board is ordered (Part C, item 5).

90 LEDs have water within 3.4 mm and so get the wider via clearance; 118
have water within 5 mm.

## Station rings halved

`RING_R` 1.25 → 0.63 mm, `RING_R_INT` 1.55 → 0.78 mm, with the strokes
brought down to 0.15 / 0.20 mm to match.

**What that means on the real board, measured rather than assumed.** The
XL-1615's four pads reach **1.15 mm** from the part centre. A halved ring is
0.70 mm at its outer edge, so it sits entirely under the pads and the body:

| | outer edge | clears the 1.15 mm pads? |
|---|---|---|
| before, 1.25 / 0.25 | 1.38 mm | yes, just |
| **halved, 0.63 / 0.15** | **0.70 mm** | **no — under the part** |
| smallest that clears, 1.33 / 0.18 | 1.42 mm | yes, with a lighter stroke |

And it is not merely hidden: silkscreen cannot print on a solder-mask
opening (lesson A6), and the pads are openings, so the ring is clipped out
of the gerbers rather than printed under the LED. The halved ring will not
exist on the board.

Two consequences worth deciding on:

- **The station marker becomes the LED itself.** Unlit, that is the white
  package, which does read as a dot — this is a legitimate look, just a
  different one from Vancouver and Montréal.
- **Interchanges stop being distinguishable.** The heavier ring was the only
  thing separating them from ordinary stations, and both rings disappear.

`rings-clears.png` is the alternative: radius 1.33 mm, stroke 0.18 instead
of 0.25, which halves the *ink* while keeping the ring outside the pads.

Halving the rings buys no label room, incidentally: `check_fit`'s keepout
around a station is set by the 1.15 mm pad reach, not by the ring, so the
25 remaining label collisions are unchanged.

## The holes cut out of the water

They cannot go away entirely: the water is an F.Cu polygon with **no net**,
so a pad inside it is shorted to it — all four pads of that LED shorted
together. The question is only how small the hole can be.

| | radius | what it is |
|---|---|---|
| before | 2.2 mm | pads + clearance + room for an escape via |
| **now, ordinary station** | **1.4 mm** | pads reach 1.15 mm, plus 0.25 mm clearance |
| now, station with water all round | 2.2 mm | the via has nowhere else to go |

At 1.4 mm the hole is barely wider than the LED package itself (1.6 × 1.5 mm),
so it reads as the part sitting in the river rather than as a hole cut around
it.

**Only two stations need the bigger disc** — Hamamatsuchō and Tatsumi, the
two with water all the way round at 2.6 mm. Everywhere else the ground pad
can reach the back plane from the land side, so no via has to fit inside the
water.

The measurable effect is that the rivers rejoin: **the water went from 26
separate pieces to 16**, because the old 2.2 mm discs were cutting narrow
rivers into fragments at every station on them. Total water area rose from
20,155 to 20,433 mm².

## Rebuilds no longer destroy hand work

Making that change meant rebuilding the data file, which would have thrown
away all 251 label placements and the chain — exactly the mistake lesson B5
is about. `build_tokyo.py` now takes `--labels` and `--chain` and re-applies
them after the rebuild, reporting how many it restored and naming any that
are for stations no longer on the board. The frozen copies live in
`input/label_overrides.json` and `input/chain.json`, and the
rebuild above restored 251 of 251 labels and all 251 chain entries.

## Three fixes from the preview

**The Shinkansen was in the data but invisible in `preview_map.py`.** That
tool predates both the line weights and the edge stubs: it drew every route
at one width and ignored `stubs` entirely, so the Shinkansen looked like any
other line and its runs on and off the board were missing. `citymap.Line`
now carries `weight` and `stubs`, and `preview_map` honours both — which
matters beyond looks, because this is the tool that shows what the board
will etch.

**The band along the bottom was the geography frame, not a border.** The
land is placed by fitting it to the stations, so wherever the frame stops,
the water stops — and `geo_tokyo.LAT1` was 35.578, barely past the
southernmost station, which left the bottom 25 mm of a 340 mm board blank
where Tokyo Bay should be. The cached water reaches 35.40, so the data was
always there. `LAT1` is now 35.500, and the water runs to the board edge:
**20,433 → 25,223 mm² of copper, and 16 pieces down to 15.**

**The wordmark.** `TOKYO`, 14 mm cap height, in copper like the water,
searched for rather than placed by hand so it follows the layout instead of
quietly ending up on a line. The search covers the lower-left quarter and
wants land that clears every route by 3 mm and every LED by 7 mm, with a
2 mm margin of land all round the block; it scores by clearance and leans
toward the corner. It landed at (41, 271) mm, 46 × 18 mm, on the Ōta ward
land between the Tama river and the Asakusa line's tail.

## Bottom eighth cropped: 340 × 298 mm

The bottom eighth of the square board was almost entirely open bay — one
station sat in it (Nishi-magome, at y = 298 of 340) and the wordmark was
clear of it at y = 271. Cutting it costs no stations: the layout refits into
the shorter board and Nishi-magome comes with it.

| | 340 × 340 | **340 × 298** |
|---|---|---|
| Core median leg | 12.2 mm | **11.4 mm** |
| Minimum pitch | 3.31 mm | 3.32 mm |
| Water pieces | 15 | 13 |
| Board area | 0.116 m² | **0.101 m²** |

The bay reserve came down from 25 mm to 8 mm at the same time — the reserve
existed to show bay below the map, and cropping the bay is the opposite
request, so holding 25 mm of it back would have spent the saving twice.

Two costs, both small: 7 % of core spacing, and the board is no longer
square (1.14 : 1). Keeping it square while cropping the bottom eighth would
mean taking the same 42 mm off the width, which does cost stations — the
east and west tails are populated where the bottom is not.

## Cropping is not the same as building smaller

Rebuilding at 340 × 298 did not crop anything, and that is worth
understanding rather than patching around: the layout **fits itself to
whatever board it is given**. A shorter board just draws the same map
smaller, so the proportion of bay along the bottom is unchanged — which is
exactly what the render showed.

To remove the bottom of the map the scale has to stay put and the board edge
has to move in. `tools/crop_board.py` does that: it keeps everything above
the new edge where it is, clips the water to the new outline, drops any
station that falls off (and takes it out of the line paths, the chain, the
shapes and the labels), pulls the mounting holes in, moves the wordmark up
if the crop would have cut it, and gives any line that lost its end a stub
running off the new edge — the same treatment the data crop gives.

| clip | removed | stations lost |
|---|---|---|
| 340 × 312 | 28 mm | none |
| **340 × 298** | **42 mm, the full eighth** | **Nishi-magome** |
| 340 × 290 | 50 mm | Nishi-magome, Magome |

The floor is set in the south-**west**, not the south-east: the bottom of the
board is open bay on the right, but the Asakusa line runs down to
Nishi-magome at y = 298 of 340. 312 mm is as far as the crop goes for free;
the eighth that was asked for costs exactly one LED, and the Asakusa line now
runs off the bottom edge past Magome instead of stopping dead.

It refuses to drop a station unless `--drop-stations` says so, because
losing an LED silently to a board-size change is the kind of thing that is
only noticed in the BOM.

## Cropped to 320 × 280 mm, 248 LEDs

Right edge just inside Ichinoe, bottom edge just above Magome:

```
# as input/rebuild.sh runs it, on the uncropped layout it builds first
python -X utf8 crop_board.py ../input/tokyo-schematic-full.json 320x280 \
    ../input/tokyo.json --drop-stations
```

| | 340 × 340 | **320 × 280** |
|---|---|---|
| LEDs | 251 | **248** |
| Core median leg | 12.2 mm | **12.2 mm** |
| Minimum pitch | 3.31 mm | 3.31 mm |
| Board area | 0.116 m² | **0.090 m²** |

**The core spacing is identical, and that is the whole point of cropping
rather than rebuilding smaller**: the scale is untouched, so 22 % of the
board area goes away and the labels are no harder to place than before.

Three LEDs go: Ichinoe on the Shinjuku line's eastern tail, and Magome and
Nishi-magome on the Asakusa line's southern one. Both lines now run off
their new edges rather than stopping dead — the Shinjuku line past Funabori
to the right, the Asakusa line past Nakanobu to the bottom. The wordmark was
inside the cut and moved up to y = 267 mm automatically.


## Housekeeping, 2026-10-19

`input/tokyo.json` is the board: 248 LEDs, 320 × 280 mm, 18 lines, with the
labels and the chain in it. `input/rebuild.sh` makes it from the cached OSM
responses in one command, so every intermediate the sections above mention —
the cap, zoom, bay, square and crop variants — was disposable and has been
deleted rather than committed. The renders those sections cite are kept;
the one-off experiment renders are not.

Hand work lives in two files and is re-applied on every build:
`input/label_overrides.json` (248 placements) and `input/chain.json` (the
248-LED order). Nothing else in `input/` is hand-made except
`future_stations.json`, `hand_lines.json` and the Overpass queries.

## The iconic pass (2026-10-19)

Feedback: the map was "too busy with lines near horizontal but not quite",
wanted "less natural and more iconic", thinner lines, and overlapping lines
combined. Then: accurate water, no station in the water, and tracks free to
curve. Then: visual appeal first, accuracy second.

### What the numbers said

| | before | after |
|---|---|---|
| legs exactly on a 0/45/90 axis | 29% | 86% |
| legs folded past a right angle | 1 | 0 |
| stations in the water | 32 | 0 |
| label-on-label collisions | 24 | 1 |
| labels sitting on a track | 55 | 14 |
| station pairs under the 3.3 mm pitch floor | 0 | 5 |
| geographic error, mean | 569 m | 499 m |

Geographic fidelity **improved** while the map became far more octolinear,
which was not expected and is worth remembering: the straightening is not
paid for in accuracy, it is paid for in the pitch floor.

### Things that did not work, and why

- **Moving stations out of the water.** The obvious fix, and it never
  converges: off one bank in this delta is onto another. Six passes went
  66, 60, 64, 52, 52, 62 stations still wet, and the geographic error
  tripled (2.3 km to 6.6 km worst case). Abandoned.
- **Narrowing the water** (a morphological opening) got 52 wet stations down
  to 7 at zero cost in station movement - but at 2.2 mm it erased the Sumida
  and the Arakawa. Rejected on accuracy; the water is the truth.
- **Merging shared corridors into one stroke.** Asked for, and it makes the
  map *worse*: eleven lines on one x drew as a single 127 mm bar, and in the
  centre a merged trunk is heavier than the eleven thin lines it replaced.
- **Enlarging the dense centre.** Works, costs almost nothing in accuracy
  (504 m against 499 m) and even recovers two stations - but it does not
  visibly beat thinning, and it distorts for no gain. Dropped.

### What did work

- **Ramping the octolinear weight** each round (`--oct-ramp 2.5`), with the
  length wish ramped more slowly (`--len-ramp 1.3`) so short legs are not
  crushed to nothing, and a **physical** separation push afterwards
  (`--separate-last`) because the least-squares pitch floor is only a wish
  and the straightening outvotes it every round.
- **Shifting only the stations that are actually offshore**
  (`--shore-shift`), with the land placement frozen for the pass so the
  coastline does not chase them. The legs into a shifted station change
  direction and `build_shapes` already fillets a direction change, so the
  track curves in rather than kinking.
- **Fanning shared corridors** into parallel lanes (`tools/fanning.py`),
  grouped by collinearity rather than by shared endpoints, because the
  eleven lines down the middle do not share a single pair of stations.
- **Thinning the centre - stroke AND lane pitch together.** Thinning the
  stroke alone leaves the band exactly as wide, only fainter. The pitch is
  what sets band width:

  | | line | lane pitch | 8-lane band | vs 3.8 mm spacing |
  |---|---|---|---|---|
  | as was | 0.75 mm | 1.70 mm | 11.9 mm | 3.1x |
  | chosen | 0.26 mm | 0.68 mm | 4.8 mm | 1.3x |

- **Re-running the label optimiser.** The single biggest win in the centre,
  and it was a self-inflicted problem: `label_overrides.json` is hand work
  frozen for the *old* geometry, and re-applying it to a layout whose
  stations had all moved is what put 55 labels on top of tracks.

### Bridges and tunnels

The official Tokyo subway map draws **no water at all** and ignores every
structure - the Tozai Line's 1,236 m Arakawa truss is an unremarked straight
segment. Drawing the real alignment is a deliberate departure, taken because
on a map that *does* show the coastline, a line cutting the bay in a straight
diagonal is the one thing that reads as plainly wrong.

`crossings.json` carries five legs, from OSM way geometry, simplified by
Douglas-Peucker rather than by spacing - even thinning leaves a point every
N metres along a straight truss, and each short sub-segment lands in its own
corridor bucket, so the fanned lanes hop and the bridge draws as a zigzag.

| line | leg | structure |
|---|---|---|
| Yurikamome | Shibaura-futo - Odaiba-kaihinkoen | Rainbow Bridge lower deck, with the Shibaura loop ramp |
| Tozai | Minami-sunamachi - Nishi-kasai | Arakawa-Nakagawa Bridge, 1,236 m Warren truss over both rivers |
| Rinkai | Tokyo Teleport - Tennozu Isle | Tokyo Port Tunnel, immersed tube |
| Rinkai | Shin-kiba - Shinonome | viaduct over the Tatsumi and Akebono canals |
| Yurakucho | Tatsumi - Shin-kiba | viaduct over the Akebono canal, its only crossing above ground |

The subway crossings of the Sumida are plain bored tunnel with no named
structure, so there is nothing to follow and the straight line is right.

## The organic map (2026-10-19, superseding the iconic pass)

The iconic pass above was paused and the board went to a **straight
realistic map** instead: no artificial straight lines, the trains drawn the
way they actually run.

### What made it possible

`routes.ql` only ever fetched each route relation's **stop nodes**. That is
enough for station order and says nothing about where the rails go, so every
leg was a straight hop by construction - including in the "natural" variant,
which was therefore not natural at all, only unstraightened. `tracks.ql`
fetches the way members with geometry (55 relations, 3,212 ways), and
`make_alignments.py` cuts the piece of each line between consecutive
stations. 264 of 333 legs now follow real rails.

A leg is rejected if its rails run more than 2.6x the straight hop, which is
what stops the Yamanote loop matching the long way round.

### What it cost, against the octolinear attempt

| | octolinear | organic |
|---|---|---|
| station position error | 499 m mean | **6 m mean**, 111 m max |
| pitch-floor breaches | 5 | **0** |
| LEDs | 246 | **248** |

### Stations out of the water

A station's clearance disc notching the river reads as an island in the
middle of it. 33 stations are walked inland until the disc is clear.

The subtlety is **which way**. The drawn water is widened by `MIN_WATER_MM`
so the thinnest channel still etches, and that widening is what swallows a
station standing 30 m back from the bank. So the side test runs against the
**unwidened** water and the clearance test against the drawn one: each
station walks out along the bank it genuinely stands on. Pushing to the
nearest dry point instead puts Ichigaya across the moat.

Verified: 0 of 33 changed land mass, against 41 separate land pieces.
Takebashi keeps its notch - clearing it means crossing the Imperial Palace
moat.

### Capsules, and what they unlocked

Every label sits in a stadium-shaped capsule that **subtracts the route**
behind it. It does not paint a background: whatever is underneath shows
through, substrate or bare copper, because painting flat colour leaves a
dark rectangle sitting in the gold moat at Otemachi.

The shape comes from the text's centre line buffered by half the text
height; buffering the bounding box only rounds its corners and still reads
as a rectangle.

That changed the scoring, and the change was far bigger than the feature:

| | before | after |
|---|---|---|
| leaders | 41 | **6** |
| rotated | 39 | **0** |
| plain horizontal beside the pad | 168 | **242** of 248 |
| two-line labels | 59 | **2** |

`label-line` was 35 of the 63 collisions and cost 100 - the commonest fault
on the board, and the thing driving almost every rotation and leader. With
a capsule knocking the route out it is not a fault at all. The weights are
now, in order of preference: **on a route (0) < on the water (60) <
rotated (150)**. A name across a river still reads; a vertical one barely
does.

`WRAP_OVER` went 13 -> 22 for the same reason. Wrapping was cheap when a
wide label hit more routes; it no longer does, and a hyphenated Japanese
name is one word - breaking "Shinjuku-sanchome" across two lines reads as a
typographic accident.

### The chain

Re-optimised for the new positions, and it exposed a real bug:
`build_chain.py`'s docstring says a long hop is worse than extra total
length, but `tour_length` summed raw distance and the 2-opt branch compared
raw deltas. Optimising for length alone gave a **117 mm hop across the
middle of the board**.

| | total | worst hop |
|---|---|---|
| old chain (schematic layout) | 3448 mm | 72 mm |
| organic, length only | 3081 mm | 117 mm |
| organic, hop-penalised | **3213 mm** | **63 mm** |

### A trap worth naming

Three separate times, a measurement was wrong because **label placement and
the settings it was placed under are stored apart**:

- `label_overrides.json`, hand-frozen for the old geometry, re-applied to a
  layout whose stations had all moved - 55 labels on top of routes.
- A wrap comparison rendered at 13 while the labels had been optimised at
  17, so both panels were identical in the only way that mattered.
- The old board measured at the new `WRAP_OVER`, reporting 11 labels on
  water that were not there.

Every file has to be measured and drawn at the settings it was optimised
under. `WRAP_OVER` lives in `citymap.py` rather than behind a flag for
exactly this reason.
