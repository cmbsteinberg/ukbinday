#!/usr/bin/env bash
# Set the GitHub secrets that switch on the deploy-vercel job in deploy.yml.
# Serves VERCEL.md phase 4. Once these exist, every push to main deploys to Vercel production.
#
#   scripts/vercel/github_secrets.sh            # mint a Vercel token, set all three secrets
#   VERCEL_TOKEN=... scripts/vercel/github_secrets.sh   # use a token you made in the dashboard
#
# VERCEL_ORG_ID / VERCEL_PROJECT_ID come from .vercel/project.json (npx vercel@latest link).
# The token is minted with `vercel api POST /v3/user/tokens` (named bins-github-actions-<date>,
# no expiry; revoke it under Account Settings -> Tokens) and piped straight into
# `gh secret set`, so it is never printed or written to disk.
# Needs: vercel login, gh auth login, jq.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
[ -f .vercel/project.json ] || { echo "github_secrets: project not linked; run: npx vercel@latest link" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "github_secrets: run gh auth login" >&2; exit 1; }

jq -r .orgId .vercel/project.json | gh secret set VERCEL_ORG_ID
jq -r .projectId .vercel/project.json | gh secret set VERCEL_PROJECT_ID

if [ -n "${VERCEL_TOKEN:-}" ]; then
  printf '%s' "$VERCEL_TOKEN" | gh secret set VERCEL_TOKEN
else
  npx --yes vercel@latest api /v3/user/tokens -X POST --raw \
      -f name="bins-github-actions-$(date +%Y%m%d)" \
    | jq -er .bearerToken | gh secret set VERCEL_TOKEN
fi
echo "github_secrets: set VERCEL_ORG_ID, VERCEL_PROJECT_ID, VERCEL_TOKEN on $(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "github_secrets: the next push to main deploys to Vercel production (deploy-vercel job)"
