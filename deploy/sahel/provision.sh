#!/usr/bin/env bash
# One-shot setup of the SAHEL COMMERCE installation on the VPS (run by an admin
# of the server, from the unpacked source dir):  bash deploy/sahel/provision.sh
# Idempotent for the env files (never overwrites existing secrets).
set -euo pipefail
cd "$(dirname "$0")"
HOST=sahelcommerce.hasel.food
COMPOSE="docker compose -f docker-compose.sahel.yml"

getent hosts "$HOST" >/dev/null || { echo "DNS: $HOST ne pointe pas encore vers ce serveur"; exit 1; }

if [ ! -f /etc/bessma/sahel-app.env ]; then
  DBPW=$(openssl rand -hex 24)
  SECRET=$(openssl rand -hex 48)
  printf 'POSTGRES_DB=sahel\nPOSTGRES_USER=sahel\nPOSTGRES_PASSWORD=%s\n' "$DBPW" | sudo install -m 600 /dev/stdin /etc/bessma/sahel-db.env
  # Start from the AZUR app env (same settings module, same options), then
  # override everything that is specific to this installation.
  sudo grep -v -E '^(DATABASE_URL|DJANGO_SECRET_KEY|DJANGO_ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|PUBLIC_HOST|BRAND|CORS_ALLOWED_ORIGINS)=' /etc/bessma/fuel-app.env > /tmp/sahel-app.env.$$ || true
  {
    cat /tmp/sahel-app.env.$$
    echo "BRAND=sahel"
    echo "PUBLIC_HOST=$HOST"
    echo "DJANGO_ALLOWED_HOSTS=$HOST,localhost,127.0.0.1"
    echo "CSRF_TRUSTED_ORIGINS=https://$HOST"
    echo "CORS_ALLOWED_ORIGINS=https://$HOST"
    echo "DJANGO_SECRET_KEY=$SECRET"
    echo "DATABASE_URL=postgres://sahel:$DBPW@db:5432/sahel"
  } | sudo install -m 600 /dev/stdin /etc/bessma/sahel-app.env
  sudo install -m 600 /etc/bessma/sahel-app.env /etc/bessma/sahel-migrate.env
  rm -f /tmp/sahel-app.env.$$
fi
sudo mkdir -p /home/bouye/apps/sahel-commerce/media

$COMPOSE build
$COMPOSE up -d db
$COMPOSE --profile tools run --rm migrate
$COMPOSE up -d backend frontend
$COMPOSE ps
echo "Cree l'administrateur :"
echo "  docker compose -f $PWD/docker-compose.sahel.yml exec backend python manage.py createsuperuser"
