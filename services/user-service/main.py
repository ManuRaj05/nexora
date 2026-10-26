from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from database import get_connection
from pydantic import BaseModel, ConfigDict
import bcrypt
import os
import jwt
import psycopg

app = FastAPI()
security = HTTPBearer(auto_error=False)

def jwt_secret():
    secret = os.getenv("JWT_SECRET")
    if not secret or not secret.strip():
        raise HTTPException(status_code=503, detail="Token verification is not configured")
    return secret

def verify_token(token: str):
    secret = jwt_secret()
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["user_id", "exp"]},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})

    user_id = payload.get("user_id")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    return user_id


def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token required", headers={"WWW-Authenticate": "Bearer"})
    user_id = verify_token(credentials.credentials)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, username, email, role FROM users WHERE id = %s;", (user_id,))
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="User account is unavailable", headers={"WWW-Authenticate": "Bearer"})
    return {"user_id": row[0], "username": row[1], "email": row[2], "role": row[3]}


def require_admin(user=Depends(get_current_user)):
    if user["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str
    email: str
    password: str

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
def get_users(_admin=Depends(require_admin)):
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id , username,email ,role FROM users;")
            users = cursor.fetchall()
    return users

@app.get("/users/me")
def get_current_user_endpoint(user=Depends(get_current_user)):
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
    }

@app.get("/users/{user_id}")
def get_user(user_id: int, identity=Depends(get_current_user)):
    if identity["user_id"] != user_id and identity["role"] != "ADMIN":
        raise HTTPException(status_code=403, detail="You may only access your own account")
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
                "SELECT id, username, email, password_hash FROM users WHERE email = %s;",
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
        "exp": datetime.now(timezone.utc) + timedelta(hours=8),
    },
    jwt_secret(),
    algorithm="HS256"
    )
    return {
        "message":"Login successful",
        "token":token
    }
