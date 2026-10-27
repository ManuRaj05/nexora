#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
env_file="${1:-$repo_root/.env}"
namespace="${NAMESPACE:-nexora}"
context="${KUBE_CONTEXT:-kind-nexora}"
secret_name="${SECRET_NAME:-nexora-runtime}"

if [[ ! -f "$env_file" ]]; then
  printf 'Environment file not found: %s\n' "$env_file" >&2
  exit 1
fi

tmp_env="$(mktemp)"
chmod 600 "$tmp_env"
trap 'rm -f "$tmp_env"' EXIT

python3 - "$env_file" "$tmp_env" <<'PY'
import shlex
import sys
from urllib.parse import quote

source_path, output_path = sys.argv[1:]
settings = {}
with open(source_path, encoding="utf-8") as source:
    for raw_line in source:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise SystemExit("Invalid .env line; expected KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith(("'", '"')):
            parsed = shlex.split(value, comments=True, posix=True)
            if len(parsed) != 1:
                raise SystemExit("Invalid quoted value in .env")
            value = parsed[0]
        else:
            value = value.split(" #", 1)[0].rstrip()
        settings[key] = value

required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "JWT_SECRET", "ORDER_SERVICE_TOKEN")
missing = [key for key in required if not settings.get(key)]
if missing:
    raise SystemExit("Missing required .env setting(s): " + ", ".join(missing))

user = quote(settings["POSTGRES_USER"], safe="")
password = quote(settings["POSTGRES_PASSWORD"], safe="")
values = {
    "POSTGRES_USER": settings["POSTGRES_USER"],
    "POSTGRES_PASSWORD": settings["POSTGRES_PASSWORD"],
    "JWT_SECRET": settings["JWT_SECRET"],
    "ORDER_SERVICE_TOKEN": settings["ORDER_SERVICE_TOKEN"],
    "USER_DATABASE_URL": f"postgresql://{user}:{password}@postgres:5432/nexora_users",
    "PRODUCT_DATABASE_URL": f"postgresql://{user}:{password}@postgres:5432/nexora_products",
    "ORDER_DATABASE_URL": f"postgresql://{user}:{password}@postgres:5432/nexora_orders",
}
with open(output_path, "w", encoding="utf-8") as target:
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise SystemExit("Newlines are not supported in secret values")
        target.write(f"{key}={value}\n")
PY

kubectl --context "$context" -n "$namespace" create secret generic "$secret_name" \
  --from-env-file="$tmp_env" --dry-run=client -o yaml \
  | kubectl --context "$context" apply -f - >/dev/null
printf 'Secret %s is configured in namespace %s.\n' "$secret_name" "$namespace"
