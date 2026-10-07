from sqlalchemy.orm import Session
from sqlalchemy import func
from app.db.models import MaterialConsumption
from decimal import Decimal

class MaterialService:
    @staticmethod
    def estimate_material(db: Session, product_type: str, quantity: int) -> Decimal | None:
        record = db.query(MaterialConsumption).filter(
            func.lower(MaterialConsumption.product_type) == product_type.lower()
        ).first()
        
        if record:
            return Decimal(quantity) * record.consumption_per_piece
        return None
