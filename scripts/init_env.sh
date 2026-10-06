#!/bin/bash
# Create .env from .env.example with generated local secrets. Never overwrites an existing .env.
# Prints variable NAMES only, never values (RULEBOOK §14, AI-12).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f .env ]; then
  echo ".env already exists; leaving it unchanged."
  exit 0
fi
gen() { openssl rand -hex "$1"; }
umask 077
sed \
  -e "s|^INFLUXDB_ORG=.*|INFLUXDB_ORG=digital-twin-sdn|" \
  -e "s|^INFLUXDB_ADMIN_USER=.*|INFLUXDB_ADMIN_USER=admin|" \
  -e "s|^INFLUXDB_ADMIN_PASSWORD=.*|INFLUXDB_ADMIN_PASSWORD=$(gen 16)|" \
  -e "s|^INFLUXDB_TOKEN=.*|INFLUXDB_TOKEN=$(gen 32)|" \
  -e "s|^GRAFANA_ADMIN_USER=.*|GRAFANA_ADMIN_USER=admin|" \
  -e "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(gen 16)|" \
  -e "s|^OPERATOR_TOKEN=.*|OPERATOR_TOKEN=$(gen 32)|" \
  .env.example > .env
echo "Created .env (mode 600) with generated values for:"
echo "  INFLUXDB_ADMIN_PASSWORD INFLUXDB_TOKEN GRAFANA_ADMIN_PASSWORD OPERATOR_TOKEN"
echo "Fill in the LLM API keys yourself. Never commit .env."
