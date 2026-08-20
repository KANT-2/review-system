#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 0 ]]; then
  echo "usage: remote_deploy.sh" >&2
  exit 2
fi

release_dir="$(pwd -P)"
release_env="$release_dir/.env.production"

if [[ ! "$release_dir" =~ ^/home/[a-z_][a-z0-9_-]*/services/review-system/releases/[0-9a-f]{40}$ ]]; then
  echo "unexpected release directory: $release_dir" >&2
  exit 2
fi
if [[ ! -L "$release_env" ]]; then
  echo "release .env.production must be a symbolic link" >&2
  exit 2
fi
env_file="$(realpath "$release_env")"
if [[ ! "$env_file" =~ ^/home/[a-z_][a-z0-9_-]*/services/review-system/shared/\.env\.production$ ]]; then
  echo "unexpected production env path" >&2
  exit 2
fi
if [[ ! -f "$env_file" || "$(stat -c '%a' "$env_file")" != "600" ]]; then
  echo "production env file must exist with mode 600" >&2
  exit 2
fi

deploy_root="$(dirname "$(dirname "$release_dir")")"
compose=(sudo -n docker compose --env-file .env.production -f compose.production.yaml)

"${compose[@]}" config --quiet
"${compose[@]}" build app caddy
"${compose[@]}" up -d db
"${compose[@]}" run --rm app python manage.py migrate --noinput
"${compose[@]}" run --rm app python manage.py check --deploy --fail-level WARNING
"${compose[@]}" up -d --wait --wait-timeout 120 app scheduler caddy

healthy=false
for _ in {1..18}; do
  if curl --fail --silent --show-error --max-time 10 \
    https://oaknamu.com/accounts/login/ >/dev/null; then
    healthy=true
    break
  fi
  sleep 5
done
if [[ "$healthy" != true ]]; then
  "${compose[@]}" ps
  echo "production HTTPS health check failed" >&2
  exit 1
fi

ln -sfn "$release_dir" "$deploy_root/current"
"${compose[@]}" ps
echo "Production deployment completed for $(basename "$release_dir")"
