import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
import main as product_service


class AdminAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.product = product_service.ProductCreate(
            name="Test", description="Test description", price=12.5, stock=3, category="Test",
        )
        self.update = product_service.ProductUpdate(
            name="Updated", description="Updated description", price=14, stock=4, category="Test",
        )
        self.gateway = Mock()
        self.gateway.status_code = 200
        self.gateway.json.return_value = {"user_id": 7, "role": "ADMIN"}
        self.user_lookup = Mock(return_value=self.gateway)
        self.http_patch = patch.object(product_service.httpx, "get", self.user_lookup)
        self.http_patch.start()
        self.addCleanup(self.http_patch.stop)
        self.db_patch = patch.object(product_service, "get_connection")
        self.get_connection = self.db_patch.start()
        self.addCleanup(self.db_patch.stop)

    def test_missing_and_invalid_credentials_are_401(self):
        for authorization in (None, "Basic abc", "Bearer invalid"):
            with self.subTest(authorization=authorization):
                if authorization == "Bearer invalid":
                    self.gateway.status_code = 401
                with self.assertRaises(HTTPException) as denied:
                    product_service.require_admin(authorization)
                self.assertEqual(denied.exception.status_code, 401)
        self.get_connection.assert_not_called()

    def test_customer_is_forbidden_even_if_request_contains_admin_claim_text(self):
        self.gateway.status_code = 200
        self.gateway.json.return_value = {"user_id": 7, "role": "CUSTOMER"}
        with self.assertRaises(HTTPException) as denied:
            product_service.create_product(self.product, "Bearer signed-customer-token")
        self.assertEqual(denied.exception.status_code, 403)
        self.get_connection.assert_not_called()

    def test_user_service_outage_fails_closed(self):
        self.user_lookup.side_effect = product_service.httpx.RequestError("offline")
        with self.assertRaises(HTTPException) as denied:
            product_service.require_admin("Bearer token")
        self.assertEqual(denied.exception.status_code, 503)

    def test_create_update_and_delete_require_admin_and_reach_database_only_after_verification(self):
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchone.side_effect = [
            (11, "Test", "Test description", 12.5, 3, "Test"),
            (11, "Updated", "Updated description", 14, 4, "Test"),
            (11,),
            (False,),
            (11,),
        ]
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.cursor.return_value = cursor
        self.get_connection.return_value = connection

        created = product_service.create_product(self.product, "Bearer admin-token")
        updated = product_service.update_product(11, self.update, "Bearer admin-token")
        deleted = product_service.delete_product(11, "Bearer admin-token")

        self.assertEqual(created[0], 11)
        self.assertEqual(updated[0], 11)
        self.assertEqual(deleted["product_id"], 11)
        self.assertEqual(self.user_lookup.call_count, 3)
        self.assertEqual(self.get_connection.call_count, 3)

    def test_product_with_active_reservation_cannot_be_deleted(self):
        cursor = Mock()
        cursor.__enter__ = Mock(return_value=cursor)
        cursor.__exit__ = Mock(return_value=False)
        cursor.fetchone.side_effect = [(11,), (True,)]
        connection = Mock()
        connection.__enter__ = Mock(return_value=connection)
        connection.__exit__ = Mock(return_value=False)
        connection.cursor.return_value = cursor
        self.get_connection.return_value = connection

        with self.assertRaises(HTTPException) as denied:
            product_service.delete_product(11, "Bearer admin-token")

        self.assertEqual(denied.exception.status_code, 409)
        self.assertIn("active stock reservations", denied.exception.detail.lower())
        queries = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
        self.assertTrue(any("FOR UPDATE" in query for query in queries))
        self.assertFalse(any("DELETE FROM products" in query for query in queries))


if __name__ == "__main__":
    unittest.main()
