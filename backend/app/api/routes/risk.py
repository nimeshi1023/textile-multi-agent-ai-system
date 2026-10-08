import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.delay_risk import DelayRiskAgent, InvalidRiskInputError, OrderNotFoundError
from app.db.session import get_db
from app.ml import predictor
from app.schemas.risk import RiskPredictRequest, RiskPredictResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/risk", tags=["risk"])


@router.post("/predict", response_model=RiskPredictResponse)
def predict_delay_risk(request: RiskPredictRequest, db: Session = Depends(get_db)):
    try:
        agent = DelayRiskAgent(db)
        return agent.run(
            order_id=request.order_id,
            resource_result=request.resource_result,
            order=request.order.model_dump() if request.order else None,
        )
    except predictor.ModelNotTrainedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OrderNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRiskInputError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"Error in risk predict: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/model-info")
def model_info():
    try:
        return predictor.load_metrics()
    except predictor.ModelNotTrainedError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/health")
def risk_health():
    try:
        bundle = predictor.load_model()
        return {
            "status": "ok",
            "model_loaded": True,
            "model_name": bundle["model_name"],
            "trained_at": bundle["trained_at"],
        }
    except predictor.ModelNotTrainedError as e:
        return {"status": "model_not_trained", "model_loaded": False, "detail": str(e)}
