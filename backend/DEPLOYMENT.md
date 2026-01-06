# Backend Deployment Guide

## Local Development

### Setup
```bash
cd ~/Projects/active-workbench/backend
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Run
```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8765
```

### Test
```bash
# Health check
curl http://localhost:8765/api/health

# Capture test note
curl -X POST http://localhost:8765/api/capture \
  -H "Content-Type: application/json" \
  -d '{"text": "Test note from API"}'

# Check limbo directory
ls ~/vault/limbo/
```

## VPS Deployment

### Prerequisites
- VPS with Ubuntu/Debian
- Python 3.12+
- Git
- uv installed

### Step 1: Create Service User

```bash
# On VPS
sudo useradd -m -s /bin/bash vault
sudo su - vault
```

### Step 2: Clone and Setup

```bash
# As vault user
mkdir -p ~/workbench
cd ~/workbench

# Clone backend (or copy files)
git clone <your-repo> backend
cd backend

# Install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Step 3: Setup Vault Directory

```bash
# As vault user
mkdir -p ~/vault/limbo
cd ~/vault
git init
git remote add origin git@github.com:yourusername/vault.git

# Setup SSH key for git push
ssh-keygen -t ed25519 -C "vault@vps"
# Add public key to GitHub
```

### Step 4: Configure

```bash
# Create config
mkdir -p ~/.config/workbench
cat > ~/.config/workbench/config.yaml <<EOF
vault_path: /home/vault/vault
host: 0.0.0.0
port: 8765
EOF
```

### Step 5: Install Systemd Service

```bash
# As root/sudo
sudo cp /home/vault/workbench/backend/workbench.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable workbench
sudo systemctl start workbench
```

### Step 6: Check Status

```bash
# Check service
sudo systemctl status workbench

# View logs
sudo journalctl -u workbench -f

# Test from outside
curl http://your-vps-ip:8765/api/health
```

### Step 7: HTTPS (Optional but Recommended)

Using Let's Encrypt with certbot:

```bash
# Install certbot
sudo apt install certbot

# Get certificate
sudo certbot certonly --standalone -d vault.yourdomain.com

# Update systemd service to use SSL
sudo nano /etc/systemd/system/workbench.service
```

Change ExecStart to:
```
ExecStart=/home/vault/workbench/backend/.venv/bin/uvicorn src.main:app \
  --host 0.0.0.0 --port 8765 \
  --ssl-keyfile /etc/letsencrypt/live/vault.yourdomain.com/privkey.pem \
  --ssl-certfile /etc/letsencrypt/live/vault.yourdomain.com/fullchain.pem
```

Restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart workbench
```

## Firewall

```bash
# Allow port 8765
sudo ufw allow 8765/tcp

# Or if using standard HTTPS
sudo ufw allow 443/tcp
```

## Git Auto-Sync

The backend automatically commits and pushes new notes if the vault is a git repository.

Ensure SSH key is set up for passwordless push:
```bash
# As vault user
ssh -T git@github.com
# Should succeed without password
```

## Troubleshooting

### Service won't start
```bash
# Check logs
sudo journalctl -u workbench -n 50

# Common issues:
# - Python version mismatch
# - Missing dependencies
# - Incorrect vault path in config
```

### Git push fails
```bash
# As vault user
cd ~/vault
git status
git push

# Check SSH key
ssh -T git@github.com
```

### Port already in use
```bash
# Find what's using port 8765
sudo lsof -i :8765

# Kill it or change port in config
```

## Monitoring

### Logs
```bash
# Real-time logs
sudo journalctl -u workbench -f

# Last 100 lines
sudo journalctl -u workbench -n 100

# Errors only
sudo journalctl -u workbench -p err
```

### Health Check
```bash
# Add to cron for monitoring
*/5 * * * * curl -f http://localhost:8765/api/health || systemctl restart workbench
```

## Updating

```bash
# As vault user
cd ~/workbench/backend
git pull
source .venv/bin/activate
uv pip install -e .

# As root
sudo systemctl restart workbench
```
