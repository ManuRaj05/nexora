from fastapi import FastAPI
from pydantic import BaseModel
from database import get_connection

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
        return {"error": "Product not found"}

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
        return {"error": "Product not found"}

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
        return {"error": "Product not found"}

    return {"message": "Product deleted successfully", "product_id": deleted_product[0]}

