import json
import logging

#import 
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents import recommendation as rec
from app.agents.delay_risk import InvalidRiskInputError, OrderNotFoundError
from app.db.session import get_db
from app.ir import retriever
from app.ml.predictor import ModelNotTrainedError
from app.schemas.recommendation import (
    DecisionRecord,
    DecisionRequest,
    GenerateRequest,
    RecommendationResponse,
    SearchRequest,
)

logger = logging.getLogger(__name__)

# add a prefix to all routes in this file
router = APIRouter(prefix="/recommendation", tags=["recommendation"])


@router.post("/generate", response_model=RecommendationResponse)
def generate_recommendations(request: GenerateRequest, db: Session = Depends(get_db)):
    try:
        return rec.RecommendationAgent(db).run(
            order_id=request.order_id,
            risk_result=request.risk_result,
            resource_result=request.resource_result,
        )
    except OrderNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except InvalidRiskInputError as e:
        raise HTTPException(status_code=422, detail=f"Delay Risk Agent could not assess this order: {e}")
    except (retriever.IndexNotBuiltError, ModelNotTrainedError) as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Bad input: {e}")
    except Exception as e:
        logger.error(f"Error in recommendation generate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
def search_knowledge_base(request: SearchRequest):
    try:
        results = retriever.search(request.query, top_k=request.top_k, category=request.category)
        return {"query": request.query, "retrieval_backend": retriever.backend_name(), "results": results}
    except retriever.IndexNotBuiltError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/kb")
def list_knowledge_base():
    try:
        r = retriever.get_retriever()
    except retriever.IndexNotBuiltError as e:
        raise HTTPException(status_code=503, detail=str(e))
    manifest_path = retriever.INDEX_DIR / "index_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    documents = [
        {"document_id": d["document_id"], "category": d["category"], "title": d["title"]}
        for d in r.list_documents()
    ]
    return {
        "retrieval_backend": r.name,
        "index_status": "built" if manifest else "not built (TF-IDF needs no index)",
        "index_built_at": manifest["built_at"] if manifest else None,
        "document_count": len(documents),
        "documents": documents,
    }


@router.post("/decision", response_model=DecisionRecord)
def save_decision(request: DecisionRequest, db: Session = Depends(get_db)):
    if not rec.order_exists(db, request.order_id):
        raise HTTPException(status_code=404, detail=f"Order '{request.order_id}' not found.")
    return rec.save_decision(db, request.order_id, request.action, request.decision,
                             request.comment, request.decided_by)


@router.get("/decisions/{order_id}", response_model=list[DecisionRecord])
def get_decisions(order_id: str, db: Session = Depends(get_db)):
    if not rec.order_exists(db, order_id):
        raise HTTPException(status_code=404, detail=f"Order '{order_id}' not found.")
    return rec.list_decisions(db, order_id)
