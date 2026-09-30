#!/usr/bin/env bash
#
# Fetch the four upstream sources behind the postcode → council mapping, only
# when upstream has actually published something new.
#
#   ONSPD   ONS Postcode Directory     → pipeline/data/onspd_postcode_lad.parquet
#   ONSUD   ONS UPRN Directory         → pipeline/data/onsud_uprn_postcode.parquet
#   LAD BUC ONS LAD boundaries         → council names + api/static/coverage.geojson
#   GOV.UK  Local Links Manager CSV    → per-council household-waste URLs
#
# Downloads land in a cache directory ($BINS_DATA_CACHE, default
# ~/.cache/bins-data) that CI is expected to key on the version stamps written
# here. The two derived parquets are committed (15MB + 88MB), so a normal
# checkout, test run or deploy needs none of this — it only runs when ONS cuts a
# new edition.
#
# Freshness tracking differs per source, because the hosts do:
#
#   * ONSPD/ONSUD are ArcGIS Online items whose /data endpoint 302s to a
#     single-use presigned S3 URL. That redirect carries no ETag and ignores
#     If-Modified-Since, so `curl -z` is useless here. Instead we read the AGOL
#     item's `modified` timestamp from its ?f=json metadata and compare it to a
#     stored stamp. A NEW item id is minted every edition, so the id cannot be
#     pinned either — the latest item is discovered by title search.
#   * The GOV.UK CSV and the boundary query are small and do honour HTTP
#     validators, so those use ETag + If-Modified-Since conditional GETs.
#
# Usage:
#   scripts/lookup/fetch_latest.sh              # fetch whatever is stale
#   scripts/lookup/fetch_latest.sh --check      # report staleness, download nothing
#   scripts/lookup/fetch_latest.sh --small-only # skip the multi-hundred-MB zips
#
# After a fetch that changed ONSPD, or after the small sources change, rebuild
# the mapping:  uv run python -m scripts.lookup.build_lad_lookup
set -euo pipefail

CACHE="${BINS_DATA_CACHE:-$HOME/.cache/bins-data}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

GOVUK_CSV_URL="https://govuk-app-assets-production.s3.eu-west-1.amazonaws.com/data/local-links-manager/links_to_services_provided_by_local_authorities.csv"
# LAD_MAY_2025_UK_BUC: BUC = British Ultra Coarse, the generalised boundary set.
# Names feed lad_base.json; the geometry feeds the coverage map. Kept in step
# with scripts/coverage/generate_coverage_map.py.
BOUNDARY_SERVICE="https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/LAD_MAY_2025_UK_BUC/FeatureServer/0/query"
BOUNDARY_NAMES_URL="${BOUNDARY_SERVICE}?outFields=*&where=1%3D1&returnGeometry=false&f=json"
BOUNDARY_GEOJSON_URL="${BOUNDARY_SERVICE}?outFields=*&where=1%3D1&f=geojson"

AGOL_SEARCH="https://www.arcgis.com/sharing/rest/search"
AGOL_ITEM="https://www.arcgis.com/sharing/rest/content/items"

CHECK_ONLY=0
SMALL_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --check) CHECK_ONLY=1 ;;
    --small-only) SMALL_ONLY=1 ;;
    -h|--help) sed -n '2,40p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$CACHE"

# Logs go to stderr so a function's stdout can carry a return value.
log() { printf '==> %s\n' "$*" >&2; }

# --- small sources: conditional GET on ETag + Last-Modified -----------------

fetch_conditional() {
  local url="$1" dest="$2" label="$3"
  local etag="$dest.etag"
  local -a cond=()
  # Only pass validators we actually hold, so a cold cache is a plain GET.
  # The ${cond[@]+...} guard keeps an empty array from tripping `set -u` on
  # bash 3.2 (what macOS ships).
  [[ -f "$dest" ]] && cond+=(--time-cond "$dest")
  [[ -f "$etag" ]] && cond+=(--etag-compare "$etag")

  if [[ $CHECK_ONLY -eq 1 ]]; then
    local code
    code=$(curl -sS -o /dev/null -w '%{http_code}' \
      ${cond[@]+"${cond[@]}"} "$url" || true)
    if [[ "$code" == "304" ]]; then
      log "$label: up to date (304)"
    else
      log "$label: would fetch (HTTP $code)"
    fi
    return 0
  fi

  local before=""
  [[ -f "$dest" ]] && before=$(shasum -a 256 "$dest" | cut -d' ' -f1)

  curl -sSL --fail --retry 3 --retry-delay 2 \
    ${cond[@]+"${cond[@]}"} --etag-save "$etag" -o "$dest" "$url"

  local after=""
  [[ -f "$dest" ]] && after=$(shasum -a 256 "$dest" | cut -d' ' -f1)
  if [[ "$before" == "$after" ]]; then
    log "$label: unchanged"
  else
    log "$label: updated ($(wc -c <"$dest" | tr -d ' ') bytes)"
  fi
}

# --- ONSPD / ONSUD: AGOL item discovery + modified-timestamp stamping -------

# Latest AGOL item for a product, as "<id> <modified> <name>".
#
# A new item id is minted per edition, so the id can't be pinned — search by
# title and take the newest. Titles are not a safe filter (the "for the UK"
# suffix comes and goes between editions, and the "User Guide" sibling shares
# the product title and item type). The download filename is stable, so match on
# that: ONSPD_AUG_2026.zip is data, ONSPD_User_Guide_August_2026.zip is not.
agol_latest_item() {
  local title="$1" name_pattern="$2"
  curl -sS --fail --retry 3 --get "$AGOL_SEARCH" \
    --data-urlencode "q=title:\"$title\"" \
    --data "f=json&num=50&sortField=created&sortOrder=desc" |
    uv run --project "$REPO_ROOT" python -c '
import json, re, sys
title, name_pattern = sys.argv[1], sys.argv[2]
pattern = re.compile(name_pattern)
items = json.load(sys.stdin).get("results", [])
matches = [i for i in items if i.get("name") and pattern.fullmatch(i["name"])]
if not matches:
    sys.exit(f"no {title} data item matching {name_pattern} in AGOL search results")
best = max(matches, key=lambda i: i["created"])
print(best["id"], best["modified"], best["name"])
' "$title" "$name_pattern"
}

fetch_agol_zip() {
  local title="$1" name_pattern="$2" dir="$3" label="$4"
  mkdir -p "$dir"
  local stamp="$dir/.upstream_version"

  local latest
  latest=$(agol_latest_item "$title" "$name_pattern")
  local current=""
  [[ -f "$stamp" ]] && current=$(cat "$stamp")

  if [[ "$latest" == "$current" ]]; then
    log "$label: up to date ($(cut -d' ' -f3- <<<"$latest"))"
    return 0
  fi

  log "$label: new edition upstream"
  log "  have: ${current:-<nothing cached>}"
  log "  want: $latest"
  if [[ $CHECK_ONLY -eq 1 || $SMALL_ONLY -eq 1 ]]; then
    log "  skipped (--check/--small-only)"
    return 0
  fi

  local id name zip
  id=$(cut -d' ' -f1 <<<"$latest")
  name=$(cut -d' ' -f3- <<<"$latest")
  zip="$dir/$name"

  # The zip is served whole; there is no server-side way to fetch only
  # Data/multi_csv, so this is a few hundred MB per edition (the item
  # description's "2.31 GB" refers to the uncompressed single-CSV product).
  log "  downloading $AGOL_ITEM/$id/data -> $zip"
  curl -SL --fail --retry 3 --retry-delay 5 -o "$zip" "$AGOL_ITEM/$id/data"

  local extract="$dir/${name%.zip}"
  rm -rf "$extract"
  # Only the per-area/region CSVs are needed; skip the 1.5GB single national
  # CSV and the User Guide. Documents/ carries the LAD name/code lookup.
  unzip -qo "$zip" -d "$extract" \
    'Data/multi_csv/*.csv' 'Data/ONSUD_*.csv' 'Documents/LAD*names and codes*.csv' \
    || unzip -qo "$zip" -d "$extract"

  printf '%s' "$latest" >"$stamp"
  log "  extracted to $extract"
  # Stdout: the extracted directory, meaning "this parquet needs rebuilding".
  printf '%s' "$extract"
}

# --- run -------------------------------------------------------------------

log "cache: $CACHE"

fetch_conditional "$GOVUK_CSV_URL" "$CACHE/local_links_manager.csv" "GOV.UK Local Links Manager"
fetch_conditional "$BOUNDARY_NAMES_URL" "$CACHE/lad_names.json" "ONS LAD names"
fetch_conditional "$BOUNDARY_GEOJSON_URL" "$CACHE/lad_boundaries.geojson" "ONS LAD boundaries"

onspd_dir=$(fetch_agol_zip "ONS Postcode Directory" \
  'ONSPD_[A-Z]{3}_[0-9]{4}\.zip' "$CACHE/onspd" "ONSPD")
onsud_dir=$(fetch_agol_zip "ONS UPRN Directory" \
  'ONSUD_[A-Z]{3}_[0-9]{4}\.zip' "$CACHE/onsud" "ONSUD")

# Rebuild a parquet only when its source edition actually changed. The edition
# string is stamped into the parquet's key-value metadata so the committed
# artifact always says which ONS edition it came from
# (`SELECT * FROM parquet_kv_metadata('...')`).
if [[ -d "${onspd_dir:-}" ]]; then
  log "rebuilding onspd_postcode_lad.parquet from $(basename "$onspd_dir")"
  uv run --project "$REPO_ROOT" python -m scripts.lookup.create_lookup_table \
    --from-onspd "$onspd_dir" --edition "$(basename "$onspd_dir")"
fi
if [[ -d "${onsud_dir:-}" ]]; then
  log "rebuilding onsud_uprn_postcode.parquet from $(basename "$onsud_dir")"
  uv run --project "$REPO_ROOT" python -m scripts.lookup.create_lookup_table \
    --from-onsud "$onsud_dir" --edition "$(basename "$onsud_dir")"
fi

cat <<'EOF'

Next:
  uv run python -m scripts.lookup.build_lad_lookup   # rebuild lad_base + lad_lookup
  uv run pytest -m ci
EOF
