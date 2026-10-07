from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import logging

from app.db.session import get_db
from app.schemas.resource import ResourceAnalyzeRequest, ResourceAnalyzeResponse
from app.agents.resource_production import ResourceProductionAgent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/production", tags=["production"])

@router.post("/analyze", response_model=ResourceAnalyzeResponse)
def analyze_resources(request: ResourceAnalyzeRequest, db: Session = Depends(get_db)):
    try:
        agent = ResourceProductionAgent(db)
        return agent.run(request)
    except Exception as e:
        logger.error(f"Error in production analyze: {e}")
        raise HTTPException(status_code=500, detail=str(e))
