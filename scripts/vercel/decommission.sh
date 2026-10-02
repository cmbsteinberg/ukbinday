#!/usr/bin/env bash
# Retire the Hetzner stack once production has been on Vercel for a while.
# Serves VERCEL.md phase 6 (decommission). Run it ~2 weeks after the DNS cutover.
#
#   scripts/vercel/decommission.sh --dry-run                 # print every command, change nothing
#   scripts/vercel/decommission.sh                           # preflight, then the three stages
#   scripts/vercel/decommission.sh --skip-hetzner --skip-secrets   # only the repo edits
#
# Flags:
#   --dry-run        print the commands (and a diff of the file edits) instead of running them;
#                    the preflight checks still run, they only read
#   --force          carry on when a preflight check fails (the failure is still reported)
#   --skip-hetzner / --skip-secrets / --skip-repo     leave that stage out
# Env:
#   BASE_URL         production base URL (default https://ukbinday.co.uk)
#   HCLOUD_SERVER    server to delete (default: asked for, after the server list is shown;
#                    scripts/deploy/deployment.py named it bins-api)
#   HCLOUD_FIREWALL / HCLOUD_SSH_KEY    the other two things deployment.py created
#                    (defaults bins-firewall / bins-deploy)
#   HCLOUD_TOKEN     for hcloud, unless a context is set (`hcloud context create bins`)
#
# Preflight (abort on any failure unless --force):
#   1. $BASE_URL/api/v2/status answers 200 and the response came from Vercel. Cloudflare
#      passes origin headers through but rewrites `server:` to cloudflare, so the check is
#      an x-vercel-id header (or x-vercel-cache, or `server: Vercel` when not proxied).
#      Hetzner's Caddy sends none of them.
#   2. $BASE_URL/api/v2/metrics .ics_cache.last_refresh_age_seconds is a number under 36 h
#      (the oldest shard's last run, so the Vercel cron is really refreshing).
#   3. git working tree clean (only when the repo stage runs), so the edits are a diff.
#
# Stages, each behind a typed confirmation (anything else skips that stage):
#   1. Hetzner: hcloud server delete (type the server name), then the firewall and SSH
#      key deployment.py made (type each name). Lists volumes, IPs, snapshots, never
#      deletes those.
#   2. GitHub secrets: gh secret delete SERVER_HOST, SSH_PRIVATE_KEY (type owner/repo).
#   3. Repo (type "yes"): git rm Caddyfile goaccess.conf scripts/deploy/; trim
#      docker-compose.yml to the api service (PyYAML rewrites it, so comments go);
#      drop the SSH `deploy` job from deploy.yml (text edit, comments kept); uv remove
#      --dev hcloud paramiko; small test edits. Nothing is committed.
#
# Needs: curl, jq, git always; hcloud (stage 1), gh (stage 2), uv (stage 3; PyYAML comes
# from python3 if installed, else `uv run --no-project --with pyyaml`). yq is not used.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

BASE="${BASE_URL:-https://ukbinday.co.uk}"
BASE="${BASE%/}"
API="$BASE/api/v2"
MAX_AGE=$((36 * 3600))
FW_NAME="${HCLOUD_FIREWALL:-bins-firewall}"
KEY_NAME="${HCLOUD_SSH_KEY:-bins-deploy}"
WORKFLOW=".github/workflows/deploy.yml"

DRY=0 FORCE=0 SKIP_HETZNER=0 SKIP_SECRETS=0 SKIP_REPO=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --force) FORCE=1 ;;
    --skip-hetzner) SKIP_HETZNER=1 ;;
    --skip-secrets) SKIP_SECRETS=1 ;;
    --skip-repo) SKIP_REPO=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "usage: $0 [--dry-run] [--force] [--skip-hetzner] [--skip-secrets] [--skip-repo]" >&2; exit 2 ;;
  esac
  shift
done

SUMMARY=""
note() { SUMMARY="${SUMMARY}  - $*"$'\n'; }
say() { printf '%s\n' "$*" >&2; }
hr() { printf '\n== %s ==\n' "$*" >&2; }
die() { say "decommission: $*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Print a command; run it unless --dry-run.
run() {
  printf '+ %s\n' "$*" >&2
  [ "$DRY" = 1 ] || "$@"
}

# Ask for an exact string. Under --dry-run only says what would be asked.
# Returns 1 (stage skipped) on anything else, including EOF.
confirm_typed() {
  local expected="$1" reply
  if [ "$DRY" = 1 ]; then say "[dry-run] would require typing: $expected"; return 0; fi
  printf 'Type "%s" to continue (anything else skips): ' "$expected" >&2
  IFS= read -r reply || reply=""
  [ "$reply" = "$expected" ]
}

for tool in curl jq git; do have "$tool" || die "$tool not installed"; done

# --- preflight ------------------------------------------------------------------------
PRE_FAILS=0
pre_pass() { say "PASS  $*"; }
pre_fail() {
  if [ "$FORCE" = 1 ]; then say "FAIL  $* (ignored: --force)"; else say "FAIL  $*"; fi
  PRE_FAILS=$((PRE_FAILS + 1))
}

hr "Preflight ($BASE)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

code="$(curl -sS --max-time 30 -o "$TMP/status" -D "$TMP/status.h" -w '%{http_code}' "$API/status" 2>"$TMP/err")" || code="000"
if [ "$code" = 200 ]; then
  pre_pass "/status answers 200"
else
  pre_fail "/status answered $code $(tr -d '\r' <"$TMP/err" | head -c 200)"
fi
vercel_hdr="$(tr -d '\r' <"$TMP/status.h" 2>/dev/null | grep -iE '^(x-vercel-id|x-vercel-cache):|^server: *vercel' | head -1 || true)"
if [ -n "$vercel_hdr" ]; then
  pre_pass "served by Vercel ($vercel_hdr)"
else
  pre_fail "no x-vercel-id / x-vercel-cache / server: Vercel header on /status: production may still be on Hetzner, or a Cloudflare rule strips the header"
fi

code="$(curl -sS --max-time 30 -o "$TMP/metrics" -w '%{http_code}' "$API/metrics" 2>"$TMP/err")" || code="000"
if [ "$code" != 200 ]; then
  pre_fail "/metrics answered $code"
else
  age="$(jq -r '.ics_cache.last_refresh_age_seconds // empty' "$TMP/metrics" 2>/dev/null || true)"
  if [ -z "$age" ]; then
    pre_fail "/metrics has no ics_cache.last_refresh_age_seconds (no refresh heartbeat in R2 yet)"
  elif jq -e --argjson max "$MAX_AGE" '.ics_cache.last_refresh_age_seconds | numbers | . < $max' "$TMP/metrics" >/dev/null; then
    pre_pass "refresh heartbeat is $((age / 3600)) h old (limit $((MAX_AGE / 3600)) h)"
  else
    pre_fail "refresh heartbeat is $((age / 3600)) h old, over the $((MAX_AGE / 3600)) h limit: is the Vercel cron running?"
  fi
fi

if [ "$SKIP_REPO" = 0 ]; then
  if [ -z "$(git status --porcelain)" ]; then
    pre_pass "git working tree clean ($(git rev-parse --abbrev-ref HEAD))"
  else
    pre_fail "git working tree not clean: commit or stash first so the edits are a reviewable diff"
  fi
  branch="$(git rev-parse --abbrev-ref HEAD)"
  [ "$branch" = main ] || say "note  on branch $branch, not main"
fi

if [ "$PRE_FAILS" -gt 0 ] && [ "$FORCE" = 0 ]; then
  die "$PRE_FAILS preflight check(s) failed; nothing was changed (--force to override)"
fi
[ "$DRY" = 0 ] || say "[dry-run] nothing below is executed"

# --- stage 1: Hetzner ------------------------------------------------------------------
stage_hetzner() {
  hr "Stage 1: Hetzner"
  if ! have hcloud; then
    say "hcloud is not installed (brew install hcloud). Once it is, with HCLOUD_TOKEN set or"
    say "a context from \`hcloud context create bins\`:"
    say "  hcloud server list"
    say "  hcloud server delete <name>"
    say "  hcloud firewall delete $FW_NAME      # made by scripts/deploy/deployment.py"
    say "  hcloud ssh-key delete $KEY_NAME      # same"
    say "then check hcloud volume / primary-ip / floating-ip / image list for leftovers."
    if [ "$DRY" = 0 ]; then note "Hetzner: skipped, hcloud not installed (commands printed above)"; return 0; fi
  fi

  local server="${HCLOUD_SERVER:-}"
  if [ "$DRY" = 1 ]; then
    : "${server:=bins-api}"
    run hcloud server list
    say "[dry-run] server name: $server (HCLOUD_SERVER, else asked for after the list)"
    run hcloud server delete "$server"
    run hcloud firewall delete "$FW_NAME"
    run hcloud ssh-key delete "$KEY_NAME"
    run hcloud volume list
    run hcloud primary-ip list
    run hcloud floating-ip list
    run hcloud image list --type snapshot --type backup
    return 0
  fi

  say "+ hcloud server list"
  hcloud server list >&2 || die "hcloud server list failed (no token? set HCLOUD_TOKEN or create a context)"
  if [ -z "$server" ]; then
    printf 'Server to delete (name from the list above): ' >&2
    IFS= read -r server || server=""
  fi
  if [ -z "$server" ] || ! hcloud server list -o noheader -o columns=name | grep -Fxq -- "$server"; then
    say "no server named '$server' in this project: skipping Hetzner"
    note "Hetzner: skipped, no server named '$server'"
    return 0
  fi

  say "Deleting '$server' also destroys its disk: the bins_data volume, Caddy certificates,"
  say "Uptime Kuma data and GoAccess reports. The ICS cache lives in R2 (see the heartbeat check)."
  say "Anything you still want from Uptime Kuma (monitors, history) has to come off first."
  if confirm_typed "$server"; then
    run hcloud server delete "$server"
    note "Hetzner: deleted server $server"
  else
    note "Hetzner: server $server NOT deleted (confirmation not given)"
    return 0
  fi

  # What scripts/deploy/deployment.py also created. Server delete detaches the firewall.
  if hcloud firewall list -o noheader -o columns=name | grep -Fxq -- "$FW_NAME"; then
    if confirm_typed "$FW_NAME"; then run hcloud firewall delete "$FW_NAME"; note "Hetzner: deleted firewall $FW_NAME"; fi
  fi
  if hcloud ssh-key list -o noheader -o columns=name | grep -Fxq -- "$KEY_NAME"; then
    say "(this removes the public key from Hetzner only; your local key files are untouched)"
    if confirm_typed "$KEY_NAME"; then run hcloud ssh-key delete "$KEY_NAME"; note "Hetzner: deleted ssh-key $KEY_NAME"; fi
  fi

  say ""
  say "Left for you to review (listed, never deleted here):"
  local kind
  for kind in volume primary-ip floating-ip load-balancer; do
    say "--- hcloud $kind list"
    hcloud "$kind" list >&2 || true
  done
  say "--- hcloud image list --type snapshot --type backup"
  hcloud image list --type snapshot --type backup >&2 || true
}

# --- stage 2: GitHub secrets -----------------------------------------------------------
# Only what the SSH job alone needed. SERVER_IP is the older name scripts/deploy/deployment.md used.
DEL_SECRETS="SERVER_HOST SSH_PRIVATE_KEY SERVER_IP"

stage_secrets() {
  hr "Stage 2: GitHub secrets"
  say "Note: until the repo stage is merged to main, a push to main still runs the SSH deploy"
  say "job, which fails once its secrets are gone. Commit and push the repo stage promptly."

  # Secrets used by the SSH job (before the repo stage removes it) and by nothing else.
  if [ -f "$WORKFLOW" ] && grep -q '^  deploy:' "$WORKFLOW"; then
    local in_job outside left
    in_job="$(awk '/^  [A-Za-z0-9_-]+:/ {on = ($1 == "deploy:")} on' "$WORKFLOW" | grep -o 'secrets\.[A-Za-z0-9_]*' | sort -u | sed 's/^secrets\.//')"
    outside="$(awk '/^  [A-Za-z0-9_-]+:/ {on = ($1 == "deploy:")} !on' "$WORKFLOW" | grep -o 'secrets\.[A-Za-z0-9_]*' | sort -u | sed 's/^secrets\.//')"
    left="$(comm -23 <(printf '%s\n' "$in_job") <(printf '%s\n' "$outside") | tr '\n' ' ')"
    say "Secrets only the SSH deploy job references: ${left:-none}"
    say "Of those, only SERVER_HOST and SSH_PRIVATE_KEY are deleted. The rest (TURNSTILE_* are"
    say "also Vercel env vars, set by env_push.sh) are left in place: delete them by hand when sure."
  fi

  local repo existing="" s present=""
  if [ "$DRY" = 1 ]; then
    repo="<owner>/<repo>"
    run gh secret list
    for s in SERVER_HOST SSH_PRIVATE_KEY; do run gh secret delete "$s"; done
    say "[dry-run] SERVER_IP is also deleted if the repo has one"
    return 0
  fi
  have gh || { say "gh is not installed: delete SERVER_HOST and SSH_PRIVATE_KEY in repo Settings -> Secrets"; note "Secrets: skipped, gh not installed"; return 0; }
  repo="$(gh repo view --json nameWithOwner -q .nameWithOwner)" || die "gh cannot resolve the repo (gh auth login?)"
  existing="$(gh secret list -R "$repo" --json name -q '.[].name')" || die "gh secret list failed"
  for s in $DEL_SECRETS; do
    printf '%s\n' "$existing" | grep -Fxq -- "$s" && present="$present $s"
  done
  if [ -z "$present" ]; then say "none of $DEL_SECRETS exist in $repo: nothing to do"; return 0; fi
  say "Repo $repo: would delete:$present"
  say "(environment, Dependabot and org secrets are not touched)"
  if confirm_typed "$repo"; then
    for s in $present; do run gh secret delete "$s" -R "$repo"; done
    note "Secrets: deleted$present from $repo"
  else
    note "Secrets: NOT deleted (confirmation not given)"
  fi
}

# --- stage 3: repo edits ---------------------------------------------------------------
# Edits compose, the workflow, two test files and .env.example in one go (all or nothing:
# everything is computed and checked before anything is written), then prints a diff.
repo_edit_py() {
  cat <<'PY'
import difflib
import pathlib
import re
import sys

import yaml

dry = "--dry-run" in sys.argv
changes: dict[str, str] = {}
warnings: list[str] = []


def read(p):
    return pathlib.Path(p).read_text()


def stage(p, new):
    old = read(p)
    if new != old:
        changes[p] = new
    else:
        print(f"  {p}: already done")


# --- docker-compose.yml: keep `api` (local use), drop the rest of the Hetzner stack ----
REMOVE = ["worker", "redis", "caddy", "goaccess", "uptime-kuma"]
doc = yaml.safe_load(read("docker-compose.yml"))
svcs = doc["services"]
for name in REMOVE:
    svcs.pop(name, None)
api = svcs["api"]
dep = api.get("depends_on")
if isinstance(dep, dict):
    dep.pop("redis", None)
elif isinstance(dep, list):
    dep[:] = [d for d in dep if d != "redis"]
if not dep:
    api.pop("depends_on", None)
if "environment" in api:
    assert isinstance(api["environment"], list), "api.environment is not a list"
    api["environment"] = [e for e in api["environment"] if not e.startswith("REDIS_URL=")]
used = set()
for s in svcs.values():
    for v in s.get("volumes", []):
        src = v.split(":")[0] if isinstance(v, str) else v.get("source", "")
        if src and not src.startswith((".", "/", "~")):
            used.add(src)
assert "bins_data" in used, "api lost its bins_data volume"
doc["volumes"] = {k: v for k, v in (doc.get("volumes") or {}).items() if k in used}
if not doc["volumes"]:
    doc.pop("volumes")
yaml.add_representer(
    type(None), lambda d, _: d.represent_scalar("tag:yaml.org,2002:null", "")
)
stage(
    "docker-compose.yml",
    yaml.dump(doc, sort_keys=False, default_flow_style=False, width=10_000),
)

# --- deploy.yml: drop the SSH `deploy` job (text edit: keeps comments, and PyYAML would
# turn the `on:` key into `true:`) ----------------------------------------------------------
lines = read(".github/workflows/deploy.yml").split("\n")
if "  deploy:" in lines:
    start = lines.index("  deploy:")
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"  \S", lines[i])),
        len(lines),
    )
    lines[start:end] = [""] if end == len(lines) else []
    new = "\n".join(lines)
    jobs = yaml.safe_load(new)["jobs"]
    assert "deploy" not in jobs and jobs, f"unexpected jobs after edit: {list(jobs)}"
    stage(".github/workflows/deploy.yml", new.rstrip("\n") + "\n")
else:
    print("  .github/workflows/deploy.yml: already done")

# --- small text edits: (file, old, new, marker). The edit counts as done when `marker` is
# gone from the file; text that is neither there nor done is a warning, not an error. ------
EDITS = [
    (
        "tests/test_deploy.py",
        '    """App boots and connects to Redis."""',
        '    """App boots and answers the health route."""',
        "connects to Redis",
    ),
    (
        "tests/test_deploy_docker.sh",
        'echo ""\n'
        'echo "--- Redis Connectivity ---"\n'
        "# Health endpoint should reflect redis status when REDIS_URL is set\n"
        'assert_json_field "Health includes redis info" "$BASE_URL/api/v2/health" "isinstance(data, list)"\n\n',
        "",
        "Redis Connectivity",
    ),
    (
        ".env.example",
        "# Hetzner API token (required for deployment.py)\nHCLOUD_TOKEN=\n\n",
        "",
        "HCLOUD_TOKEN",
    ),
]
for path, old, new, marker in EDITS:
    text = changes.get(path) or read(path)
    if old in text:
        changes[path] = text.replace(old, new, 1)
    elif marker not in text:
        print(f"  {path}: already done")
    else:
        warnings.append(f"{path}: expected text not found, edit it by hand (remove: {marker!r})")

for path, new in changes.items():
    print("".join(difflib.unified_diff(read(path).splitlines(True), new.splitlines(True), path, path)))
    if not dry:
        pathlib.Path(path).write_text(new)
for w in warnings:
    print(f"WARNING {w}", file=sys.stderr)
PY
}

pyrun() {
  if have python3 && python3 -c 'import yaml' 2>/dev/null; then
    python3 - "$@"
  else
    have uv || die "need python3 with PyYAML, or uv"
    uv run --no-project --with pyyaml python - "$@"
  fi
}

stage_repo() {
  hr "Stage 3: repo edits"
  local rm_paths="Caddyfile goaccess.conf scripts/deploy" p existing_rm=""
  for p in $rm_paths; do [ -e "$p" ] && existing_rm="$existing_rm $p"; done
  say "Will: git rm -r${existing_rm:- (nothing left to remove)}"
  say "      trim docker-compose.yml to api (worker, redis, caddy, goaccess, uptime-kuma out; REDIS_URL and"
  say "      depends_on dropped; bins_data kept; PyYAML rewrites the file, so its comments are lost)"
  say "      remove the SSH deploy job from $WORKFLOW"
  say "      uv remove --dev hcloud paramiko"
  say "      tests/test_deploy.py, tests/test_deploy_docker.sh: drop the Redis wording/check; .env.example: drop HCLOUD_TOKEN"
  have uv || die "uv not installed (needed for uv remove and the test run)"
  confirm_typed yes || { note "Repo: NOT edited (confirmation not given)"; return 0; }

  if [ "$DRY" = 1 ]; then
    say "[dry-run] file edits as a diff (nothing written):"
    repo_edit_py | pyrun --dry-run
    # shellcheck disable=SC2086
    [ -z "$existing_rm" ] || run git rm -r $existing_rm
    run uv remove --dev hcloud paramiko
    run uv run pytest -m ci -q
    return 0
  fi

  say "On failure from here, the tree was clean: \`git restore --staged --worktree .\` undoes it."
  say "file edits:"
  repo_edit_py | pyrun
  # shellcheck disable=SC2086
  [ -z "$existing_rm" ] || run git rm -r -q $existing_rm
  if grep -qE '"(hcloud|paramiko)[>=~ ]' pyproject.toml; then
    run uv remove --dev hcloud paramiko
  else
    say "hcloud/paramiko already out of pyproject.toml"
  fi

  hr "Verify"
  if have docker; then
    run docker compose -f docker-compose.yml config -q
  else
    say "docker not installed: compose file only checked as YAML"
  fi
  run bash -n tests/test_deploy_docker.sh
  if run uv run pytest -m ci -q; then
    note "Repo: edited; ci tests pass"
  else
    note "Repo: edited, but ci tests FAILED, look before committing"
  fi
}

if [ "$SKIP_HETZNER" = 1 ]; then note "Hetzner: skipped (--skip-hetzner)"; else stage_hetzner; fi
if [ "$SKIP_SECRETS" = 1 ]; then note "Secrets: skipped (--skip-secrets)"; else stage_secrets; fi
if [ "$SKIP_REPO" = 1 ]; then note "Repo: skipped (--skip-repo)"; else stage_repo; fi

# --- wrap-up ---------------------------------------------------------------------------
hr "Summary"
printf '%s' "$SUMMARY" >&2
if [ "$SKIP_REPO" = 0 ] && [ "$DRY" = 0 ]; then
  say ""
  say "git status:"
  git status --short >&2
  git diff --stat HEAD >&2 || true
  say ""
  say "Suggested commit message (not committed):"
  cat >&2 <<'MSG'
  Decommission Hetzner: drop Caddy, GoAccess, Uptime Kuma, worker, Redis and the SSH deploy

  Production has been on Vercel since the cutover and the refresh heartbeat is
  healthy. Remove the compose services only Hetzner used (api stays for local
  runs), the SSH deploy job, scripts/deploy/ and the hcloud/paramiko dev
  dependencies.
MSG
fi

hr "Manual follow-ups"
cat >&2 <<'TXT'
  AGENTS.md
    - Infrastructure: now Vercel (lhr1) + Cloudflare (cache and rate-limit rules) + R2; compose
      is the api alone, for local runs
    - CI/CD: deploy.yml is smoke-test then deploy-vercel; no SSH job
    - services/refresh_job.py: runs from the Vercel cron via /api/v2/internal/refresh, not a
      `worker` container; scrape_lock and ics_cache wording (R2, Redis optional)
    - drop `deploy/deployment.py`; test_deploy.py / test_deploy_docker.sh descriptions; ibis mentions
  VERCEL.md: mark phase 6 done and the Status line; fix the "Both deploy on every push" CI bullet
  README.md "Deployment" section: Redis/Caddy/Uptime Kuma wording and the link to deploy/deployment.md
  tests/battletest/README.md: goaccess / uptime-kuma rows
  .env.example: the REDIS_URL comment says "set automatically in docker-compose"; no longer true
  Monitoring (Uptime Kuma is gone with the box):
    - UptimeRobot / Better Stack HTTP check on https://ukbinday.co.uk/api/v2/status (expect 200)
    - second check on /api/v2/metrics: alert when .ics_cache.last_refresh_age_seconds is null or
      > 129600 (36 h); Better Stack's JSON/keyword assertions can do it, else a small cron script
    - Cloudflare Web Analytics (dashboard -> Analytics & Logs) replaces GoAccess; Vercel keeps
      runtime logs for an hour only, so add a log drain or Sentry if errors need keeping
  Elsewhere: DNS/Cloudflare records still pointing at the Hetzner IP, the Hetzner project itself
    (API token, billing), and any Uptime Kuma status page links
TXT
