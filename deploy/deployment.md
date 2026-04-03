# Deploying to Hetzner

Automated deployment using `deploy/deployment.py` (wraps the Hetzner Cloud API via `hcloud-python`).

---

## Prerequisites

1. A [Hetzner Cloud API token](https://console.hetzner.cloud/projects) (read/write)
2. An SSH key pair at `~/.ssh/id_ed25519` (or pass `--ssh-key-file`)
3. Python dependencies installed:
   ```bash
   uv add hcloud paramiko
   ```
4. Copy and fill in the env file:
   ```bash
   cp .env.example .env
   # Add your HCLOUD_TOKEN
   ```

## 1. Provision the Server

One command creates everything — SSH key, firewall, and a CX22 server with cloud-init that installs Docker, creates a `deploy` user, clones the repo, and runs `docker compose up`:

```bash
uv run python deploy/deployment.py provision
```

The script will print the server IP when done. Cloud-init runs in the background and takes ~3-5 minutes to finish.

You can monitor progress:

```bash
uv run python deploy/deployment.py ssh "tail -f /var/log/cloud-init-deploy.log"
```

> Edit the constants at the top of `deploy/deployment.py` to change server type, location, repo URL, or domain.

## 2. Point Your Domain

Once you have the server IP (shown after provision, or check with `status`):

1. Go to your DNS provider for `bincollection.co.uk`
2. Create/update records:
   - `A` record: `bincollection.co.uk` → `<server-ipv4>`
   - `AAAA` record (optional): `bincollection.co.uk` → `<server-ipv6>`
3. Wait for propagation: `dig bincollection.co.uk`

> Caddy auto-provisions Let's Encrypt certs, but the domain must resolve to your server **before** HTTPS will work.

## 3. Verify

```bash
# Check server status
uv run python deploy/deployment.py status

# Test the API
curl https://bincollection.co.uk/api/v1/health

# Check container logs
uv run python deploy/deployment.py ssh "cd ~/bins && docker compose ps"
uv run python deploy/deployment.py ssh "cd ~/bins && docker compose logs --tail 50"
```

Set up Uptime Kuma monitoring at `http://<server-ip>:3001`.

## 4. Redeploying

After pushing code to main, redeploy with:

```bash
uv run python deploy/deployment.py deploy
```

This SSHes in and runs `git pull && docker compose up -d --build && docker image prune -f`.

### GitHub Actions (optional)

For automatic deploys on push to main, create `.github/workflows/deploy.yml`:

```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy via SSH
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.SERVER_IP }}
          username: deploy
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            cd ~/bins
            git pull origin main
            docker compose up -d --build
            docker image prune -f
```

Add these GitHub repo secrets:
- `SERVER_IP` — your Hetzner server IP
- `SSH_PRIVATE_KEY` — private key whose public key is on the server

## 5. Maintenance

```bash
# View logs
uv run python deploy/deployment.py ssh "cd ~/bins && docker compose logs api --tail 100"
uv run python deploy/deployment.py ssh "cd ~/bins && docker compose logs caddy --tail 100"

# Resource usage
uv run python deploy/deployment.py ssh "docker stats --no-stream"
uv run python deploy/deployment.py ssh "df -h"

# Run any command
uv run python deploy/deployment.py ssh "<command>"
```

## 6. Tearing Down

Remove all Hetzner resources (server, firewall, SSH key):

```bash
uv run python deploy/deployment.py destroy
```

## Command Reference

| Command | Description |
|---|---|
| `deploy/deployment.py provision` | Create server, firewall, SSH key; run cloud-init |
| `deploy/deployment.py destroy` | Delete server, firewall, SSH key |
| `deploy/deployment.py deploy` | Git pull + docker compose rebuild on server |
| `deploy/deployment.py status` | Show server IP, status, type |
| `deploy/deployment.py ssh <cmd>` | Run arbitrary command on server |

All commands accept `--token <token>` (or use `HCLOUD_TOKEN` env var) and `--ssh-key-file <path>` (default `~/.ssh/id_ed25519.pub`).
