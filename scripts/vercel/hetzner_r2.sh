#!/usr/bin/env bash
# Copy the Hetzner ICS cache into R2, then switch the Hetzner stack onto R2. Run from your
# machine; it drives the box over SSH. Serves VERCEL.md phase 1.
#
#   scripts/vercel/hetzner_r2.sh /tmp/vercel.env --dry-run   # show what the sync would copy
#   scripts/vercel/hetzner_r2.sh /tmp/vercel.env             # sync, set R2_* in .env, restart
#   scripts/vercel/hetzner_r2.sh /tmp/vercel.env --sync-only # sync again, touch nothing else
#
# Reads R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET from the env file
# (scripts/vercel/cf_setup.sh writes them). rclone runs in a throwaway rclone/rclone
# container on the box with the bins_data volume mounted read-only, so nothing is
# installed there; credentials go over SSH stdin into a 0600 file that is deleted after.
# `rclone copy --update` never deletes and never overwrites a newer object, so it is safe
# while Vercel (a preview, the probe) also writes to the bucket. Once Hetzner runs on R2
# (this script's last step) the box's own directory goes stale; copying again is harmless.
# Env: HETZNER_HOST (default deploy@ukbinday.co.uk, which only reaches the box before the
# DNS cutover), HETZNER_DIR (default /home/deploy/bins, as in deploy.yml), BINS_VOLUME
# (default: the volume whose name ends in bins_data).
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: $0 <env-file> [--dry-run|--sync-only]" >&2; exit 2; }
FILE="$1"; MODE="${2:-}"
case "$MODE" in ''|--dry-run|--sync-only) ;; *) echo "hetzner_r2: unknown flag $MODE" >&2; exit 2 ;; esac
[ -f "$FILE" ] || { echo "hetzner_r2: $FILE not found" >&2; exit 2; }
HOST="${HETZNER_HOST:-deploy@ukbinday.co.uk}"
DIR="${HETZNER_DIR:-/home/deploy/bins}"

get() { grep -E "^$1=" "$FILE" | tail -n 1 | cut -d= -f2-; }
for k in R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET; do
  [ -n "$(get "$k")" ] || { echo "hetzner_r2: $k missing from $FILE" >&2; exit 2; }
done

R2_ENV="$(cat <<EOF
R2_ACCOUNT_ID=$(get R2_ACCOUNT_ID)
R2_ACCESS_KEY_ID=$(get R2_ACCESS_KEY_ID)
R2_SECRET_ACCESS_KEY=$(get R2_SECRET_ACCESS_KEY)
R2_BUCKET=$(get R2_BUCKET)
EOF
)"
RCLONE_ENV="$(cat <<EOF
RCLONE_CONFIG_R2_TYPE=s3
RCLONE_CONFIG_R2_PROVIDER=Cloudflare
RCLONE_CONFIG_R2_ACCESS_KEY_ID=$(get R2_ACCESS_KEY_ID)
RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=$(get R2_SECRET_ACCESS_KEY)
RCLONE_CONFIG_R2_ENDPOINT=https://$(get R2_ACCOUNT_ID).r2.cloudflarestorage.com
RCLONE_CONFIG_R2_NO_CHECK_BUCKET=true
EOF
)"

echo "hetzner_r2: $HOST:$DIR ${MODE:-(full)}" >&2
ssh "$HOST" bash -s -- "$(printf %q "$DIR")" "$(printf %q "$(get R2_BUCKET)")" "$(printf %q "$MODE")" "$(printf %q "${BINS_VOLUME:-}")" <<REMOTE
set -euo pipefail
DIR=\$1; BUCKET=\$2; MODE=\$3; VOLUME=\$4
[ -n "\$VOLUME" ] || VOLUME=\$(docker volume ls -q | grep -E '(^|_)bins_data\$' | head -n 1)
[ -n "\$VOLUME" ] || { echo "hetzner_r2: no bins_data volume on the box" >&2; exit 1; }
ENVF=\$(mktemp); chmod 600 "\$ENVF"; trap 'rm -f "\$ENVF"' EXIT
cat > "\$ENVF" <<'CREDS'
$RCLONE_ENV
CREDS
rc() { docker run --rm --env-file "\$ENVF" -v "\$VOLUME:/data:ro" rclone/rclone "\$@"; }
echo "volume \$VOLUME -> r2:\$BUCKET/calendars"
echo "local:  \$(rc size /data/calendars | tr '\n' ' ')"
echo "bucket: \$(rc size "r2:\$BUCKET/calendars" 2>/dev/null | tr '\n' ' ' || true)"
if [ "\$MODE" = --dry-run ]; then
  rc copy /data/calendars "r2:\$BUCKET/calendars" --update --dry-run --stats-one-line
  exit 0
fi
rc copy /data/calendars "r2:\$BUCKET/calendars" --update --transfers 16 --stats-one-line -v
echo "bucket: \$(rc size "r2:\$BUCKET/calendars" | tr '\n' ' ')"
[ "\$MODE" = --sync-only ] && exit 0

cd "\$DIR"
grep -v '^R2_' .env > .env.tmp 2>/dev/null || true
cat >> .env.tmp <<'R2'
$R2_ENV
R2
chmod 600 .env.tmp; mv .env.tmp .env
docker compose up -d api worker
sleep 5
curl -fsS -o /dev/null -w 'status after restart: %{http_code}\n' http://localhost:8000/api/v1/status || echo "status check failed: look at docker compose logs api" >&2
REMOTE
