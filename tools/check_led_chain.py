"""Check the LED chain in a KiCad netlist: every LEDn has +5V and GND, and
LEDn's DO is LEDn+1's DI all the way down.

    kicad-cli sch export netlist --format kicadsexpr -o netlist.net board.kicad_sch
    python check_led_chain.py netlist.net [expected LED count]
"""
import re
import sys

s = open(sys.argv[1], encoding="utf-8").read()
nets = {}
for m in re.finditer(r'\(net\s*\(code "?\d+"?\)\s*\(name "([^"]*)"\)(.*?)(?=\(net\s*\(code|\Z)', s, re.S):
    nets[m[1]] = re.findall(r'\(node\s*\(ref "([^"]+)"\)\s*\(pin "([^"]+)"\)', m[2])
pin = {node: name for name, nodes in nets.items() for node in nodes}
leds = sorted({ref for ref, _ in pin if re.fullmatch(r"LED\d+", ref)}, key=lambda r: int(r[3:]))
errors = []
if len(sys.argv) > 2 and len(leds) != int(sys.argv[2]):
    errors.append(f"{len(leds)} LEDs, expected {sys.argv[2]}")
if [int(l[3:]) for l in leds] != list(range(1, len(leds) + 1)):
    errors.append("LED references are not LED1..LEDn without gaps")
for l in leds:                                   # pins: 1 GND, 2 DI, 3 VDD, 4 DO
    if pin.get((l, "3")) != "+5V" or pin.get((l, "1")) != "GND":
        errors.append(f"{l}: VDD on {pin.get((l, '3'))}, GND on {pin.get((l, '1'))}")
for a, b in zip(leds, leds[1:]):
    if pin.get((a, "4")) != pin.get((b, "2")) or len(nets[pin[(a, "4")]]) != 2:
        errors.append(f"{a} DO ({pin.get((a, '4'))}) does not go only to {b} DI ({pin.get((b, '2'))})")
# The head of the chain, which is what this script used to only PRINT. A
# continuous chain with nothing driving it passes every check above, and
# once did: make_schematic.py deleted LED_DATA and LED_IN off R1's pins and
# put nothing back, leaving GPIO1 dead-ended at its test point, both of
# R1's pads unconnected, and LED1's DI alone on a one-node net. The board
# would have lit not one LED. So walk it: DI -> series resistor -> a
# controller pin, and refuse any single-node net on the way.
din = pin.get((leds[0], "2"))
head = nets.get(din, [])
if len(head) < 2:
    errors.append(f"{leds[0]} DI is on {din} with {len(head)} node(s) - nothing drives the chain")
else:
    res = [r for r, _ in head if re.fullmatch(r"R\d+", r)]
    if not res:
        errors.append(f"{leds[0]} DI net {din} has no series resistor: {head}")
    for r in res:
        far = [nets[n] for (ref, _), n in pin.items() if ref == r and n != din]
        if not far or all(len(nodes) < 2 for nodes in far):
            errors.append(f"{r}'s other pad is unconnected - the data path stops at the resistor")
        elif not any(ref.startswith("U") for nodes in far for ref, _ in nodes):
            errors.append(f"{r} does not reach a controller pin: {far}")
# The rails. Checking that every LED's pin 3 sits on a net NAMED "+5V" is a
# spelling test, not a connectivity test: drop the +5V label off U1's VBUS
# pin the way LED_DATA was dropped off R1 and all 248 LEDs are still on a
# net called +5V, with nothing feeding it. That is the same bug one net
# over, so require each rail to reach the controller.
for rail, want in (("+5V", "source"), ("GND", "return")):
    nodes = nets.get(rail, [])
    if len(nodes) < 2:
        errors.append(f"{rail} has {len(nodes)} node(s) - no rail")
    elif not any(re.fullmatch(r"U\d+", r) for r, _ in nodes):
        errors.append(f"{rail} never reaches the controller - no {want}")

# The decoupling capacitors. This script looked straight past them, so when
# the generator grew from 13 caps to 52 and the power rail was not extended
# to reach the new ones, all 39 sat with both pads on
# unconnected-(ROWn-Pad*) and this still printed PASS. A cap that is not
# across the rails is not a cap.
caps = sorted({r for r, _ in pin if re.fullmatch(r"ROW\d+", r)},
              key=lambda r: int(r[3:]))
for c in caps:
    a, b = pin.get((c, "1")), pin.get((c, "2"))
    if {a, b} != {"GND", "+5V"}:
        errors.append(f"{c} is not across the rails: pad 1 on {a}, pad 2 on {b}")

# The far end, which was also only printed. LED_OUT carrying nothing is not
# fatal the way a dead head is, but a chain whose tail went missing means
# the generator dropped a label again.
dout = pin.get((leds[-1], "4"))
tail = nets.get(dout, [])
if len(tail) < 2:
    errors.append(f"{leds[-1]} DO is on {dout} with {len(tail)} node(s) - the chain output goes nowhere")

print(f"{len(leds)} LEDs; data in: {pin[(leds[0], '2')]} {nets[pin[(leds[0], '2')]]}")
print(f"data out: {pin[(leds[-1], '4')]} {nets[pin[(leds[-1], '4')]]}")
print(f"rails: +5V {len(nets.get('+5V', []))} nodes, GND {len(nets.get('GND', []))} nodes")
print(f"decoupling: {len(caps)} capacitor(s), all across the rails")
if errors:
    print(f"FAIL: {len(errors)} problem(s)")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("PASS: chain is continuous and every LED is powered")
