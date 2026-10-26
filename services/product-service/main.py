import hmac
import os
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel
from database import get_connection
import httpx
from uuid import UUID

app = FastAPI()

class ProductCreate(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str

class ProductUpdate(BaseModel):
    name: str
    description: str
    price: float
    stock: int
    category: str
  
@app.get("/")
def root():
    return {"message": "Nexora Product Service is running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/products")
def create_product(product: ProductCreate):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO products
                (name, description, price, stock, category)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, description, price, stock, category;
                """,
                (
                    product.name,
                    product.description,
                    product.price,
                    product.stock,
                    product.category
                )
            )
            new_product = cursor.fetchone()

    return new_product

@app.get("/products")
def get_products():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, description, price, stock, category FROM products;"
            )
            products = cursor.fetchall()

    return products

@app.get("/products/{product_id}")
def get_product(product_id: int):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, description, price, stock, category
                FROM products
                WHERE id = %s;
                """,
                (product_id,)
            )
            product = cursor.fetchone()

    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return product

@app.put("/products/{product_id}")
def update_product(product_id: int, product: ProductUpdate):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE products
                SET name = %s,
                    description = %s,
                    price = %s,
                    stock = %s,
                    category = %s
                WHERE id = %s
                RETURNING id, name, description, price, stock, category;
                """,
                (
                    product.name,
                    product.description,
                    product.price,
                    product.stock,
                    product.category,
                    product_id
                )
            )
            updated_product = cursor.fetchone()

    if updated_product is None:
        raise HTTPException(status_code=404, detail="Product not found")    

    return updated_product

@app.delete("/products/{product_id}")
def delete_product(product_id: int):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM products
                WHERE id = %s
                RETURNING id;
                """,
                (product_id,)
            )
            deleted_product = cursor.fetchone()

    if deleted_product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product deleted successfully", "product_id": deleted_product[0]}

def lock_reservation(cursor, reservation_id: UUID):
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0));",
        (str(reservation_id),)
    )

def require_order_service(token):
    expected = os.getenv("ORDER_SERVICE_TOKEN")
    if not expected or not expected.strip():
        raise HTTPException(
            status_code=503,
            detail="Order Service authentication is not configured",
        )
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid service credentials")

def get_reservation_operation(cursor, reservation_id):
    cursor.execute(
        """
        SELECT product_id, quantity, fencing_generation, status, created_at
        FROM reservation_operations
        WHERE reservation_id = %s
        FOR UPDATE;
        """,
        (reservation_id,),
    )
    operation = cursor.fetchone()
    if operation is not None:
        cursor.execute(
            """
            SELECT product_id, quantity, status
            FROM stock_reservations
            WHERE reservation_id = %s
            FOR UPDATE;
            """,
            (reservation_id,),
        )
        reservation = cursor.fetchone()
        if operation[3] == "CANCELLED":
            if reservation is not None:
                raise HTTPException(status_code=409, detail="Reservation ledger is inconsistent")
        elif (
            reservation is None
            or reservation[0] != operation[0]
            or reservation[1] != operation[1]
            or reservation[2] != operation[3]
        ):
            raise HTTPException(status_code=409, detail="Reservation ledger is inconsistent")
        return operation

    # Compatibility fallback for reservations written before the ledger existed.
    cursor.execute(
        """
        SELECT product_id, quantity, status, created_at
        FROM stock_reservations
        WHERE reservation_id = %s
        FOR UPDATE;
        """,
        (reservation_id,),
    )
    legacy = cursor.fetchone()
    if legacy is None:
        return None
    if legacy[2] not in ("RESERVED", "RELEASED"):
        raise HTTPException(status_code=409, detail="Legacy reservation state is inconsistent")

    cursor.execute(
        """
        INSERT INTO reservation_operations
            (reservation_id, product_id, quantity, fencing_generation, status, created_at)
        VALUES (%s, %s, %s, 0, %s, COALESCE(%s, CURRENT_TIMESTAMP))
        ON CONFLICT (reservation_id) DO NOTHING;
        """,
        (reservation_id, legacy[0], legacy[1], legacy[2], legacy[3]),
    )
    cursor.execute(
        """
        SELECT product_id, quantity, fencing_generation, status, created_at
        FROM reservation_operations
        WHERE reservation_id = %s
        FOR UPDATE;
        """,
        (reservation_id,),
    )
    return cursor.fetchone()

def validate_operation(operation, product_id, quantity, fencing_generation):
    if operation[0] != product_id or operation[1] != quantity:
        raise HTTPException(status_code=409, detail="Reservation details do not match")
    if fencing_generation < operation[2]:
        raise HTTPException(status_code=409, detail="Stale reservation fencing generation")

def update_operation(cursor, reservation_id, product_id, quantity, fencing_generation, status):
    cursor.execute(
        """
        INSERT INTO reservation_operations
            (reservation_id, product_id, quantity, fencing_generation, status)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (reservation_id) DO UPDATE
        SET fencing_generation = EXCLUDED.fencing_generation,
            status = EXCLUDED.status,
            updated_at = CURRENT_TIMESTAMP
        WHERE reservation_operations.fencing_generation <= EXCLUDED.fencing_generation
          AND (
              reservation_operations.status = EXCLUDED.status
              OR (
                  reservation_operations.status = 'RESERVED'
                  AND EXCLUDED.status = 'RELEASED'
              )
          );
        """,
        (reservation_id, product_id, quantity, fencing_generation, status),
    )
    if cursor.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Stale reservation fencing generation or invalid state transition",
        )

def release_active_reservation(cursor, reservation_id, product_id, quantity, fencing_generation):
    cursor.execute(
        """
        SELECT product_id, quantity, status
        FROM stock_reservations
        WHERE reservation_id = %s
        FOR UPDATE;
        """,
        (reservation_id,),
    )
    reservation = cursor.fetchone()
    if reservation is None or reservation[0] != product_id or reservation[1] != quantity:
        raise HTTPException(status_code=409, detail="Reservation details do not match")
    if reservation[2] == "RELEASED":
        update_operation(cursor, reservation_id, product_id, quantity, fencing_generation, "RELEASED")
        cursor.execute(
            "SELECT id, name, stock FROM products WHERE id = %s;",
            (product_id,),
        )
        product = cursor.fetchone()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return product, True

    cursor.execute(
        """
        UPDATE products
        SET stock = stock + %s
        WHERE id = %s
        RETURNING id, name, stock;
        """,
        (quantity, product_id),
    )
    product = cursor.fetchone()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    cursor.execute(
        "UPDATE stock_reservations SET status = 'RELEASED' WHERE reservation_id = %s;",
        (reservation_id,),
    )
    update_operation(cursor, reservation_id, product_id, quantity, fencing_generation, "RELEASED")
    return product, False

@app.post("/products/{product_id}/reserve")
def reserve_stock(
    product_id: int,
    quantity: int,
    reservation_id: UUID,
    fencing_generation: int = Query(default=0, ge=0),
    service_token: str | None = Header(default=None, alias="X-Order-Service-Token"),
):
    require_order_service(service_token)
    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            lock_reservation(cursor, reservation_id)
            existing = get_reservation_operation(cursor, reservation_id)

            if existing is not None:
                validate_operation(existing, product_id, quantity, fencing_generation)
                if existing[3] != "RESERVED":
                    raise HTTPException(status_code=409, detail="Reservation is no longer active")

                cursor.execute(
                    """
                    SELECT product_id, quantity, status
                    FROM stock_reservations
                    WHERE reservation_id = %s;
                    """,
                    (reservation_id,),
                )
                reservation = cursor.fetchone()
                if (
                    reservation is None
                    or reservation[0] != product_id
                    or reservation[1] != quantity
                    or reservation[2] != "RESERVED"
                ):
                    raise HTTPException(status_code=409, detail="Reservation ledger is inconsistent")
                if fencing_generation > existing[2]:
                    update_operation(cursor, reservation_id, product_id, quantity, fencing_generation, "RESERVED")

                cursor.execute(
                    "SELECT id, name, stock FROM products WHERE id = %s;",
                    (product_id,)
                )
                product = cursor.fetchone()

                if product is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Product not found"
                    )

                return {
                    "reservation_id": str(reservation_id),
                    "product_id": product[0],
                    "name": product[1],
                    "remaining_stock": product[2],
                    "already_reserved": True
                }

            cursor.execute(
                """
                UPDATE products
                SET stock = stock - %s
                WHERE id = %s AND stock >= %s
                RETURNING id, name, stock;
                """,
                (quantity, product_id, quantity)
            )
            product = cursor.fetchone()

            if product is None:
                cursor.execute(
                    "SELECT id FROM products WHERE id = %s;",
                    (product_id,)
                )

                if cursor.fetchone() is None:
                    raise HTTPException(
                        status_code=404,
                        detail="Product not found"
                    )

                raise HTTPException(
                    status_code=409,
                    detail="Insufficient stock"
                )

            cursor.execute(
                """
                INSERT INTO stock_reservations
                (reservation_id, product_id, quantity, status)
                VALUES (%s, %s, %s, 'RESERVED');
                """,
                (reservation_id, product_id, quantity)
            )
            update_operation(cursor, reservation_id, product_id, quantity, fencing_generation, "RESERVED")

    return {
        "reservation_id": str(reservation_id),
        "product_id": product[0],
        "name": product[1],
        "remaining_stock": product[2],
        "already_reserved": False
    }

@app.post("/products/{product_id}/release")
def release_stock(
    product_id: int,
    quantity: int,
    reservation_id: UUID,
    fencing_generation: int = Query(default=0, ge=0),
    service_token: str | None = Header(default=None, alias="X-Order-Service-Token"),
):
    require_order_service(service_token)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            lock_reservation(cursor, reservation_id)
            operation = get_reservation_operation(cursor, reservation_id)
            if operation is None:
                raise HTTPException(
                    status_code=404,
                    detail="Reservation not found"
                )
            validate_operation(operation, product_id, quantity, fencing_generation)

            if operation[3] == "CANCELLED":
                return {
                    "reservation_id": str(reservation_id),
                    "product_id": product_id,
                    "status": "CANCELLED",
                    "already_released": False,
                    "already_cancelled": True,
                }
            if operation[3] == "RELEASED":
                if fencing_generation > operation[2]:
                    update_operation(cursor, reservation_id, product_id, quantity, fencing_generation, "RELEASED")
                return {
                    "reservation_id": str(reservation_id),
                    "product_id": product_id,
                    "status": "RELEASED",
                    "already_released": True
                }

            product, already_released = release_active_reservation(
                cursor, reservation_id, product_id, quantity, fencing_generation
            )

    return {
        "reservation_id": str(reservation_id),
        "product_id": product[0],
        "name": product[1],
        "remaining_stock": product[2],
        "status": "RELEASED",
        "already_released": already_released
    }

@app.post("/products/{product_id}/cancel")
def cancel_reservation(
    product_id: int,
    quantity: int,
    reservation_id: UUID,
    fencing_generation: int = Query(..., ge=0),
    service_token: str | None = Header(default=None, alias="X-Order-Service-Token"),
):
    require_order_service(service_token)
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be greater than zero")

    with get_connection() as connection:
        with connection.cursor() as cursor:
            lock_reservation(cursor, reservation_id)
            operation = get_reservation_operation(cursor, reservation_id)
            if operation is None:
                update_operation(
                    cursor, reservation_id, product_id, quantity, fencing_generation, "CANCELLED"
                )
                status = "CANCELLED"
            else:
                validate_operation(operation, product_id, quantity, fencing_generation)
                if operation[3] == "RESERVED":
                    release_active_reservation(
                        cursor, reservation_id, product_id, quantity, fencing_generation
                    )
                    status = "RELEASED"
                else:
                    status = operation[3]
                    if fencing_generation > operation[2]:
                        update_operation(
                            cursor, reservation_id, product_id, quantity,
                            fencing_generation, status
                        )

    return {
        "reservation_id": str(reservation_id),
        "product_id": product_id,
        "status": status,
        "already_cancelled": status == "CANCELLED" and operation is not None,
    }

@app.get("/user-info/{user_id}")
def get_user_info(user_id: int):
    response = httpx.get(
        f"http://127.0.0.1:8000/users/{user_id}"
    )

    if response.status_code != 200:
        return {"error": "User not found"}

    return response.json()

@app.get("/products/{product_id}/reservations/{reservation_id}")
def get_reservation_status(
    product_id: int,
    reservation_id: UUID,
    fencing_generation: int = Query(default=0, ge=0),
    service_token: str | None = Header(default=None, alias="X-Order-Service-Token"),
):
    require_order_service(service_token)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            lock_reservation(cursor, reservation_id)
            operation = get_reservation_operation(cursor, reservation_id)
            if operation is None:
                raise HTTPException(status_code=404, detail="Reservation not found")
            if operation[0] != product_id:
                raise HTTPException(status_code=409, detail="Reservation details do not match")
            if fencing_generation < operation[2]:
                raise HTTPException(status_code=409, detail="Stale reservation fencing generation")

    return {
        "reservation_id": str(reservation_id),
        "product_id": operation[0],
        "quantity": operation[1],
        "fencing_generation": operation[2],
        "status": operation[3],
        "created_at": operation[4],
    }
