# Scope and style decisions (Phase 0)

Settled 2026-10-18, before any layout work, as
[runbook-new-city.md](../runbook-new-city.md) Phase 0 requires. Lesson A1:
the scope decision fixes the LED count, and the LED count binds everything
downstream.

## Network — the full Tokyo subway: Tokyo Metro + Toei, transfer stations counted once

Thirteen lines. Tokyo Metro: Ginza (G), Marunouchi (M, including the Hōnanchō
branch), Hibiya (H), Tōzai (T), Chiyoda (C), Yūrakuchō (Y), Hanzōmon (Z),
Namboku (N), Fukutoshin (F). Toei: Asakusa (A), Mita (I), Shinjuku (S),
Ōedo (E).

Decided 2026-10-18 after the counts were in: start with the whole network on
the large board and back-track to Tokyo Metro only if it does not work. The
Metro-only scope stays costed below, and in the builder, as the fallback.

| | Line-stations | Unique stations |
|---|---|---|
| Tokyo Metro (9 lines) | 186 | 144 |
| Toei (4 lines) | 106 | 100 |
| **Both** | **292** | **213** |

The two networks share 31 stations, which is why 144 + 100 is not 213.

Counts are from OSM route relations (`network=東京メトロ` / `都営地下鉄`),
de-duplicated by clustering stop nodes within 200 m. The Toei total matches
Toei's published 106 exactly. Tokyo Metro's published "180 stations" is a
line-station count in which the six stations Wakōshi–Kotake-Mukaihara, shared
by the Yūrakuchō and Fukutoshin lines, are counted once; the raw per-line sum
is 186.

**One LED per unique station**, as Montréal did. Counting once per line would
put several LEDs on the same spot, which the 3.3 mm pitch floor forbids.

Both scopes are variants in the builder, not a choice baked into the data:
the pipeline fetches both networks and tags each station with its lines, so
dropping back to Tokyo Metro only is a configuration change, not a rewrite
(lesson A1 — every style and scope is a variant).

## Lines under construction — both Tokyo Metro extensions are in. +3 LEDs

Same test as Montréal's Blue line extension: the board outlives the
construction timeline. Tokyo Metro's 2025–2027 Mid-term Management Plan says
work on both extensions started in November 2024, each targeting a mid-2030s
opening.

| Extension | Length | New LEDs |
|---|---|---|
| Yūrakuchō, Toyosu–Sumiyoshi (the "Toyosumi line") | 4.8 km | Edagawa and Sengoku (both provisional names). Tōyōchō and Sumiyoshi already have LEDs |
| Namboku, Shirokane-Takanawa–Shinagawa | 2.5 km | Shinagawa. No intermediate station |

Planned-but-not-funded projects stay off the board, including the Ōedo line
extension toward Tokorozawa.

Neither line's new stations exist in OSM as nodes. Their positions are
hand-placed from the published alignments, and each one's source is recorded
in `input/future_stations.json` (lesson A3).

**LED count: 213 + 3 = 216.**

## Style — schematic straight lines with rounded bends, on true-scale natural land

The style the Montréal board settled on after four rounds (lesson A1), and
the one Tokyo suits best: Tokyo Bay, the Sumida and Arakawa rivers and the
Imperial Palace moats give this board more water than either previous city,
and the water is bare ENIG copper, which is the whole visual idea.

Rejected, but kept as variants to compare:

- **The official Tokyo Metro map's look.** Its geometry is its own schematic
  and it draws no coastline, so adopting it means discarding the land.
- **True-geographic routes** (the Vancouver recipe). At this scale the central
  lines read as spaghetti.

The land is fitted to the stations with a **similarity transform only**
(scale, rotation, translation). The land is never warped (lesson A2).

## Board — 400 mm wide at 12.8 mm/km; 400 × 289 mm for the full network

The board takes the frame's aspect rather than being forced square
(lesson B3), so the network scope sets the height:

| Scope | Frame | Aspect | Board at 400 mm wide |
|---|---|---|---|
| Metro only | 31.3 × 17.2 km | 1.82 | 400 × 220 mm |
| **Metro + Toei** | **31.3 × 22.6 km** | **1.38** | **400 × 289 mm** |

400 mm and 12.8 mm/km were the decision; the height follows from including
Toei, whose Ōedo and Mita lines reach further north-west and north.

| Board (Metro + Toei) | mm/km | Stations below the 3.3 mm pitch floor |
|---|---|---|
| 160 × 116 | 5.1 | 91 of 213 |
| 250 × 181 | 8.0 | 40 |
| 300 × 217 | 9.6 | 17 |
| **400 × 289** | **12.8** | **4** |

At 12.8 mm/km only four stations need pitch spreading — the tightest real
pairs are Kyōbashi–Takaracho (214 m), Hibiya–Yūrakuchō (239 m) and
Awajichō–Shin-ochanomizu (274 m) — and the central cluster gets about 4 mm
per 300 m of real distance, which is what makes labels possible at all.

If 289 mm turns out to be too tall to hang or to ship, the alternatives are
cropping the frame (the Tōzai line's eastern tail past Nishi-Funabashi and the
Ōedo line's north-western tail are the candidates) or dropping to 305 × 220 mm
at 9.7 mm/km. Both are cheaper than reducing the station list.

Fab and cost notes to carry into Phase 8:

- Bare-PCB limits are not the constraint: 2-layer FR4 goes to 670 × 600 mm as
  a single board. **SMT assembly is the limit** — published figures range from
  400 × 500 mm to 470 × 500 mm, so 400 × 220 mm is inside it, but confirm in
  JLCPCB's quote tool before paying.
- 0.088 m² with ENIG and 147 placements costs several times a 160 mm board.
- Lesson A11: the cheapest tracked shipping line greys out above its size and
  weight limits. A 400 mm assembled board will need the next tier.

## Labels — English, romanised, no macrons; names not codes

- **No macrons.** KiCad's stroke font has no dependable macron glyph, and
  lesson B6 is that the editor lies about what plots: "Ōtemachi" is written
  "Otemachi".
- **Names, not station codes.** Codes (G-09, five characters, about 2.5 mm at
  1.1 mm text) are the fallback for a station whose name cannot be made to
  fit, not the default.
- **Official spellings with their hyphens**, line-broken at the hyphen, never
  abbreviated (lesson A4).
- Kanji are possible — KiCad 10 plots TrueType — but unreadable at 1.1 mm and
  too large at a legible size. Worth a test as a variant or a back-side
  feature, not on the front.

## Power — a dedicated USB-C power input, with a cuttable terminal-block backup

147 LEDs at 60 mA each is 8.8 A at full white, far past any single USB port,
so brightness is capped in firmware as well.

- **Primary: a USB-C receptacle on the board, separate from the XIAO's own
  USB.** The board's 5 V rail does not come through the controller module.
- **Backup: a 2-pin Phoenix Contact straight-entry terminal block**, joined to
  the same rail by a trace that can be cut to isolate it.
- **Power injection:** taps off the 5 V pour at several points along the
  chain. A 147-LED chain fed from one end browns out at the far end on a
  2-layer board whatever the supply.
- The XIAO's own 5 V pad is separated from the board rail by a cuttable link
  too, so plugging the XIAO in to reprogram it does not parallel two supplies.

## Controller — Seeed XIAO RP2040, hand-soldered, all placed parts on top

Unchanged from Montréal, with three fixes from lessons A8 and A12:

1. The XIAO goes at a **board edge**, so the USB-C cable does not land in the
   middle of the back (Montréal's sits 26 mm in).
2. A **74AHCT1G125 level shifter** on the data line, instead of feeding 3.3 V
   data into 5 V LEDs with only a series resistor.
3. Keep the 330 Ω series resistor and the bulk capacitor at the power entry.

Every part JLCPCB places is on the top side; the XIAO is hand-soldered and
the buttons are do-not-populate pads.

## What to watch, and the back-track plan

216 LEDs is three times Montréal's 73, and the central cluster — Ōtemachi,
Ginza, Nihombashi, Tokyo, Kasumigaseki — is where this board will be decided
(lesson B4). If the labels cannot be made to work there, in order:

1. Crop the frame's tails and raise mm/km.
2. Codes instead of names in the dense core.
3. Drop back to Tokyo Metro only: 147 LEDs on 400 × 220 mm.
