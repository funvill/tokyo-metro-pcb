#!/bin/bash
# Fetch the Overpass data this project is built from and cache the raw
# responses in input/osm/, so every later build runs offline and
# reproducibly (lesson A3 / B7).
#
#   ./fetch_osm.sh                 # fetch anything missing
#   ./fetch_osm.sh --force         # re-fetch everything
#   ./fetch_osm.sh routes water    # named queries only
#
# One query per file in queries/*.ql, sent with --data-urlencode "data@FILE".
# The queries must come from files: Git Bash mangles the Japanese tag values
# (東京メトロ, 都営地下鉄) of an inline query on the way to curl, and Overpass
# rejects the regular expression with "static error: Invalid regular
# expression".
#
# Overpass returns 429/500/502 under load, so every query is retried across
# mirrors with exponential backoff (lesson A3).
set -uo pipefail
cd "$(dirname "$0")"
mkdir -p osm

MIRRORS="https://overpass-api.de/api/interpreter https://overpass.private.coffee/api/interpreter https://overpass.osm.jp/api/interpreter"

FORCE=""
if [ "${1:-}" = "--force" ]; then FORCE=1; shift; fi

WANT="$*"
[ -z "$WANT" ] && WANT=$(ls queries/*.ql | sed 's#queries/##; s#\.ql$##' | tr '\n' ' ')

fail=0
for name in $WANT; do
    ql="queries/$name.ql"
    out="osm/$name.json"
    if [ ! -f "$ql" ]; then echo "  $name: no $ql"; fail=1; continue; fi
    if [ -s "$out" ] && [ -z "$FORCE" ]; then
        echo "  $name: cached ($(wc -c < "$out") bytes)"
        continue
    fi
    wait=3; got=""
    for attempt in 1 2 3 4 5 6; do
        for m in $MIRRORS; do
            curl -s -A "tokyo-metro-pcb/1.0" --max-time 600 "$m" \
                --data-urlencode "data@$ql" -o "$out.tmp" 2>/dev/null
            if head -c 1 "$out.tmp" 2>/dev/null | grep -q '{'; then
                mv "$out.tmp" "$out"
                echo "  $name: $(wc -c < "$out") bytes from $m"
                got=1; break
            fi
        done
        [ -n "$got" ] && break
        echo "  $name: attempt $attempt failed, waiting ${wait}s"
        sleep $wait; wait=$((wait * 2))
    done
    if [ -z "$got" ]; then
        echo "  $name: FAILED"
        grep -oE "Error</strong>[^<]*|static error[^<]*" "$out.tmp" 2>/dev/null | head -2
        rm -f "$out.tmp"; fail=1
    fi
done

echo "Raw responses are in osm/ and are committed with the repo."
exit $fail
