from fastapi import APIRouter

router = APIRouter(prefix="/risk", tags=["risk"])

@router.get("/")
def get_risk_status():
    return {"message": "Phase 3 stub"}
