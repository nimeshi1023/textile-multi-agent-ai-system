import sys
import os

# Add backend dir to path
sys.path.append(os.path.abspath('e:/Textile Multi Agent Ai System/FabricFlow/backend'))

from app.db.session import engine
from sqlalchemy import text

tables = ['cust_ord_table', 'machines', 'materials', 'suppliers', 'llm_logs']

with engine.connect() as conn:
    for table in tables:
        print(f"\n--- Table: {table} ---")
        try:
            result = conn.execute(text(f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table}'
            """))
            for row in result:
                print(f"{row[0]}: {row[1]}")
        except Exception as e:
            print(f"Error reading {table}: {e}")
