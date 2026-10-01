#!/usr/bin/env bash
# List new upstream commits that touch the source file of a council we serve.
#
# The council modules in api/councils/ started as ports of two community
# projects. Upstream still fixes those scrapers when a council changes its
# site, so a commit there is a hint to check our module.
#
#   scripts/upstream_watch.sh                     # since the last check
#   scripts/upstream_watch.sh --since 2026-09-01  # since a date
#   scripts/upstream_watch.sh --hook              # pre-commit: see below
#
# Mapping: api/councils/_aliases.json maps each old scraper ID to a LAD, and
# api/data/lad_lookup.json maps the LAD to its module. Old IDs name the
# upstream file:
#   hacs_<x>               source/<x>.py              mampfes/hacs_waste_collection_schedule
#   hacs_itv_*             source/iapp_itouchvision_com.py
#   ukbcd_<x>, port_<x>    councils/<CamelCase x>.py  robbrad/UKBinCollectionData
#
# State: scripts/upstream_watch.json (gitignored, per checkout) holds the time
# of the last successful check. A run reports commits after it, then moves it
# to now.
#
# --hook (lefthook pre-commit) never blocks a commit: it checks at most once a
# day, gives up after ~20s, stays silent when gh or python3 is missing or the
# network is down, always exits 0.

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$ROOT/scripts/upstream_watch.json"
HOOK=0
SINCE=""
CALL_TIMEOUT=5   # seconds per gh call
BUDGET=20        # seconds for the whole check in --hook mode

while [ $# -gt 0 ]; do
  case "$1" in
    --hook) HOOK=1 ;;
    --since) SINCE="$2"; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "upstream_watch: unknown option $1" >&2; exit 2 ;;
  esac
  shift
done

quit() {  # in --hook mode every exit is a clean one
  if [ "$HOOK" = 1 ]; then exit 0; fi
  exit "${1:-1}"
}

command -v gh >/dev/null 2>&1 || { [ "$HOOK" = 1 ] || echo "upstream_watch: gh not installed" >&2; quit 1; }
command -v python3 >/dev/null 2>&1 || { [ "$HOOK" = 1 ] || echo "upstream_watch: python3 not found" >&2; quit 1; }

# gh with a hard time limit (perl's alarm survives exec; no coreutils timeout on macOS)
ghc() { perl -e 'alarm shift @ARGV; exec @ARGV' "$CALL_TIMEOUT" gh "$@" 2>/dev/null; }

NOW="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LAST="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("checked_at",""))' "$STATE" 2>/dev/null || true)"

if [ "$HOOK" = 1 ] && [ -n "$LAST" ]; then
  # At most once a day
  python3 - "$LAST" <<'PY' || exit 0
import sys
from datetime import UTC, datetime, timedelta
last = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
sys.exit(0 if datetime.now(UTC) - last >= timedelta(hours=24) else 1)
PY
fi

SINCE="${SINCE:-${LAST:-$NOW}}"

# upstream path <TAB> repo <TAB> "module (LAD)", one line per old ID that maps to a file
TABLE="$(python3 - "$ROOT" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
aliases = json.loads((root / "api/councils/_aliases.json").read_text())
lad_lookup = json.loads((root / "api/data/lad_lookup.json").read_text())
HACS = ("mampfes/hacs_waste_collection_schedule", "custom_components/waste_collection_schedule/waste_collection_schedule/source/")
UKBCD = ("robbrad/UKBinCollectionData", "uk_bin_collection/uk_bin_collection/councils/")
for old, lad in sorted(aliases.items()):
    module = (lad_lookup.get(lad) or {}).get("scraper_id")
    if not module:
        continue
    if old.startswith("hacs_itv_"):
        repo, path = HACS[0], HACS[1] + "iapp_itouchvision_com.py"
    elif old.startswith("hacs_"):
        repo, path = HACS[0], HACS[1] + old.removeprefix("hacs_") + ".py"
    elif old.startswith(("ukbcd_", "port_")):
        camel = "".join(w[:1].upper() + w[1:] for w in old.split("_", 1)[1].split("_"))
        repo, path = UKBCD[0], UKBCD[1] + camel + ".py"
    else:
        continue  # a recoded LAD code, not a scraper
    print(f"{path}\t{repo}\t{module} ({lad})")
PY
)" || quit 1

# Offline, or gh not logged in: say nothing in --hook mode
ghc api rate_limit --jq .rate.remaining >/dev/null || { [ "$HOOK" = 1 ] || echo "upstream_watch: GitHub API unreachable" >&2; quit 1; }

# sha <TAB> changed file, for each commit sha on stdin; "sha <TAB> !" when a call fails
export CALL_TIMEOUT
commit_files() {
  xargs -P 8 -I{} bash -c '
    out="$(perl -e "alarm shift @ARGV; exec @ARGV" "$CALL_TIMEOUT" gh api "repos/$0/commits/$1" --jq ".files[].filename" 2>/dev/null)" \
      || { printf "%s\t!\n" "$1"; exit 0; }
    printf "%s\n" "$out" | sed "s|^|$1	|"' "$1" {}
}

FOUND=""
for spec in \
  "mampfes/hacs_waste_collection_schedule custom_components/waste_collection_schedule/waste_collection_schedule/source" \
  "robbrad/UKBinCollectionData uk_bin_collection/uk_bin_collection/councils"; do
  read -r repo dir <<<"$spec"
  commits="$(ghc api -X GET "repos/$repo/commits" -f since="$SINCE" -f path="$dir" -f per_page=100 \
    --jq '.[] | [.sha, .commit.committer.date[:10], (.commit.message | split("\n")[0])] | @tsv')" || quit 1
  [ -n "$commits" ] || continue
  n="$(printf '%s\n' "$commits" | wc -l | tr -d ' ')"
  if [ "$HOOK" = 1 ] && [ "$n" -gt 30 ]; then
    # Too many to look through inside a commit; leave the state for a manual run
    echo "upstream_watch: $n upstream commits in $repo since $SINCE; run scripts/upstream_watch.sh to see which touch our councils"
    exit 0
  fi
  files="$(printf '%s\n' "$commits" | cut -f1 | commit_files "$repo")"
  if printf '%s\n' "$files" | grep -q $'\t!$'; then quit 1; fi
  if [ "$HOOK" = 1 ] && [ "$SECONDS" -ge "$BUDGET" ]; then exit 0; fi
  while IFS=$'\t' read -r sha day subject; do
    while IFS=$'\t' read -r _ f; do
      hits="$(printf '%s\n' "$TABLE" | awk -F'\t' -v f="$f" -v r="$repo" '$1 == f && $2 == r {print $3}' | sort -u | paste -sd, - | sed 's/,/, /g')"
      [ -n "$hits" ] || continue
      FOUND+="  $hits: ${f##*/}"$'\n'"    $day ${sha:0:7} $subject"$'\n'"    https://github.com/$repo/commit/$sha"$'\n'
    done < <(printf '%s\n' "$files" | awk -F'\t' -v s="$sha" '$1 == s')
  done <<<"$commits"
done

if [ -n "$FOUND" ]; then
  echo "upstream_watch: upstream changed councils we serve (since $SINCE):"
  printf '%s' "$FOUND"
  echo "  Check whether our module needs the same fix."
elif [ "$HOOK" = 0 ]; then
  echo "upstream_watch: nothing new upstream for councils we serve since $SINCE"
fi

printf '{\n  "checked_at": "%s"\n}\n' "$NOW" >"$STATE"
exit 0
