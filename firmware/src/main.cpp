// Tokyo Metro LED map firmware (ported from the Montréal métro board)
// One WS2812B (XL-1615RGBC) per station, 73 LEDs total.
// Index tables are GENERATED from input/montreal-schematic-square.json by
// tools/export_placement.py -> include/firmware_tables.h. Regenerate after
// any layout/chain change; never edit the tables by hand.
//
// Board: any XIAO module on the back (U1, DNP footprint). Pin assignments
// read off the PCB itself, not assumed - XIAO pad -> net:
//   pad 8  = D7 -> LED_IN, straight into LED1 DI (no level shifter on v3)
//   pad 1  = D0 -> BUTTON_01 (SW1)      pad 3 = D2 -> BUTTON_03 (SW3)
//   pad 2  = D1 -> BUTTON_02 (SW2)      pad 4 = D3 -> BUTTON_04 (SW4)
//   pad 13 = GND, pad 14 = 5V (VBUS) -> the LED +5V rail
// The switches are DNP; their pins idle high on the internal pull-ups.
// D7 is GPIO20 on the ESP32-C3 (GPIO1 on the RP2040) - the name is what
// matters, the core maps it to the right GPIO per board.

#include <Arduino.h>
#include "FastLED.h"
#include "firmware_tables.h"

constexpr uint8_t PIN_LED_DATA = D7;
constexpr uint8_t PIN_BTN_MODE = D0;    // SW1
constexpr uint8_t PIN_BTN_BRIGHT = D1;  // SW2
constexpr uint8_t PIN_BTN_SPEED = D2;   // SW3
constexpr uint8_t PIN_BTN_LINE = D3;    // SW4
const uint32_t BAUD_RATE = 115200;
const uint8_t BUILD_NUMBER = 4;

// Bring-up staging. The LED driver is brought up from loop() rather than
// setup() so the heartbeat below starts printing before the RMT driver is
// touched: on a USB-CDC board the boot banner is gone before a monitor can
// attach, so "which stage did it reach" is the only thing you can actually
// read back. 0 = booted, 1 = FastLED up, 2 = chain tested, 3 = animating.
volatile uint8_t stage = 0;
const uint32_t LED_INIT_DELAY_MS = 4000;   // let USB CDC enumerate first

CRGB leds[NUM_LEDS];

uint8_t brightness = 40;
uint16_t stepMs = 700;          // train advance interval
const uint8_t FADE_PER_FRAME = 24;

// 251 LEDs at full white would pull about 15 A. The board has a USB-C
// power input of its own and a terminal block beside it, but the cap stays
// low until the supply and the injection points are proven on a real board.
const uint32_t MAX_MILLIAMPS = 900;

struct Route {
  const int *idx;    // LED index per station along the route
  int count;
  CRGB color;
  int trains;        // simultaneous trains on this route
  int pos[4];        // per-train station cursor (max 4 trains)
  int dir[4];        // +1 / -1
};

// --- generated line table: make_firmware_lines.py ---
// One CRGB per line, in the operator's own colour, and the
// routes[] table the animation walks. Generated - do not edit.
const CRGB COLOR_OEDO = CRGB(0xB6, 0x00, 0x7A);  // Oedo Line, 38 stations
const CRGB COLOR_ARAKAWA = CRGB(0xD8, 0x5B, 0x81);  // Toden Arakawa Line, 30 stations
const CRGB COLOR_YAMANOTE = CRGB(0xB1, 0xCB, 0x39);  // JR Yamanote Line, 30 stations
const CRGB COLOR_MARUNOUCHI = CRGB(0xF6, 0x2E, 0x36);  // Marunouchi Line, 28 stations
const CRGB COLOR_YURAKUCHO = CRGB(0xC1, 0xA4, 0x70);  // Yurakucho Line, 28 stations
const CRGB COLOR_MITA = CRGB(0x00, 0x79, 0xC2);  // Mita Line, 27 stations
const CRGB COLOR_TOZAI = CRGB(0x00, 0x9B, 0xBF);  // Tozai Line, 23 stations
const CRGB COLOR_HIBIYA = CRGB(0xB5, 0xB5, 0xAC);  // Hibiya Line, 22 stations
const CRGB COLOR_SHINJUKU = CRGB(0x6C, 0xBB, 0x5A);  // Shinjuku Line, 21 stations
const CRGB COLOR_ASAKUSA = CRGB(0xE8, 0x52, 0x98);  // Asakusa Line, 20 stations
const CRGB COLOR_CHIYODA = CRGB(0x00, 0xBB, 0x85);  // Chiyoda Line, 20 stations
const CRGB COLOR_NAMBOKU = CRGB(0x00, 0xAC, 0x9B);  // Namboku Line, 20 stations
const CRGB COLOR_GINZA = CRGB(0xFF, 0x95, 0x00);  // Ginza Line, 19 stations
const CRGB COLOR_FUKUTOSHIN = CRGB(0x9C, 0x5E, 0x31);  // Fukutoshin Line, 16 stations
const CRGB COLOR_YURIKAMOME = CRGB(0x16, 0x62, 0xB8);  // Yurikamome, 16 stations
const CRGB COLOR_HANZOMON = CRGB(0x8F, 0x76, 0xD6);  // Hanzomon Line, 14 stations
const CRGB COLOR_RINKAI = CRGB(0x00, 0x38, 0x9E);  // Rinkai Line, 8 stations
const CRGB COLOR_SHINKANSEN = CRGB(0x2E, 0x31, 0x92);  // Shinkansen, 3 stations

Route routes[] = {
  {LINE_OEDO, LINE_OEDO_COUNT, COLOR_OEDO, 3, {0}, {0}},
  {LINE_ARAKAWA, LINE_ARAKAWA_COUNT, COLOR_ARAKAWA, 2, {0}, {0}},
  {LINE_YAMANOTE, LINE_YAMANOTE_COUNT, COLOR_YAMANOTE, 2, {0}, {0}},
  {LINE_MARUNOUCHI, LINE_MARUNOUCHI_COUNT, COLOR_MARUNOUCHI, 2, {0}, {0}},
  {LINE_YURAKUCHO, LINE_YURAKUCHO_COUNT, COLOR_YURAKUCHO, 2, {0}, {0}},
  {LINE_MITA, LINE_MITA_COUNT, COLOR_MITA, 2, {0}, {0}},
  {LINE_TOZAI, LINE_TOZAI_COUNT, COLOR_TOZAI, 2, {0}, {0}},
  {LINE_HIBIYA, LINE_HIBIYA_COUNT, COLOR_HIBIYA, 2, {0}, {0}},
  {LINE_SHINJUKU, LINE_SHINJUKU_COUNT, COLOR_SHINJUKU, 2, {0}, {0}},
  {LINE_ASAKUSA, LINE_ASAKUSA_COUNT, COLOR_ASAKUSA, 2, {0}, {0}},
  {LINE_CHIYODA, LINE_CHIYODA_COUNT, COLOR_CHIYODA, 2, {0}, {0}},
  {LINE_NAMBOKU, LINE_NAMBOKU_COUNT, COLOR_NAMBOKU, 2, {0}, {0}},
  {LINE_GINZA, LINE_GINZA_COUNT, COLOR_GINZA, 2, {0}, {0}},
  {LINE_FUKUTOSHIN, LINE_FUKUTOSHIN_COUNT, COLOR_FUKUTOSHIN, 1, {0}, {0}},
  {LINE_YURIKAMOME, LINE_YURIKAMOME_COUNT, COLOR_YURIKAMOME, 1, {0}, {0}},
  {LINE_HANZOMON, LINE_HANZOMON_COUNT, COLOR_HANZOMON, 1, {0}, {0}},
  {LINE_RINKAI, LINE_RINKAI_COUNT, COLOR_RINKAI, 1, {0}, {0}},
  {LINE_SHINKANSEN, LINE_SHINKANSEN_COUNT, COLOR_SHINKANSEN, 1, {0}, {0}},
};
// --- end generated line table ---

const int ROUTE_COUNT = sizeof(routes) / sizeof(routes[0]);

// Power-on chain check: walk one lit LED from the first to the last, then
// flash every LED once. On a new board this shows at a glance that all 73
// are alive and in chain order - if the walk stops part way, the break is
// at the LED it stopped on.
void chainSelfTest() {
  for (int i = 0; i < NUM_LEDS; i++) {
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    leds[i] = CRGB::White;
    FastLED.show();
    delay(18);
  }
  for (int f = 0; f < 2; f++) {
    fill_solid(leds, NUM_LEDS, CRGB::White);
    FastLED.show();
    delay(120);
    fill_solid(leds, NUM_LEDS, CRGB::Black);
    FastLED.show();
    delay(120);
  }
}

void setup() {
  Serial.begin(BAUD_RATE);
#if defined(ARDUINO_ARCH_ESP32)
  Serial.setTxTimeoutMs(0);   // never block waiting for a USB host to attach
#endif
  Serial.println("SkyTrain map v3 build " + String(BUILD_NUMBER));

  pinMode(PIN_BTN_MODE, INPUT_PULLUP);
  pinMode(PIN_BTN_BRIGHT, INPUT_PULLUP);
  pinMode(PIN_BTN_SPEED, INPUT_PULLUP);
  pinMode(PIN_BTN_LINE, INPUT_PULLUP);
}

void startLeds() {
  FastLED.addLeds<WS2812B, PIN_LED_DATA, GRB>(leds, NUM_LEDS);
  FastLED.setBrightness(brightness);
  // USB powered: hard cap regardless of brightness/animation choices
  FastLED.setMaxPowerInVoltsAndMilliamps(5, MAX_MILLIAMPS);

  for (int r = 0; r < ROUTE_COUNT; r++) {
    for (int t = 0; t < routes[r].trains; t++) {
      routes[r].pos[t] = (routes[r].count * t) / routes[r].trains;
      routes[r].dir[t] = (t % 2 == 0) ? 1 : -1;
    }
  }
}

void advanceTrains() {
  for (int r = 0; r < ROUTE_COUNT; r++) {
    Route &rt = routes[r];
    for (int t = 0; t < rt.trains; t++) {
      rt.pos[t] += rt.dir[t];
      if (rt.pos[t] >= rt.count) {          // bounce at the terminus
        rt.pos[t] = rt.count - 2;
        rt.dir[t] = -1;
      } else if (rt.pos[t] < 0) {
        rt.pos[t] = 1;
        rt.dir[t] = 1;
      }
    }
  }
}

void handleButtons() {
  static uint32_t lastPress = 0;
  if (millis() - lastPress < 250) return;   // debounce
  if (digitalRead(PIN_BTN_BRIGHT) == LOW) {
    brightness = (brightness >= 224) ? 16 : brightness + 32;
    FastLED.setBrightness(brightness);
    lastPress = millis();
  }
  if (digitalRead(PIN_BTN_SPEED) == LOW) {
    stepMs = (stepMs <= 200) ? 1200 : stepMs - 200;
    lastPress = millis();
  }
  // PIN_BTN_MODE / PIN_BTN_LINE reserved for future animation modes
}

void loop() {
  // Heartbeat first, so it reports even if a later stage wedges.
  EVERY_N_MILLISECONDS(2000) {
    Serial.printf("build %u alive %lus stage %u\n",
                  BUILD_NUMBER, millis() / 1000, stage);
  }

  if (stage == 0) {
    if (millis() < LED_INIT_DELAY_MS) return;
    startLeds();
    stage = 1;
    return;
  }
  if (stage == 1) {
    chainSelfTest();
    stage = 2;
    return;
  }
  if (stage == 2) {
    stage = 3;
  }

  handleButtons();

  EVERY_N_MILLISECONDS_I(trainTimer, 700) {
    trainTimer.setPeriod(stepMs);
    advanceTrains();
  }

  // fade trails, then draw trains at full line colour
  fadeToBlackBy(leds, NUM_LEDS, FADE_PER_FRAME);
  for (int r = 0; r < ROUTE_COUNT; r++) {
    Route &rt = routes[r];
    for (int t = 0; t < rt.trains; t++) {
      leds[rt.idx[rt.pos[t]]] = rt.color;
    }
  }
  FastLED.show();
  delay(16);
}
