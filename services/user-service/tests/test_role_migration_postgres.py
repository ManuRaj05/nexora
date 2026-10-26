"""Opt-in migration check; requires an explicitly disposable PostgreSQL database."""

import os
import unittest
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg
from psycopg import sql


MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_user_roles.sql"
SCHEMA = Path(__file__).resolve().parents[1] / "schema.sql"
RUN_TEST = os.getenv("NEXORA_RUN_DISPOSABLE_ROLE_MIGRATION_TEST") == "1"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@unittest.skipUnless(RUN_TEST and TEST_DATABASE_URL, "requires explicit disposable PostgreSQL test opt-in")
class RoleMigrationPostgresTests(unittest.TestCase):
    def test_legacy_role_upgrade_preserves_valid_admins_and_migration_reruns(self):
        database_name = urlparse(TEST_DATABASE_URL).path.lstrip("/")
        if not database_name.endswith("_test"):
            self.skipTest("database name must end in _test to guard against development databases")

        schema_name = f"nexora_roles_test_{uuid4().hex}"
        connection = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
                cursor.execute(
                    """
                    CREATE TABLE users (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL,
                        email TEXT NOT NULL,
                        password_hash TEXT NOT NULL,
                        role TEXT
                    );
                    INSERT INTO users (username, email, password_hash, role) VALUES
                        ('customer', 'customer@example.test', 'hash', 'CUSTOMER'),
                        ('admin', 'admin@example.test', 'hash', 'ADMIN'),
                        ('legacy-null', 'null@example.test', 'hash', NULL),
                        ('legacy-unknown', 'unknown@example.test', 'hash', 'legacy');
                    """
                )
                cursor.execute(MIGRATION.read_text())
                cursor.execute("SELECT username, role FROM users ORDER BY id;")
                self.assertEqual(cursor.fetchall(), [
                    ("customer", "CUSTOMER"),
                    ("admin", "ADMIN"),
                    ("legacy-null", "CUSTOMER"),
                    ("legacy-unknown", "CUSTOMER"),
                ])
                cursor.execute(
                    "INSERT INTO users (username, email, password_hash) "
                    "VALUES ('new', 'new@example.test', 'hash') RETURNING role;"
                )
                self.assertEqual(cursor.fetchone()[0], "CUSTOMER")
                with self.assertRaises(psycopg.errors.CheckViolation):
                    cursor.execute(
                        "INSERT INTO users (username, email, password_hash, role) "
                        "VALUES ('bad', 'bad@example.test', 'hash', 'OWNER');"
                    )
                cursor.execute(MIGRATION.read_text())
                cursor.execute("SELECT username, role FROM users ORDER BY id;")
                self.assertEqual(cursor.fetchall()[:4], [
                    ("customer", "CUSTOMER"),
                    ("admin", "ADMIN"),
                    ("legacy-null", "CUSTOMER"),
                    ("legacy-unknown", "CUSTOMER"),
                ])
        finally:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
            connection.close()

    def test_clean_install_schema_matches_verified_table_shape(self):
        database_name = urlparse(TEST_DATABASE_URL).path.lstrip("/")
        if not database_name.endswith("_test"):
            self.skipTest("database name must end in _test to guard against development databases")

        schema_name = f"nexora_clean_schema_test_{uuid4().hex}"
        connection = psycopg.connect(TEST_DATABASE_URL, autocommit=True)
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
                clean_install_sql = SCHEMA.read_text().replace("public.users", "users")
                cursor.execute(clean_install_sql)
                cursor.execute(
                    "SELECT column_name, data_type, is_nullable, column_default, is_identity, identity_generation "
                    "FROM information_schema.columns WHERE table_schema=%s AND table_name='users' ORDER BY ordinal_position;",
                    (schema_name,),
                )
                columns = cursor.fetchall()
                self.assertEqual([row[0] for row in columns], [
                    "id", "username", "email", "password_hash", "role", "created_at",
                ])
                self.assertEqual(columns[0][1:3], ("integer", "NO"))
                self.assertEqual(columns[0][4:6], ("YES", "BY DEFAULT"))
                self.assertEqual(columns[1][1:3], ("character varying", "NO"))
                self.assertEqual(columns[2][1:3], ("character varying", "NO"))
                self.assertEqual(columns[3][1:3], ("character varying", "NO"))
                self.assertEqual(columns[4][1:3], ("character varying", "NO"))
                self.assertEqual(columns[4][3], "'CUSTOMER'::character varying")
                self.assertEqual(columns[5][1:3], ("timestamp without time zone", "YES"))
                self.assertEqual(columns[5][3], "CURRENT_TIMESTAMP")
                cursor.execute(
                    "SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass "
                    "AND contype IN ('p', 'u', 'c') ORDER BY conname;",
                    (f"{schema_name}.users",),
                )
                self.assertEqual({row[0] for row in cursor.fetchall()}, {
                    "users_email_key", "users_pkey", "users_role_check", "users_username_key",
                })
        finally:
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema_name)))
            connection.close()


if __name__ == "__main__":
    unittest.main()
