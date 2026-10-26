import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import jwt
import bcrypt
from pydantic import ValidationError

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
import main as user_service


TEST_SECRET = os.urandom(32).hex()


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = ""
        self.params = ()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=()):
        self.query = " ".join(query.split())
        self.params = params

    def fetchone(self):
        if self.query.startswith("SELECT") and "password_hash" in self.query:
            return (2, "admin", "admin@example.test", self.rows[2][4])
        if "WHERE id = %s" in self.query:
            return self.rows.get(self.params[0])
        if "RETURNING id,username,email,role" in self.query:
            return (9, "new-customer", self.params[1], "CUSTOMER")
        if "COUNT(*)" in self.query:
            return (0,)
        return None

    def fetchall(self):
        return list(self.rows.values())


class FakeConnection:
    def __init__(self, cursor):
        self.fake_cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.fake_cursor


class UserRoleTests(unittest.TestCase):
    def setUp(self):
        self.rows = {
            1: (1, "customer", "customer@example.test", "CUSTOMER", None),
            2: (2, "admin", "admin@example.test", "ADMIN", bcrypt.hashpw(b"admin-test-password", bcrypt.gensalt()).decode()),
        }
        self.cursor = FakeCursor(self.rows)
        self.connection = FakeConnection(self.cursor)
        self.db_patch = patch.object(user_service, "get_connection", return_value=self.connection)
        self.db_patch.start()
        self.env_patch = patch.dict(os.environ, {"JWT_SECRET": TEST_SECRET})
        self.env_patch.start()

    def tearDown(self):
        self.db_patch.stop()
        self.env_patch.stop()

    def token(self, user_id=1, role="ADMIN"):
        return jwt.encode({"user_id": user_id, "role": role, "exp": 4_000_000_000}, TEST_SECRET, algorithm="HS256")

    def test_registration_ignores_no_role_and_inserts_customer_by_database_default(self):
        response = user_service.register_user(user_service.UserCreate(
            username="new-customer", email="new@example.test", password="not-a-real-password",
        ))
        self.assertEqual(response[3], "CUSTOMER")
        self.assertIn("INSERT INTO users (username, email, password_hash)", self.cursor.query)
        self.assertEqual(len(self.cursor.params), 3)

    def test_registration_rejects_attempt_to_supply_admin_role(self):
        with self.assertRaises(ValidationError):
            user_service.UserCreate.model_validate({
                "username": "attacker", "email": "attacker@example.test", "password": "x", "role": "ADMIN",
            })

    def test_me_uses_database_role_instead_of_signed_role_claim(self):
        current = user_service.get_current_user(user_service.HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=self.token(role="ADMIN"),
        ))
        response = user_service.get_current_user_endpoint(current)
        self.assertEqual(response["role"], "CUSTOMER")

    def test_expired_token_is_rejected_and_missing_secret_fails_closed(self):
        expired = jwt.encode({"user_id": 1, "exp": 1}, TEST_SECRET, algorithm="HS256")
        with self.assertRaises(user_service.HTTPException) as invalid:
            user_service.get_current_user(user_service.HTTPAuthorizationCredentials(
                scheme="Bearer", credentials=expired,
            ))
        self.assertEqual(invalid.exception.status_code, 401)
        with patch.dict(os.environ, {"JWT_SECRET": ""}):
            with self.assertRaises(user_service.HTTPException) as unavailable:
                user_service.verify_token(self.token())
        self.assertEqual(unavailable.exception.status_code, 503)

    def test_admin_identity_is_accepted_and_customer_identity_is_denied(self):
        admin = user_service.get_current_user(user_service.HTTPAuthorizationCredentials(scheme="Bearer", credentials=self.token(2, "CUSTOMER")))
        self.assertEqual(admin["role"], "ADMIN")
        with self.assertRaises(user_service.HTTPException) as denied:
            user_service.require_admin(user_service.get_current_user(user_service.HTTPAuthorizationCredentials(scheme="Bearer", credentials=self.token(1, "ADMIN"))))
        self.assertEqual(denied.exception.status_code, 403)

    def test_valid_admin_login_issues_a_short_lived_token_and_admin_is_authorized(self):
        result = user_service.login_user(user_service.UserLogin(
            email="admin@example.test", password="admin-test-password",
        ))
        payload = jwt.decode(result["token"], TEST_SECRET, algorithms=["HS256"])
        self.assertEqual(payload["user_id"], 2)
        self.assertNotIn("role", payload)
        identity = user_service.get_current_user(user_service.HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=result["token"],
        ))
        self.assertEqual(user_service.require_admin(identity)["role"], "ADMIN")

    def test_user_listing_requires_authentication_and_admin_role(self):
        with self.assertRaises(user_service.HTTPException) as missing:
            user_service.get_current_user(None)
        self.assertEqual(missing.exception.status_code, 401)
        customer = user_service.get_current_user(user_service.HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=self.token(1),
        ))
        with self.assertRaises(user_service.HTTPException) as denied:
            user_service.require_admin(customer)
        self.assertEqual(denied.exception.status_code, 403)
        admin = user_service.get_current_user(user_service.HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=self.token(2),
        ))
        self.assertEqual(len(user_service.get_users(user_service.require_admin(admin))), 2)

    def test_profile_lookup_is_self_or_admin_only(self):
        own = user_service.get_current_user(user_service.HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=self.token(1),
        ))
        self.assertEqual(user_service.get_user(1, own)[0], 1)
        with self.assertRaises(user_service.HTTPException) as denied:
            user_service.get_user(2, own)
        self.assertEqual(denied.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
