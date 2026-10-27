#!/usr/bin/env bash
set -Eeuo pipefail

psql --set ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname=nexora_users \
    --file=/schema/user-service.sql
psql --set ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname=nexora_products \
    --file=/schema/product-service.sql
psql --set ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname=nexora_orders \
    --file=/schema/order-service.sql
