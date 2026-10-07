from fastapi import APIRouter

router = APIRouter(prefix="/recommendation", tags=["recommendation"])

@router.get("/")
def get_recommendation():
    return {"message": "Phase 4 stub"}
