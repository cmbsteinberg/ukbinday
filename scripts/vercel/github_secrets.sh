#!/usr/bin/env bash
# Set the GitHub secrets that switch on the deploy-vercel job in deploy.yml.
# Serves VERCEL.md phase 4. Once these exist, every push to main deploys to Vercel production.
#
#   scripts/vercel/github_secrets.sh                    # prompts for the token (hidden)
#   VERCEL_TOKEN=... scripts/vercel/github_secrets.sh   # or pass it in
#
# VERCEL_ORG_ID / VERCEL_PROJECT_ID come from .vercel/project.json (npx vercel@latest link).
# The token comes from vercel.com/account/tokens (the CLI login can't mint one: 403
# "Cannot create tokens for this app"); it goes straight into `gh secret set`, never
# printed or written to disk. If gh is logged in to several accounts, pass the repo
# owner's token: GH_TOKEN=$(gh auth token -u <owner>) scripts/vercel/github_secrets.sh
# Needs: vercel login, gh auth login, jq.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
[ -f .vercel/project.json ] || { echo "github_secrets: project not linked; run: npx vercel@latest link" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "github_secrets: run gh auth login" >&2; exit 1; }

jq -r .orgId .vercel/project.json | gh secret set VERCEL_ORG_ID
jq -r .projectId .vercel/project.json | gh secret set VERCEL_PROJECT_ID

if [ -z "${VERCEL_TOKEN:-}" ]; then
  # Vercel refuses token creation from the CLI's own login ("Cannot create tokens for
  # this app"), so a token has to come from the dashboard: vercel.com/account/tokens
  read -r -s -p "Paste a Vercel token (vercel.com/account/tokens; input hidden): " VERCEL_TOKEN </dev/tty; echo >&2
fi
[ -n "$VERCEL_TOKEN" ] || { echo "github_secrets: no token, VERCEL_TOKEN not set" >&2; exit 1; }
printf '%s' "$VERCEL_TOKEN" | gh secret set VERCEL_TOKEN
echo "github_secrets: set VERCEL_ORG_ID, VERCEL_PROJECT_ID, VERCEL_TOKEN on $(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "github_secrets: the next push to main deploys to Vercel production (deploy-vercel job)"
