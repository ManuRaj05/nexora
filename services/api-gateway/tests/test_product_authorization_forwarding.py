import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
import main as gateway


class ProductAuthorizationForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_update_and_delete_forward_authorization_header(self):
        request = SimpleNamespace(headers={"Authorization": "Bearer opaque-test-token"})
        create = gateway.ProductCreate(name="Name", description="Description", price=1, stock=2, category="Test")
        update = gateway.ProductUpdate(name="Name", description="Description", price=1, stock=2, category="Test")
        with patch.object(gateway, "forward_request", new_callable=AsyncMock, return_value={"ok": True}) as forward:
            await gateway.create_product(create, request)
            await gateway.update_product(7, update, request)
            await gateway.delete_product(7, request)

        calls = forward.await_args_list
        self.assertEqual(calls[0].kwargs["headers"], {"Authorization": "Bearer opaque-test-token"})
        self.assertEqual(calls[1].kwargs["headers"], {"Authorization": "Bearer opaque-test-token"})
        self.assertEqual(calls[2].kwargs["headers"], {"Authorization": "Bearer opaque-test-token"})
        self.assertEqual(calls[2].args[0], "DELETE")

    async def test_registration_schema_rejects_role_input(self):
        with self.assertRaises(ValueError):
            gateway.UserCreate.model_validate({
                "username": "customer", "email": "customer@example.test", "password": "example", "role": "ADMIN",
            })


if __name__ == "__main__":
    unittest.main()
