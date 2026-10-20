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
print(f"{len(leds)} LEDs; data in: {pin[(leds[0], '2')]} {nets[pin[(leds[0], '2')]]}")
print(f"data out: {pin[(leds[-1], '4')]} {nets[pin[(leds[-1], '4')]]}")
if errors:
    print(f"FAIL: {len(errors)} problem(s)")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("PASS: chain is continuous and every LED is powered")
