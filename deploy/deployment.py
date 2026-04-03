"""
Hetzner deployment script for Bin Collection API.

Automates the full deployment pipeline:
  1. Upload SSH key to Hetzner
  2. Create firewall (SSH, HTTP, HTTPS, Uptime Kuma)
  3. Provision server with cloud-init (Docker, deploy user, UFW, clone repo, docker compose up)
  4. Wait for server to be ready
  5. Print next steps (DNS, verify)

Prerequisites:
  - uv add hcloud paramiko  (paramiko only needed for --ssh commands)
  - HCLOUD_TOKEN env var or --token flag
  - SSH public key at ~/.ssh/id_ed25519.pub (or specify with --ssh-key-file)

Usage:
  uv run python deployment.py provision
  uv run python deployment.py destroy
  uv run python deployment.py deploy          # SSH in and git pull + rebuild
  uv run python deployment.py ssh <command>   # Run arbitrary command on server
  uv run python deployment.py status          # Show server info
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
import time
from pathlib import Path

from hcloud import Client
from hcloud.firewalls.domain import FirewallRule, FirewallResource
from hcloud.servers.domain import ServerCreatePublicNetwork

# ---------------------------------------------------------------------------
# Config — edit these to taste
# ---------------------------------------------------------------------------
SERVER_NAME = "bins-api"
SERVER_TYPE = "cx22"  # 2 vCPU, 4 GB RAM — bump to cx32 if needed
IMAGE = "ubuntu-24.04"
LOCATION = "fsn1"  # Falkenstein, DE — closest to UK
SSH_KEY_NAME = "bins-deploy"
FIREWALL_NAME = "bins-firewall"
DOMAIN = "bincollection.co.uk"
REPO_URL = "https://github.com/09steicm/bins.git"  # change to your repo
DEPLOY_USER = "deploy"
LABELS = {"project": "bins", "managed-by": "deployment-script"}


def get_client(token: str | None = None) -> Client:
    token = token or os.environ.get("HCLOUD_TOKEN")
    if not token:
        print("Error: set HCLOUD_TOKEN env var or pass --token", file=sys.stderr)
        sys.exit(1)
    return Client(token=token)


# ---------------------------------------------------------------------------
# Cloud-init user data — runs on first boot as root
# ---------------------------------------------------------------------------
def build_cloud_init(repo_url: str, deploy_user: str) -> str:
    return textwrap.dedent(f"""\
        #!/bin/bash
        set -euo pipefail
        exec > /var/log/cloud-init-deploy.log 2>&1

        echo ">>> Updating packages"
        apt-get update && apt-get upgrade -y

        echo ">>> Creating deploy user"
        useradd -m -s /bin/bash -G sudo {deploy_user}
        echo "{deploy_user} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/{deploy_user}
        mkdir -p /home/{deploy_user}/.ssh
        cp /root/.ssh/authorized_keys /home/{deploy_user}/.ssh/authorized_keys
        chown -R {deploy_user}:{deploy_user} /home/{deploy_user}/.ssh
        chmod 700 /home/{deploy_user}/.ssh
        chmod 600 /home/{deploy_user}/.ssh/authorized_keys

        echo ">>> Installing Docker"
        curl -fsSL https://get.docker.com | sh
        usermod -aG docker {deploy_user}

        echo ">>> Setting up UFW"
        ufw allow OpenSSH
        ufw allow 80/tcp
        ufw allow 443/tcp
        ufw allow 3001/tcp
        ufw --force enable

        echo ">>> Disabling root SSH login"
        sed -i 's/^#\\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
        systemctl restart sshd

        echo ">>> Cloning repository"
        su - {deploy_user} -c "git clone {repo_url} /home/{deploy_user}/bins"

        echo ">>> Creating .env"
        cat > /home/{deploy_user}/bins/.env << 'ENVEOF'
        REDIS_URL=redis://redis:6379
        ENVEOF
        chown {deploy_user}:{deploy_user} /home/{deploy_user}/bins/.env

        echo ">>> Starting docker compose"
        su - {deploy_user} -c "cd /home/{deploy_user}/bins && docker compose up -d --build"

        echo ">>> Cloud-init complete"
    """)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_provision(client: Client, ssh_key_file: str) -> None:
    """Provision a new server with everything configured."""

    # 1. SSH key
    pub_key_path = Path(ssh_key_file).expanduser()
    if not pub_key_path.exists():
        print(f"Error: SSH public key not found at {pub_key_path}", file=sys.stderr)
        sys.exit(1)
    pub_key = pub_key_path.read_text().strip()

    existing_key = client.ssh_keys.get_by_name(SSH_KEY_NAME)
    if existing_key:
        print(f"SSH key '{SSH_KEY_NAME}' already exists (id={existing_key.data_model.id})")
        ssh_key = existing_key
    else:
        ssh_key = client.ssh_keys.create(name=SSH_KEY_NAME, public_key=pub_key)
        print(f"Created SSH key '{SSH_KEY_NAME}' (id={ssh_key.data_model.id})")

    # 2. Firewall
    existing_fw = client.firewalls.get_by_name(FIREWALL_NAME)
    if existing_fw:
        print(f"Firewall '{FIREWALL_NAME}' already exists (id={existing_fw.data_model.id})")
        firewall = existing_fw
    else:
        rules = [
            FirewallRule(
                direction=FirewallRule.DIRECTION_IN,
                protocol=FirewallRule.PROTOCOL_TCP,
                source_ips=["0.0.0.0/0", "::/0"],
                port="22",
                description="SSH",
            ),
            FirewallRule(
                direction=FirewallRule.DIRECTION_IN,
                protocol=FirewallRule.PROTOCOL_TCP,
                source_ips=["0.0.0.0/0", "::/0"],
                port="80",
                description="HTTP",
            ),
            FirewallRule(
                direction=FirewallRule.DIRECTION_IN,
                protocol=FirewallRule.PROTOCOL_TCP,
                source_ips=["0.0.0.0/0", "::/0"],
                port="443",
                description="HTTPS",
            ),
            FirewallRule(
                direction=FirewallRule.DIRECTION_IN,
                protocol=FirewallRule.PROTOCOL_TCP,
                source_ips=["0.0.0.0/0", "::/0"],
                port="3001",
                description="Uptime Kuma",
            ),
        ]
        response = client.firewalls.create(name=FIREWALL_NAME, rules=rules, labels=LABELS)
        firewall = response.firewall
        print(f"Created firewall '{FIREWALL_NAME}' (id={firewall.data_model.id})")

    # 3. Check for existing server
    existing_server = client.servers.get_by_name(SERVER_NAME)
    if existing_server:
        ip = existing_server.public_net.ipv4.ip
        print(f"\nServer '{SERVER_NAME}' already exists at {ip}")
        print("Run 'deployment.py destroy' first if you want to recreate it.")
        return

    # 4. Create server
    print(f"\nProvisioning server '{SERVER_NAME}' ({SERVER_TYPE} / {IMAGE} / {LOCATION})...")
    user_data = build_cloud_init(REPO_URL, DEPLOY_USER)

    response = client.servers.create(
        name=SERVER_NAME,
        server_type=client.server_types.get_by_name(SERVER_TYPE),
        image=client.images.get_by_name(IMAGE),
        location=client.locations.get_by_name(LOCATION),
        ssh_keys=[ssh_key],
        firewalls=[firewall],
        user_data=user_data,
        labels=LABELS,
        public_net=ServerCreatePublicNetwork(enable_ipv4=True, enable_ipv6=True),
    )

    # 5. Wait for server action to complete
    print("Waiting for server to be created...", end="", flush=True)
    response.action.wait_until_finished()
    for action in response.next_actions:
        action.wait_until_finished()
    print(" done.")

    server = client.servers.get_by_name(SERVER_NAME)
    ipv4 = server.public_net.ipv4.ip
    ipv6 = server.public_net.ipv6.ip

    print(f"""
Server provisioned successfully!

  Name:     {SERVER_NAME}
  IPv4:     {ipv4}
  IPv6:     {ipv6}
  Image:    {IMAGE}
  Type:     {SERVER_TYPE}
  Location: {LOCATION}

Cloud-init is now running in the background (installing Docker, cloning repo,
starting containers). This takes ~3-5 minutes.

Next steps:
  1. Point DNS for {DOMAIN}:
       A    record -> {ipv4}
       AAAA record -> {ipv6}

  2. Monitor cloud-init progress:
       ssh root@{ipv4} tail -f /var/log/cloud-init-deploy.log

     (root SSH is available until cloud-init disables it — use {DEPLOY_USER}@ after)

  3. Once cloud-init finishes and DNS propagates:
       curl https://{DOMAIN}/api/v1/health

  4. Set up Uptime Kuma:
       http://{ipv4}:3001
""")


def cmd_destroy(client: Client) -> None:
    """Tear down server, firewall, and SSH key."""
    server = client.servers.get_by_name(SERVER_NAME)
    if server:
        print(f"Deleting server '{SERVER_NAME}' (id={server.data_model.id})...")
        server.delete()
        print("Server deleted.")
    else:
        print(f"No server named '{SERVER_NAME}' found.")

    firewall = client.firewalls.get_by_name(FIREWALL_NAME)
    if firewall:
        print(f"Deleting firewall '{FIREWALL_NAME}'...")
        firewall.delete()
        print("Firewall deleted.")

    ssh_key = client.ssh_keys.get_by_name(SSH_KEY_NAME)
    if ssh_key:
        print(f"Deleting SSH key '{SSH_KEY_NAME}'...")
        ssh_key.delete()
        print("SSH key deleted.")

    print("\nAll resources cleaned up.")


def cmd_status(client: Client) -> None:
    """Show current server status."""
    server = client.servers.get_by_name(SERVER_NAME)
    if not server:
        print(f"No server named '{SERVER_NAME}' found.")
        return

    print(f"""
  Name:     {server.data_model.name}
  Status:   {server.data_model.status}
  IPv4:     {server.public_net.ipv4.ip}
  IPv6:     {server.public_net.ipv6.ip}
  Type:     {server.data_model.server_type.name}
  Location: {server.data_model.datacenter.name}
  Created:  {server.data_model.created}
""")


def _ssh_exec(client: Client, ssh_key_file: str, command: str) -> int:
    """SSH into the server and run a command. Returns exit code."""
    try:
        import paramiko
    except ImportError:
        print("Error: paramiko required for SSH commands. Run: uv add paramiko", file=sys.stderr)
        sys.exit(1)

    server = client.servers.get_by_name(SERVER_NAME)
    if not server:
        print(f"No server named '{SERVER_NAME}' found.", file=sys.stderr)
        sys.exit(1)

    ip = server.public_net.ipv4.ip
    priv_key_path = Path(ssh_key_file).expanduser().with_suffix("")
    if not priv_key_path.exists():
        print(f"Error: private key not found at {priv_key_path}", file=sys.stderr)
        sys.exit(1)

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    print(f"Connecting to {DEPLOY_USER}@{ip}...")
    ssh.connect(hostname=ip, username=DEPLOY_USER, key_filename=str(priv_key_path))

    print(f"Running: {command}\n")
    stdin, stdout, stderr = ssh.exec_command(command)
    for line in stdout:
        print(line, end="")
    for line in stderr:
        print(line, end="", file=sys.stderr)

    exit_code = stdout.channel.recv_exit_status()
    ssh.close()
    return exit_code


def cmd_deploy(client: Client, ssh_key_file: str) -> None:
    """Pull latest code and rebuild on the server."""
    command = "cd ~/bins && git pull origin main && docker compose up -d --build && docker image prune -f"
    exit_code = _ssh_exec(client, ssh_key_file, command)
    if exit_code == 0:
        print("\nDeploy complete.")
    else:
        print(f"\nDeploy failed with exit code {exit_code}.", file=sys.stderr)
        sys.exit(exit_code)


def cmd_ssh(client: Client, ssh_key_file: str, command: str) -> None:
    """Run an arbitrary command on the server."""
    exit_code = _ssh_exec(client, ssh_key_file, command)
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Bin Collection API to Hetzner")
    parser.add_argument("--token", help="Hetzner API token (or set HCLOUD_TOKEN)")
    parser.add_argument(
        "--ssh-key-file",
        default="~/.ssh/id_ed25519.pub",
        help="Path to SSH public key (default: ~/.ssh/id_ed25519.pub)",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("provision", help="Create server, firewall, SSH key and deploy")
    sub.add_parser("destroy", help="Delete server, firewall, and SSH key")
    sub.add_parser("deploy", help="Pull latest code and rebuild on server")
    sub.add_parser("status", help="Show server info")

    ssh_parser = sub.add_parser("ssh", help="Run a command on the server")
    ssh_parser.add_argument("remote_command", nargs="+", help="Command to run")

    args = parser.parse_args()
    client = get_client(args.token)

    if args.command == "provision":
        cmd_provision(client, args.ssh_key_file)
    elif args.command == "destroy":
        cmd_destroy(client, args.ssh_key_file if hasattr(args, "ssh_key_file") else None)
    elif args.command == "deploy":
        cmd_deploy(client, args.ssh_key_file)
    elif args.command == "status":
        cmd_status(client)
    elif args.command == "ssh":
        cmd_ssh(client, args.ssh_key_file, " ".join(args.remote_command))


if __name__ == "__main__":
    main()
