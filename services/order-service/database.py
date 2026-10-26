import os
from pathlib import Path
from dotenv import load_dotenv
import psycopg

load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"), override=False)

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg.connect(DATABASE_URL)
