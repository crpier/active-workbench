# Active Workbench Deployment (Tailscale-only VM + systemd)

**Updated:** 2026-02-22

This is the simplest deployment for a single-user setup (your own devices only).

This runbook deploys:
- Active Workbench backend on `:8000` (tailnet access only)
- OpenCode serve on `:4096` (tailnet access only)
- `systemd` services for both
- Daily SQLite/log backups via `systemd` timer
- No Nginx, no public TLS, no app-level auth

Trust model:
- Tailscale is the network boundary.
- Any device authenticated into your tailnet that can reach this VM can use the app.

## 1. VM and network assumptions

Open only what you need publicly:
- `22/tcp` (SSH) if you manage the VM over public internet

Do **not** open these publicly:
- `80/tcp`
- `443/tcp`
- `8000/tcp`
- `4096/tcp`
- `9090/tcp` (Cockpit, if installed)

Install Tailscale on:
- the VM
- your PC
- your phone

## 2. Bootstrap VM packages

```bash
sudo apt-get update
sudo apt-get install -y git sqlite3
```

Install `uv`, `opencode`, and Tailscale using the official installers for your distro/user setup.

## 3. Create service user and directories

```bash
sudo useradd -m -s /bin/bash active-workbench || true
sudo mkdir -p /opt/active-workbench
sudo mkdir -p /var/lib/active-workbench/data
sudo mkdir -p /var/lib/active-workbench/backups
sudo mkdir -p /etc/active-workbench
sudo chown -R active-workbench:active-workbench /opt/active-workbench
sudo chown -R active-workbench:active-workbench /var/lib/active-workbench
sudo chmod 750 /etc/active-workbench
```

## 4. Deploy code and runtime env

```bash
sudo -u active-workbench git clone https://github.com/crpier/active-workbench /opt/active-workbench
cd /opt/active-workbench
sudo cp deploy/env/active-workbench.env.example /etc/active-workbench/active-workbench.env
sudo cp deploy/env/opencode.env.example /etc/active-workbench/opencode.env
sudo chown root:active-workbench /etc/active-workbench/active-workbench.env /etc/active-workbench/opencode.env
sudo chmod 640 /etc/active-workbench/active-workbench.env /etc/active-workbench/opencode.env
```

Edit env files:
- `/etc/active-workbench/active-workbench.env` (API keys, data dir, rate limits)
- `/etc/active-workbench/opencode.env` (provider keys/model defaults)

Defaults in the env examples are already set for Tailscale-only access:
- `ACTIVE_WORKBENCH_BIND_HOST=0.0.0.0`
- `OPENCODE_SERVER_HOSTNAME=0.0.0.0`
- no OpenCode username/password

Install Python deps:

```bash
cd /opt/active-workbench
sudo -u active-workbench uv sync --all-groups
```

If OpenCode requires interactive provider auth on this VM, run it once as the service user:

```bash
sudo -u active-workbench opencode auth login
```

If using YouTube OAuth mode (recommended), place OAuth files in:
- `/var/lib/active-workbench/data/youtube-client-secret.json`
- `/var/lib/active-workbench/data/youtube-token.json`

## 5. Install systemd units

```bash
sudo cp /opt/active-workbench/deploy/systemd/active-workbench-backend.service /etc/systemd/system/
sudo cp /opt/active-workbench/deploy/systemd/opencode-serve.service /etc/systemd/system/
sudo cp /opt/active-workbench/deploy/systemd/active-workbench-backup.service /etc/systemd/system/
sudo cp /opt/active-workbench/deploy/systemd/active-workbench-backup.timer /etc/systemd/system/
sudo chmod +x /opt/active-workbench/deploy/scripts/backup_active_workbench.sh
sudo systemctl daemon-reload
sudo systemctl enable --now active-workbench-backend.service
sudo systemctl enable --now opencode-serve.service
sudo systemctl enable --now active-workbench-backup.timer
```

Local health checks on the VM:

```bash
sudo systemctl status active-workbench-backend.service --no-pager
sudo systemctl status opencode-serve.service --no-pager
curl -sS http://127.0.0.1:8000/health
curl -sS -I http://127.0.0.1:4096/ | head -n 5
```

## 6. Join Tailscale and confirm reachability

Install Tailscale using official instructions, then:

```bash
sudo tailscale up
tailscale ip -4
```

From the VM, note the Tailscale IPv4 (for example `100.x.y.z`).

From a device on the same tailnet, test:

```bash
curl -sS http://<tailscale-ip>:8000/health
curl -sS -I http://<tailscale-ip>:4096/ | head -n 5
```

Expected:
- backend `/health` returns `{"status":"ok"}`
- OpenCode returns `200 OK` (no auth challenge in Tailscale-only mode)

## 7. Mobile app setup (no bearer token)

Use the backend Tailscale URL in the mobile app, for example:
- `http://<tailscale-ip>:8000`

## 8. Backups and restore

Manual backup:

```bash
sudo systemctl start active-workbench-backup.service
sudo journalctl -u active-workbench-backup.service -n 50 --no-pager
```

Restore example:
1. Stop backend service.
2. Decompress backup DB into `${ACTIVE_WORKBENCH_DATA_DIR}/state.db`.
3. Start backend service.

## 9. Updates (rolling)

```bash
cd /opt/active-workbench
sudo -u active-workbench git pull
sudo -u active-workbench uv sync --all-groups
sudo systemctl restart active-workbench-backend.service
sudo systemctl restart opencode-serve.service
```

## 10. Optional observability over Tailscale

If you install Cockpit or other admin UIs, keep them private:
- bind/access over Tailscale
- do not open public firewall ports

## 11. Public internet deployment (optional, advanced)

If you later need public access:
- use `docs/DEPLOY_NGINX_VM.md`
- bind services to loopback (`127.0.0.1`)
- re-enable app-level auth for exposed surfaces
