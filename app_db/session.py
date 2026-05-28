import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

APP_DATABASE_URL = os.getenv(
    "APP_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tradingbot_app"
)

engine = create_engine(APP_DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
