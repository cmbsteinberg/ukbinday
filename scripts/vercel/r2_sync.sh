#!/usr/bin/env bash
# Copy the Hetzner ICS cache into the R2 bucket. Run ON the Hetzner box.
# Serves VERCEL.md phase 1 (ICS cache to R2). Safe to re-run; use it again right before cutover.
#
#   R2_BUCKET=bins scripts/vercel/r2_sync.sh --dry-run    # see what would change
#   R2_BUCKET=bins scripts/vercel/r2_sync.sh
#
# One-off rclone remote (~/.config/rclone/rclone.conf, or `rclone config`); create an R2
# API token with Object Read & Write on the bucket:
#   [r2]
#   type = s3
#   provider = Cloudflare
#   access_key_id = <R2_ACCESS_KEY_ID>
#   secret_access_key = <R2_SECRET_ACCESS_KEY>
#   endpoint = https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
#   acl = private
#
# Env: R2_BUCKET (required), RCLONE_REMOTE (default r2), CALENDARS_DIR
# (default /var/lib/docker/volumes/bins_data/_data/calendars).
# `sync` makes the bucket's calendars/ match the box, deleting extra objects there, which is
# right while Hetzner is the only writer. Once Vercel serves traffic, do not run it any more:
# the bucket then holds newer data than the box.
# Any extra arguments (e.g. --dry-run, -v) go to rclone sync.
set -euo pipefail

: "${R2_BUCKET:?set R2_BUCKET}"
REMOTE="${RCLONE_REMOTE:-r2}"
SRC="${CALENDARS_DIR:-/var/lib/docker/volumes/bins_data/_data/calendars}"
DEST="$REMOTE:$R2_BUCKET/calendars"

command -v rclone >/dev/null || { echo "r2_sync: rclone not installed (apt install rclone)" >&2; exit 1; }
[ -d "$SRC" ] || { echo "r2_sync: $SRC not found (run on the Hetzner box, or set CALENDARS_DIR)" >&2; exit 1; }

echo "r2_sync: $SRC -> $DEST"
echo "r2_sync: before"; echo "  local:  $(rclone size "$SRC" | tr '\n' ' ')"
echo "  bucket: $(rclone size "$DEST" 2>/dev/null | tr '\n' ' ' || true)"

rclone sync "$SRC" "$DEST" --transfers 16 --stats-one-line -v "$@"

echo "r2_sync: after"; echo "  local:  $(rclone size "$SRC" | tr '\n' ' ')"
echo "  bucket: $(rclone size "$DEST" | tr '\n' ' ')"
