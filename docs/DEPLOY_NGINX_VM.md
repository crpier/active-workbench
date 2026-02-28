# Active Workbench Deployment (Nginx + systemd + Hetzner-style VM)

**Updated:** 2026-02-22

This is the public-internet deployment variant.
For a simpler single-user setup on your own devices, use `docs/DEPLOY_TAILSCALE_VM.md` instead.

This runbook deploys:
- Active Workbench backend on `127.0.0.1:8000`
- Expo web UI served by backend under `/app/*`
- OpenCode serve on `127.0.0.1:4096`
- Nginx TLS reverse proxy on `443`
- Daily SQLite/log backups via `systemd` timer

## 1. DNS and VM assumptions

Create DNS records:
- `api.example.com` -> VM public IP
- `chat.example.com` -> VM public IP

Open firewall ports:
- `22/tcp` (SSH)
- `80/tcp` (Let's Encrypt challenge + HTTP redirect)
- `443/tcp` (HTTPS)

Keep admin/observability UIs off the public internet:
- do **not** open `9090/tcp` (Cockpit) publicly
- access Cockpit over Tailscale/private network

## 2. Bootstrap VM packages

```bash
sudo apt-get update
sudo apt-get install -y git nginx certbot sqlite3
```

Install `uv` and `opencode` with official installers for your distro/user setup.

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
- `/etc/active-workbench/active-workbench.env` (set API keys, data dir, auth/rate limits)
- `/etc/active-workbench/opencode.env` (set provider keys/model defaults and OpenCode server auth)

Because the systemd unit templates now default to Tailscale-friendly `0.0.0.0` binding, set these for the Nginx reverse-proxy deployment:
- `ACTIVE_WORKBENCH_BIND_HOST=127.0.0.1`
- `OPENCODE_SERVER_HOSTNAME=127.0.0.1`

For OpenCode UI/API protection, set both:
- `OPENCODE_SERVER_USERNAME`
- `OPENCODE_SERVER_PASSWORD` (long random password)

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

Check service health:

```bash
sudo systemctl status active-workbench-backend.service --no-pager
sudo systemctl status opencode-serve.service --no-pager
curl -sS http://127.0.0.1:8000/health
curl -sS -I http://127.0.0.1:4096/
```

## 6. Issue TLS certificates

Run standalone cert issuance before enabling TLS site config:

```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d api.example.com -d chat.example.com
```

## 7. Configure Nginx reverse proxy

Copy and edit the template:

```bash
sudo cp /opt/active-workbench/deploy/nginx/active-workbench.conf /etc/nginx/sites-available/active-workbench.conf
sudo nano /etc/nginx/sites-available/active-workbench.conf
```

Replace:
- `api.example.com`
- `chat.example.com`

Enable site:

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/active-workbench.conf /etc/nginx/sites-enabled/active-workbench.conf
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

## 8. First production checks

```bash
curl -sS https://api.example.com/health
curl -sS -I https://api.example.com/app/articles | head -n 5
curl -sS -I https://chat.example.com/ | head -n 5
```

Expected for OpenCode endpoint without credentials:
- `401 Unauthorized`
- `WWW-Authenticate` header present

Verify with credentials:

```bash
curl -sS -u 'opencode:YOUR_PASSWORD' -I https://chat.example.com/ | head -n 5
```

Expected with valid credentials:
- `200 OK`

## 9. Mobile app auth setup

Create per-device key:

```bash
cd /opt/active-workbench
sudo -u active-workbench uv run python -m backend.app.scripts.mobile_api_keys create --device-name "pixel-test"
sudo -u active-workbench uv run python -m backend.app.scripts.mobile_api_keys list
```

Paste generated token (`mkey_xxx.secret`) in Android app settings as `Mobile API key (Bearer)`.

## 10. Backups and restore

Manual backup:

```bash
sudo systemctl start active-workbench-backup.service
sudo journalctl -u active-workbench-backup.service -n 50 --no-pager
```

Restore example:
1. Stop backend service.
2. Decompress backup DB into `${ACTIVE_WORKBENCH_DATA_DIR}/state.db`.
3. Start backend service.

## 11. Updates (rolling)

```bash
cd /opt/active-workbench
sudo -u active-workbench git pull
sudo -u active-workbench uv sync --all-groups
sudo systemctl restart active-workbench-backend.service
sudo systemctl restart opencode-serve.service
```

## 12. Observability (recommended for early-stage ops)

This setup gives you:
- phone-friendly VM/service checks (`Cockpit`)
- private admin access without public exposure (`Tailscale`)
- searchable logs + alerts (`Vector` -> Better Stack)

### 12.1 Tailscale (private access for ops UIs)

Install Tailscale using the official instructions for your distro, then:

```bash
sudo tailscale up
tailscale ip -4
```

Use the Tailscale IP for private admin access (for example Cockpit at `https://<tailscale-ip>:9090`).

### 12.2 Cockpit (systemd + VM health UI)

```bash
sudo apt-get install -y cockpit
sudo systemctl enable --now cockpit.socket
```

Cockpit gives you:
- `systemd` service status/restarts (backend + opencode + vector)
- `journald` logs in browser
- CPU / memory / disk quick checks

Recommended access pattern:
- expose Cockpit only over Tailscale/private network
- do not open `9090/tcp` publicly

### 12.3 Better Stack + Vector (searchable logs and alerts)

Create a Better Stack Logs source first and note:
- **Source token**
- **Ingesting host**

Then install Vector on the VM (Ubuntu example):
- fastest path: Better Stack Vector setup script for Ubuntu (from Better Stack docs)
- alternative: install Vector from the official Vector packages/docs

After Vector is installed, wire it to this repo template:

```bash
sudo cp /opt/active-workbench/deploy/vector/vector.betterstack.yaml.example /etc/vector/vector.yaml
sudo cp /opt/active-workbench/deploy/env/vector.env.example /etc/active-workbench/vector.env
sudo mkdir -p /etc/systemd/system/vector.service.d
sudo cp /opt/active-workbench/deploy/systemd/vector.service.d/override.conf.example /etc/systemd/system/vector.service.d/override.conf
sudo chown root:root /etc/vector/vector.yaml /etc/systemd/system/vector.service.d/override.conf
sudo chown root:active-workbench /etc/active-workbench/vector.env
sudo chmod 640 /etc/active-workbench/vector.env
```

Edit `/etc/active-workbench/vector.env`:
- `BETTER_STACK_INGESTING_HOST`
- `BETTER_STACK_SOURCE_TOKEN`
- `ACTIVE_WORKBENCH_DEPLOYMENT_ENV`

Give the `vector` user access to the needed logs/journal:

```bash
sudo usermod -aG adm,systemd-journal,active-workbench vector
```

Restart Vector after group/env changes:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now vector
sudo systemctl restart vector
sudo systemctl status vector --no-pager
sudo journalctl -u vector -n 100 --no-pager
```

The provided Vector config ships:
- Active Workbench runtime log file
- Active Workbench telemetry log file
- Nginx access/error logs
- `opencode-serve.service` logs from `journald`

Notes:
- Vector is configured with `read_from: end` and `since_now: true` to avoid surprise historical ingest/cost on first boot.
- Backend app logs are shipped from files (not backend `journald`) to avoid duplicates.
- The Nginx template forwards `X-Request-ID` to upstreams so backend request/telemetry IDs can be correlated with edge requests.

### 12.4 Suggested monitors and alerts

Uptime checks:
- `https://api.example.com/health` expecting `200`
- `https://chat.example.com/` expecting `401` (healthy auth challenge) unless your uptime provider supports authenticated checks

Log alerts (high signal):
- backend `level=error` spike
- mobile share `401` spike
- mobile share `429` spike
- `opencode-serve.service` crash/restart patterns
- nginx `5xx` spike

### 12.5 Optional next step: Better Stack Error Tracking

If you want Sentry-style exception tracking later:
- add Better Stack Error Tracking (Sentry SDK-compatible) for backend exceptions
- keep current telemetry and logs; error tracking complements both
