from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.api.routes import orders, production, risk, recommendation, auth, dashboard
from app.api.routes.auth import get_current_manager
from app.db.session import get_db

app = FastAPI(title="FabricFlow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /auth/signup and /auth/login are public; every other API router needs a signed-in manager
app.include_router(auth.router)
protected = [Depends(get_current_manager)]
app.include_router(orders.router, dependencies=protected)
app.include_router(production.router, dependencies=protected)
app.include_router(risk.router, dependencies=protected)
app.include_router(recommendation.router, dependencies=protected)
app.include_router(dashboard.router, dependencies=protected)

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = str(e)
    return {"status": "ok", "db": db_status}

@app.get("/")
def read_root():
    return {"message": "Welcome to the FabricFlow API. Check /docs for the API documentation."}
