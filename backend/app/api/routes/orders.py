from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional
from app.db.session import get_db
from app.schemas.order import OrderCreate, OrderUpdate, OrderResponse, OrderAnalysisResponse, MessageRequest
from app.services.order_service import OrderService
from app.services.material_service import MaterialService
from app.services.llm_client import LLMClient
from app.services.pdf_service import PDFService
from app.agents.order_analysis import OrderAnalysisAgent
from datetime import date

router = APIRouter(prefix="/orders", tags=["orders"])

llm_client = LLMClient()
agent = OrderAnalysisAgent(llm_client)

def post_process_extracted(db: Session, analysis: OrderAnalysisResponse) -> OrderAnalysisResponse:
    if analysis.status == "error":
        return analysis
        
    ext = analysis.extracted_order
    if not ext:
        return analysis

    # Post processing
    if not ext.order_date:
        ext.order_date = date.today()
        
    if not ext.cus_ord_id:
        # Will be auto-generated later at save time, but we leave it None to show it's missing
        pass
        
    material_source = None
    if ext.material_required is not None:
        material_source = "extracted"
    elif ext.product_type and ext.quantity:
        est = MaterialService.estimate_material(db, ext.product_type, ext.quantity)
        if est is not None:
            ext.material_required = est
            material_source = "estimated"
        else:
            material_source = "missing"
            
    analysis.material_required_source = material_source
    return analysis

@router.post("/analyze/message", response_model=OrderAnalysisResponse)
def analyze_message(req: MessageRequest, db: Session = Depends(get_db)):
    result = agent.analyze_text(req.text)
    return post_process_extracted(db, result)

@router.post("/analyze/pdf", response_model=OrderAnalysisResponse)
def analyze_pdf(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    file_bytes = file.file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds 10 MB limit")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
        
    extracted_text = PDFService.extract_text(file_bytes)
    result = agent.analyze_pdf(file_bytes, extracted_text)
    return post_process_extracted(db, result)

@router.post("", response_model=OrderResponse)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    # Check deadline >= order_date
    if order.deadline_date < order.order_date:
        raise HTTPException(status_code=400, detail="deadline_date cannot be before order_date")
        
    # Always auto-generate ID
    order.cus_ord_id = OrderService.generate_next_order_id(db)
        
    # Check duplicates
    existing = OrderService.get_order(db, order.cus_ord_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Order ID {order.cus_ord_id} already exists")
        
    try:
        return OrderService.create_order(db, order)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))

@router.get("", response_model=list[OrderResponse])
def list_orders(priority: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return OrderService.get_all_orders(db, priority, skip, limit)

@router.get("/{cus_ord_id}", response_model=OrderResponse)
def get_order(cus_ord_id: str, db: Session = Depends(get_db)):
    order = OrderService.get_order(db, cus_ord_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.patch("/{cus_ord_id}", response_model=OrderResponse)
def update_order(cus_ord_id: str, order_update: OrderUpdate, db: Session = Depends(get_db)):
    order = OrderService.update_order(db, cus_ord_id, order_update)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@router.delete("/{cus_ord_id}")
def delete_order(cus_ord_id: str, db: Session = Depends(get_db)):
    success = OrderService.delete_order(db, cus_ord_id)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"detail": "Deleted"}
