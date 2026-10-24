from fastapi import FastAPI
from pydantic import BaseModel
from database import get_connection
import httpx
from fastapi import HTTPException
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

@app.post("/products/{product_id}/reserve")
def reserve_stock(
    product_id: int,
    quantity: int,
    reservation_id: UUID
):
    if quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Quantity must be greater than zero"
        )

    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_id, quantity, status
                FROM stock_reservations
                WHERE reservation_id = %s;
                """,
                (reservation_id,)
            )
            existing = cursor.fetchone()

            if existing is not None:
                if (
                    existing[0] != product_id
                    or existing[1] != quantity
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Reservation ID already used with different details"
                    )

                if existing[2] != "RESERVED":
                    raise HTTPException(
                        status_code=409,
                        detail="Reservation is no longer active"
                    )

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
    reservation_id: UUID
):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT product_id, quantity, status
                FROM stock_reservations
                WHERE reservation_id = %s
                FOR UPDATE;
                """,
                (reservation_id,)
            )
            reservation = cursor.fetchone()

            if reservation is None:
                raise HTTPException(
                    status_code=404,
                    detail="Reservation not found"
                )

            if reservation[0] != product_id or reservation[1] != quantity:
                raise HTTPException(
                    status_code=409,
                    detail="Reservation details do not match"
                )

            if reservation[2] == "RELEASED":
                return {
                    "reservation_id": str(reservation_id),
                    "product_id": product_id,
                    "status": "RELEASED",
                    "already_released": True
                }

            cursor.execute(
                """
                UPDATE products
                SET stock = stock + %s
                WHERE id = %s
                RETURNING id, name, stock;
                """,
                (quantity, product_id)
            )
            product = cursor.fetchone()

            if product is None:
                raise HTTPException(
                    status_code=404,
                    detail="Product not found"
                )

            cursor.execute(
                """
                UPDATE stock_reservations
                SET status = 'RELEASED'
                WHERE reservation_id = %s;
                """,
                (reservation_id,)
            )

    return {
        "reservation_id": str(reservation_id),
        "product_id": product[0],
        "name": product[1],
        "remaining_stock": product[2],
        "status": "RELEASED",
        "already_released": False
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
def get_reservation_status(product_id: int, reservation_id: UUID):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT reservation_id, product_id, quantity, status, created_at
                FROM stock_reservations
                WHERE reservation_id = %s AND product_id = %s;
                """,
                (reservation_id, product_id)
            )
            reservation = cursor.fetchone()

    if reservation is None:
        raise HTTPException(
            status_code=404,
            detail="Reservation not found"
        )

    return {
        "reservation_id": str(reservation[0]),
        "product_id": reservation[1],
        "quantity": reservation[2],
        "status": reservation[3],
        "created_at": reservation[4]
    }
