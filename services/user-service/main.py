from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from pydantic import BaseModel
import bcrypt
import os
import jwt
import psycopg

app = FastAPI()
security = HTTPBearer()

def verify_token(token: str):
    try:
        payload = jwt.decode(
            token,
            os.getenv("JWT_SECRET"),
            algorithms=["HS256"]
        )
        return payload
    except jwt.InvalidTokenError:
        return None

class UserCreate(BaseModel):
    username:str
    email:str
    password:str

class UserLogin(BaseModel):
    email:str
    password:str

@app.get("/")
def root():
    return {"message": "Nexora User Service is running"}
    
@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/users")
def get_users():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id , username,email ,role FROM users;")
            users = cursor.fetchall()
    return users

@app.get("/users/me")
def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials

    payload = verify_token(token)

    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token"
        )

    return {
        "user_id": payload["user_id"],
        "role": payload["role"]
    }

@app.get("/users/{user_id}")
def get_user(user_id: int):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, username, email, role FROM users WHERE id = %s;",
                (user_id,)
            )
            user = cursor.fetchone()

    if user is None:
        return {"error": "User not found"}

    return user

@app.post("/users/register")
def register_user(user: UserCreate):
    password_hash = bcrypt.hashpw(user.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (username, email, password_hash)
                    VALUES(%s, %s, %s)
                    RETURNING id,username,email,role;
                    """,
                    (user.username,user.email,password_hash)
                )
                new_user = cursor.fetchone()
        return new_user
    except psycopg.errors.UniqueViolation:
        raise HTTPException(
            status_code=400,
            detail="Username or email already exists"
        )

@app.post("/users/login")
def login_user(user: UserLogin):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id , username,email,password_hash, role FROM users WHERE email = %s;",
                (user.email,)
            )
            existing_user = cursor.fetchone()
    if existing_user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    password_matches=bcrypt.checkpw(user.password.encode("utf-8"),existing_user[3].encode("utf-8")
    )

    if not password_matches:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )
    
    token = jwt.encode({
        "user_id":existing_user[0],
        "role":existing_user[4]
    },
    os.getenv("JWT_SECRET"), 
    algorithm="HS256"
    )
    return {
        "message":"Login successful",
        "token":token
    }
