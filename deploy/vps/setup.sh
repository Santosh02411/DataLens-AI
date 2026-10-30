#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu/Debian VPS. Run from the repository root:
#   sudo bash deploy/vps/setup.sh yourdomain.com      (or without a domain: plain HTTP on port 80)
set -euo pipefail
DOMAIN="${1:-}"
cd "$(dirname "$0")/../.."
if ! command -v docker >/dev/null 2>&1; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  read -r -p "Paste your Gemini API key (from https://aistudio.google.com/apikey): " KEY
  sed -i "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=${KEY}|" backend/.env
  chmod 600 backend/.env
fi
cd deploy/vps
if [ -n "$DOMAIN" ]; then export DOMAIN; fi
docker compose up -d --build
echo
echo "DataLens AI is starting. It will restart automatically after crashes and reboots."
if [ -n "$DOMAIN" ]; then echo "Open https://$DOMAIN (point the domain's A record at this server first)."; else echo "Open http://$(curl -s ifconfig.me || echo YOUR_SERVER_IP)"; fi
echo "Logs:   docker compose -f deploy/vps/docker-compose.yml logs -f app"
echo "Update: git pull && docker compose -f deploy/vps/docker-compose.yml up -d --build"
