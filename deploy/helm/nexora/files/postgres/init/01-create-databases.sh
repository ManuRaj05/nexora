#!/usr/bin/env bash
set -Eeuo pipefail

createdb --maintenance-db=postgres --username="$POSTGRES_USER" nexora_users
createdb --maintenance-db=postgres --username="$POSTGRES_USER" nexora_products
createdb --maintenance-db=postgres --username="$POSTGRES_USER" nexora_orders
