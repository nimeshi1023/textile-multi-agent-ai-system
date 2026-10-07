from sqlalchemy import Column, String, Integer, Date, Numeric, CheckConstraint, Index, DateTime, Text, Float
from app.db.session import Base
from datetime import datetime

class CustOrd(Base):
    __tablename__ = "cust_ord_table"
    cus_ord_id = Column(String(20), primary_key=True)
    product_type = Column(String(100), nullable=False)
    quantity = Column(Integer, nullable=False)
    priority = Column(String(20), nullable=False)
    order_date = Column(Date, nullable=False)
    deadline_date = Column(Date, nullable=False)
    material_required = Column(Numeric(12, 2), nullable=True)
    material_name = Column(String(50), nullable=True)

    __table_args__ = (
        CheckConstraint("priority IN ('Low', 'Medium', 'High')", name="check_priority"),
        CheckConstraint("deadline_date >= order_date", name="check_deadline"),
        Index("ix_cust_ord_table_deadline_date", "deadline_date"),
        Index("ix_cust_ord_table_priority", "priority"),
    )

class LLMLog(Base):
    __tablename__ = "llm_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    prompt = Column(Text, nullable=False)
    response = Column(Text, nullable=True)
    latency_ms = Column(Float, nullable=True)
    status = Column(String(50), nullable=False)
    error_message = Column(Text, nullable=True)

class MaterialConsumption(Base):
    __tablename__ = "material_consumption"
    id = Column(Integer, primary_key=True, autoincrement=True)
    product_type = Column(String(100), unique=True, nullable=False)
    unit = Column(String(20), nullable=False)
    consumption_per_piece = Column(Numeric(10, 2), nullable=False)
