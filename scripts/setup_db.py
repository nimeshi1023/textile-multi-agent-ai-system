import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))
# pyrefly: ignore [missing-import]
from app.core.config import settings

# pyrefly: ignore [missing-import]
from app.db.session import engine, SessionLocal

# pyrefly: ignore [missing-import]
from app.db.models import MaterialConsumption, Base
import subprocess
from sqlalchemy import text

def create_database_if_not_exists():
    db_url = settings.DATABASE_URL
    # parse db_url
    url_parts = db_url.split('/')
    db_name = url_parts[-1]
    base_url = '/'.join(url_parts[:-1]) + '/postgres'
    
    # psycopg2.connect doesn't understand postgresql+psycopg2://
    base_url = base_url.replace("postgresql+psycopg2://", "postgresql://")
    
    try:
        conn = psycopg2.connect(base_url)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{db_name}'")
        exists = cur.fetchone()
        if not exists:
            cur.execute(f"CREATE DATABASE {db_name}")
            print(f"Database {db_name} created successfully.")
        else:
            print(f"Database {db_name} already exists.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error checking/creating database: {e}")

def seed_material_consumption():
    db = SessionLocal()
    defaults = [
        {"product_type": "T-Shirt", "unit": "meters", "consumption_per_piece": 1.20},
        {"product_type": "Polo Shirt", "unit": "meters", "consumption_per_piece": 1.50},
        {"product_type": "Shirt", "unit": "meters", "consumption_per_piece": 1.80},
        {"product_type": "Trousers", "unit": "meters", "consumption_per_piece": 2.20},
        {"product_type": "Jacket", "unit": "meters", "consumption_per_piece": 3.00},
        {"product_type": "Hoodie", "unit": "meters", "consumption_per_piece": 2.50},
    ]
    
    for item in defaults:
        existing = db.query(MaterialConsumption).filter_by(product_type=item["product_type"]).first()
        if not existing:
            db.add(MaterialConsumption(**item))
            
    db.commit()
    db.close()
    print("Seeded material consumption table.")

if __name__ == "__main__":
    create_database_if_not_exists()
    
    print("Running migrations...")
    # Just use create_all for simplicity if alembic is not fully configured yet
    # Or use alembic:
    # subprocess.run(["alembic", "upgrade", "head"], check=True)
    Base.metadata.create_all(bind=engine)
    print("Database tables created.")

    # create_all doesn't add columns to existing tables
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE cust_ord_table ADD COLUMN IF NOT EXISTS material_name VARCHAR(50)"))
    print("Schema columns up to date.")
    
    seed_material_consumption()
    print("Setup complete.")
