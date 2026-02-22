# Active Workbench Deployment (Nginx + systemd + Hetzner-style VM)

**Updated:** 2026-02-22

This runbook deploys:
- Active Workbench backend on `127.0.0.1:8000`
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
