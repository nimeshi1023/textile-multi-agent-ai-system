from sqlalchemy.orm import Session
from app.db.models import CustOrd
from app.schemas.order import OrderCreate, OrderUpdate
from datetime import date

class OrderService:
    @staticmethod
    def get_all_orders(db: Session, priority: str = None, skip: int = 0, limit: int = 100):
        query = db.query(CustOrd)
        if priority:
            query = query.filter(CustOrd.priority == priority)
        return query.offset(skip).limit(limit).all()

    @staticmethod
    def get_order(db: Session, cus_ord_id: str):
        return db.query(CustOrd).filter(CustOrd.cus_ord_id == cus_ord_id).first()

    @staticmethod
    def create_order(db: Session, order: OrderCreate) -> CustOrd:
        db_order = CustOrd(
            cus_ord_id=order.cus_ord_id,
            product_type=order.product_type,
            quantity=order.quantity,
            priority=order.priority,
            order_date=order.order_date,
            deadline_date=order.deadline_date,
            material_required=order.material_required,
            material_name=order.material_name
        )
        db.add(db_order)
        db.commit()
        db.refresh(db_order)
        return db_order

    @staticmethod
    def delete_order(db: Session, cus_ord_id: str) -> bool:
        db_order = OrderService.get_order(db, cus_ord_id)
        if db_order:
            db.delete(db_order)
            db.commit()
            return True
        return False

    @staticmethod
    def update_order(db: Session, cus_ord_id: str, order_update: OrderUpdate) -> CustOrd | None:
        db_order = OrderService.get_order(db, cus_ord_id)
        if not db_order:
            return None
        
        update_data = order_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(db_order, key, value)
            
        db.commit()
        db.refresh(db_order)
        return db_order

    @staticmethod
    def generate_next_order_id(db: Session) -> str:
        current_year = date.today().year
        prefix = f"ORD-{current_year}-"
        
        # Get the highest existing ID with this prefix safely
        last_order = db.query(CustOrd).filter(
            CustOrd.cus_ord_id.like(f"{prefix}%")
        ).order_by(CustOrd.cus_ord_id.desc()).first()
        
        if last_order:
            try:
                seq = int(last_order.cus_ord_id.split("-")[-1])
                next_seq = seq + 1
            except ValueError:
                next_seq = 1
        else:
            next_seq = 1
            
        return f"{prefix}{next_seq:04d}"
