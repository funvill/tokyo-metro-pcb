"""Put the frozen LED chain back into the board file after a rebuild.

    python -X utf8 apply_chain.py tokyo.json chain.json

The chain is a permutation of the board's station set, so it can only go on
after the crop - handing it to build_tokyo.py would have it rejected for
being 248 long against the 251 stations of the uncropped layout. It refuses
to apply a chain that does not match, and says which stations differ, rather
than writing a chain with a hole in it.
"""
import io
import json
import sys


def main():
    board, chain_file = sys.argv[1], sys.argv[2]
    with io.open(board, encoding="utf-8") as f:
        d = json.load(f)
    with io.open(chain_file, encoding="utf-8") as f:
        chain = json.load(f)
    if sorted(chain) != sorted(d["stations"]):
        missing = sorted(set(d["stations"]) - set(chain))
        extra = sorted(set(chain) - set(d["stations"]))
        print(f"  WARNING: {chain_file} does not match the board: "
              f"{len(missing)} station(s) not in the chain {missing[:5]}, "
              f"{len(extra)} in the chain but not on the board {extra[:5]}")
        print("  re-run build_chain.py; the chain was NOT applied")
        return 1
    d["chain"] = chain
    with io.open(board, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
    print(f"chain re-applied: {len(chain)} LEDs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
