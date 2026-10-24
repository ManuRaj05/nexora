from uuid import uuid4
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List
import httpx
from fastapi import HTTPException
from database import get_connection

app = FastAPI()

class OrderItemCreate(BaseModel):
    product_id: int
    quantity: int


class OrderCreate(BaseModel):
    user_id: int
    items: List[OrderItemCreate]

@app.get("/")
def root():
    return {"message": "Nexora Order Service is running"}


@app.get("/health")
def health():
    return {"status": "healthy"}

def release_reserved_stock(reserved_items):
    all_released = True

    for item in reversed(reserved_items):
        error_message = None

        try:
            response = httpx.post(
                f"http://127.0.0.1:8001/products/{item['product_id']}/release",
                params={
                    "quantity": item["quantity"],
                    "reservation_id": item["reservation_id"]
                },
                timeout=5.0
            )

            if (
                response.status_code == 200
                and response.json().get("status") == "RELEASED"
            ):
                continue

            error_message = (
                f"Product Service returned HTTP {response.status_code}: "
                f"{response.text}"
            )

        except httpx.RequestError as exc:
            error_message = f"Product Service request failed: {exc}"

        all_released = False
        print(
            f"WARNING: Stock release failed for product "
            f"{item['product_id']}: {error_message}"
        )

        try:
            with get_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO reconciliation_tasks
                        (reservation_id, product_id, quantity, action,
                         status, last_error)
                        VALUES (%s, %s, %s, 'RELEASE', 'PENDING', %s)
                        ON CONFLICT (reservation_id, action)
                        DO UPDATE SET
                            status = CASE
                                WHEN reconciliation_tasks.status = 'COMPLETED'
                                THEN 'COMPLETED'
                                ELSE 'PENDING'
                            END,
                            next_retry_at = CASE
                                WHEN reconciliation_tasks.status = 'COMPLETED'
                                THEN reconciliation_tasks.next_retry_at
                                ELSE CURRENT_TIMESTAMP
                            END,
                            last_error = CASE
                                WHEN reconciliation_tasks.status = 'COMPLETED'
                                THEN reconciliation_tasks.last_error
                                ELSE EXCLUDED.last_error
                            END,
                            updated_at = CURRENT_TIMESTAMP;
                        """,
                        (
                            item["reservation_id"],
                            item["product_id"],
                            item["quantity"],
                            error_message[:2000]
                        )
                    )

            print(
                f"Reconciliation task saved for reservation "
                f"{item['reservation_id']}"
            )

        except Exception as db_error:
            print(
                f"CRITICAL: Could not save reconciliation task for "
                f"reservation {item['reservation_id']}: {db_error}"
            )

    return all_released

@app.post("/orders")
def create_order(order: OrderCreate):

    if not order.items:
        raise HTTPException(
            status_code=400,
            detail="Order must contain at least one item"
        )

    try:
        user_response = httpx.get(
            f"http://127.0.0.1:8000/users/{order.user_id}",
            timeout=5.0
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="User Service timed out"
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail="User Service is unavailable"
        )

    if user_response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail="User Service request failed"
        )

    user = user_response.json()

    if isinstance(user, dict) and "error" in user:
        raise HTTPException(
            status_code=404,
            detail=f"User {order.user_id} not found"
        )

    if not isinstance(user, list) or not user or user[0] != order.user_id:
        raise HTTPException(
            status_code=404,
            detail=f"User {order.user_id} not found"
        )

    total_amount = 0
    validated_items = []
    reserved_items = []

    for item in order.items:
        try:
            response = httpx.get(
                f"http://127.0.0.1:8001/products/{item.product_id}",
                timeout=5.0
            )
        
        except httpx.TimeoutException:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service timed out, and stock compensation "
                        "was incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=504,
                detail="Product Service timed out; reserved stock was released"
            )

        
        except httpx.RequestError:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service is unavailable, and stock compensation "
                        "was incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=503,
                detail="Product Service is unavailable; reserved stock was released"
            )
        
        if response.status_code != 200:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service request failed, and stock compensation "
                        "was incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=502,
                detail="Product Service request failed; reserved stock was released"
            )

        product = response.json()

        
        if "error" in product:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product not found, and stock compensation was "
                        "incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found; reserved stock was released"
            )
        
        if item.quantity <= 0:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Invalid quantity, and stock compensation was "
                        "incomplete. Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=400,
                detail="Quantity must be greater than zero; reserved stock was released"
            )

        reservation_id = str(uuid4())

        try:
            reserve_response = httpx.post(
                f"http://127.0.0.1:8001/products/{item.product_id}/reserve",
                params={
                    "quantity": item.quantity,
                    "reservation_id": reservation_id
                },
                timeout=5.0
            )

        except httpx.TimeoutException:
            try:
                reserve_response = httpx.post(
                    f"http://127.0.0.1:8001/products/{item.product_id}/reserve",
                    params={
                        "quantity": item.quantity,
                        "reservation_id": reservation_id
                    },
                    timeout=5.0
                )

            
            except httpx.RequestError:
                released = release_reserved_stock([
                    *reserved_items,
                    {
                        "product_id": item.product_id,
                        "quantity": item.quantity,
                        "reservation_id": reservation_id
                    }
                ])

                if not released:
                    raise HTTPException(
                        status_code=500,
                        detail=(
                            "Reservation outcome is uncertain, and compensation "
                            "was incomplete. Manual reconciliation is required."
                        )
                    )

                raise HTTPException(
                    status_code=504,
                    detail=(
                        "Reservation outcome was uncertain. Compensation was attempted; "
                        "verify the reservation status before retrying."
                    )
                )

        except httpx.RequestError:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product Service is unavailable during stock reservation, "
                        "and stock compensation was incomplete. "
                        "Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=503,
                detail=(
                    "Product Service is unavailable during stock reservation; "
                    "previous reservations were released."
                )
            )

        if reserve_response.status_code == 409:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Stock reservation failed, and compensation was incomplete. "
                        "Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=409,
                detail=f"Insufficient stock for product {item.product_id}"
            )

        if reserve_response.status_code == 404:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Product was not found during reservation, and "
                        "compensation was incomplete. "
                        "Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=404,
                detail=f"Product {item.product_id} not found"
            )

        if reserve_response.status_code != 200:
            released = release_reserved_stock(reserved_items)

            if not released:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Stock reservation failed, and compensation was incomplete. "
                        "Manual reconciliation is required."
                    )
                )

            raise HTTPException(
                status_code=502,
                detail="Stock reservation failed; previous reservations were released"
            )

        reserved_items.append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "reservation_id": reservation_id
        })

        price = float(product[3])
        total_amount += price * item.quantity

        validated_items.append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "price": price
        })

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO orders (user_id, total_amount)
                    VALUES (%s, %s)
                    RETURNING id, user_id, total_amount, status, created_at;
                    """,
                    (order.user_id, total_amount)
                )
                new_order = cursor.fetchone()

                for item in validated_items:
                    cursor.execute(
                        """
                        INSERT INTO order_items
                        (order_id, product_id, quantity, price)
                        VALUES (%s, %s, %s, %s);
                        """,
                        (
                            new_order[0],
                            item["product_id"],
                            item["quantity"],
                            item["price"]
                        )
                    )
    
    except Exception as error:
        released = release_reserved_stock(reserved_items)

        print(f"Order database transaction failed: {error}")

        if not released:
            print(
                "CRITICAL: Some stock reservations may remain active. "
                "Manual reconciliation is required."
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Order creation failed, and stock compensation "
                    "was incomplete. Manual reconciliation is required."
                )
            )

        raise HTTPException(
            status_code=500,
            detail="Order creation failed; reserved stock was released"
        )

    return {
        "id": new_order[0],
        "user_id": new_order[1],
        "total_amount": float(new_order[2]),
        "status": new_order[3],
        "items": validated_items
    }

@app.get("/orders/{order_id}")
def get_order(order_id: int):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, total_amount, status, created_at
                FROM orders
                WHERE id = %s;
                """,
                (order_id,)
            )
            order = cursor.fetchone()

            if order is None:
                raise HTTPException(
                    status_code=404,
                    detail="Order not found"
                )

            cursor.execute(
                """
                SELECT product_id, quantity, price
                FROM order_items
                WHERE order_id = %s;
                """,
                (order_id,)
            )
            items = cursor.fetchall()

    return {
        "id": order[0],
        "user_id": order[1],
        "total_amount": float(order[2]),
        "status": order[3],
        "created_at": order[4],
        "items": [
            {
                "product_id": item[0],
                "quantity": item[1],
                "price": float(item[2])
            }
            for item in items
        ]
    }

@app.get("/orders")
def get_orders():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, total_amount, status, created_at
                FROM orders
                ORDER BY id;
                """
            )
            orders = cursor.fetchall()

            result = []

            for order in orders:
                cursor.execute(
                    """
                    SELECT product_id, quantity, price
                    FROM order_items
                    WHERE order_id = %s;
                    """,
                    (order[0],)
                )
                items = cursor.fetchall()

                result.append({
                    "id": order[0],
                    "user_id": order[1],
                    "total_amount": float(order[2]),
                    "status": order[3],
                    "created_at": order[4],
                    "items": [
                        {
                            "product_id": item[0],
                            "quantity": item[1],
                            "price": float(item[2])
                        }
                        for item in items
                    ]
                })

    return result