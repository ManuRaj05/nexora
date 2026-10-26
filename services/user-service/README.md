# User Service database setup

## Fresh database

For a new, empty User Service database, apply `schema.sql` once. It creates the
final `public.users` table, including the identity, unique keys, role check, and
nullable `created_at` column. It is intentionally a clean-install schema and
fails if `public.users` already exists. It is not run by service startup.

## Legacy database upgrade

For an existing legacy `users` table, apply
`migrations/001_user_roles.sql` after reviewing that database's schema. Do not
run it as the clean-install procedure. The upgrade normalizes only NULL or
unsupported role values to `CUSTOMER`, sets the role default and NOT NULL rule,
and adds the allowed-role check if missing. It preserves valid `ADMIN` values
and is safe to rerun; it never demotes a valid administrator.

No User Service setup or startup script automatically runs either SQL file.
Keep schema setup as an explicit database-administration step. Never use a
destructive reset as part of application startup.

## First administrator

Register the intended account through the normal registration flow. Then run
`venv/bin/python provision_admin.py <account-email>` from this service directory
on a trusted host with the User Service database configuration available. The
command requires a typed confirmation, takes a transaction-level lock, and
promotes the account only when no administrator exists. It does not accept or
store a password. Log in again or refresh the identity request after promotion
to obtain the current database-backed role in the application.
