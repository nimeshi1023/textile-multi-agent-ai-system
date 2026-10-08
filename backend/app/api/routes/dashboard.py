"""
Manager Dashboard data (read-only).

GET /dashboard/summary        aggregates from cust_ord_table, orders and recommendation_decisions
GET /dashboard/risk-overview  delay risk of the 10 most recent orders, using the existing
                              Delay Risk / Resource agent functions (no LLM, no writes),
                              cached in memory for 10 minutes
Protected by get_current_manager in main.py, like the other routers.
"""
import logging
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

RISK_CACHE_SECONDS = 600
RISK_OVERVIEW_ORDERS = 10
TOP_REASONS = 6
NO_RISK_REASON = "No major risk factor detected"

_risk_cache: Dict[str, Any] = {"at": 0.0, "data": None}


def _read_only(db: Session) -> None:
    db.rollback()
    db.execute(text("SET TRANSACTION READ ONLY"))


def _rows(db: Session, sql: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    return [dict(r) for r in db.execute(text(sql), params or {}).mappings().fetchall()]


def _table_exists(db: Session, name: str) -> bool:
    return db.execute(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": name}).scalar() is True


def _counts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"label": r["label"], "count": int(r["count"])} for r in rows]


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)):
    today = date.today()
    try:
        _read_only(db)
        totals = db.execute(text("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE priority = 'High') AS high,
                   COUNT(*) FILTER (WHERE deadline_date BETWEEN :today AND :in7) AS due7
            FROM cust_ord_table
        """), {"today": today, "in7": today + timedelta(days=7)}).mappings().fetchone()
        totals = dict(totals) if totals else {}

        by_priority = _rows(db, """SELECT priority AS label, COUNT(*) AS count FROM cust_ord_table
                                   GROUP BY priority ORDER BY count DESC, label""")
        by_product = _rows(db, """SELECT product_type AS label, COUNT(*) AS count FROM cust_ord_table
                                  GROUP BY product_type ORDER BY count DESC, label""")
        by_material = _rows(db, """SELECT COALESCE(NULLIF(TRIM(material_name), ''), 'Unknown') AS label,
                                          COUNT(*) AS count
                                   FROM cust_ord_table GROUP BY 1 ORDER BY count DESC, label""")
        per_day = _rows(db, """SELECT order_date AS day, COUNT(*) AS count FROM cust_ord_table
                               WHERE order_date BETWEEN :start AND :today
                               GROUP BY order_date ORDER BY order_date""",
                        {"start": today - timedelta(days=29), "today": today})
        deadlines = _rows(db, """SELECT cus_ord_id AS order_id, product_type, quantity, priority, deadline_date
                                 FROM cust_ord_table WHERE deadline_date BETWEEN :today AND :in14
                                 ORDER BY deadline_date, cus_ord_id""",
                          {"today": today, "in14": today + timedelta(days=14)})

        delay_rates, reasons = [], []
        if _table_exists(db, "orders"):
            delay_rates = _rows(db, """SELECT product_type AS label, ROUND(AVG(delayed)::numeric, 4) AS rate,
                                              COUNT(*) AS orders
                                       FROM orders GROUP BY product_type ORDER BY rate DESC, label""")
            # "Material shortage (8571 units short of Silk Thread)" -> "Material shortage"
            reasons = _rows(db, r"""
                SELECT label, COUNT(*) AS count FROM (
                    SELECT TRIM(regexp_replace(reason, '\s*\(.*\)\s*$', '')) AS label
                    FROM orders, regexp_split_to_table(COALESCE(delay_reasons, ''), ';') AS reason
                ) AS split
                WHERE label <> '' AND label <> :no_risk
                GROUP BY label ORDER BY count DESC, label LIMIT :top
            """, {"no_risk": NO_RISK_REASON, "top": TOP_REASONS})

        decisions = []
        if _table_exists(db, "recommendation_decisions"):
            decisions = _rows(db, """SELECT decision AS label, COUNT(*) AS count FROM recommendation_decisions
                                     GROUP BY decision ORDER BY count DESC, label""")
    finally:
        db.rollback()

    return {
        "total_orders": int(totals.get("total") or 0),
        "high_priority_orders": int(totals.get("high") or 0),
        "orders_due_within_7_days": int(totals.get("due7") or 0),
        "orders_by_priority": _counts(by_priority),
        "orders_by_product_type": _counts(by_product),
        "orders_by_material": _counts(by_material),
        "orders_per_day": [{"date": str(r["day"]), "count": int(r["count"])} for r in per_day],
        "deadlines_next_14_days": [
            {**r, "deadline_date": str(r["deadline_date"]), "days_left": (r["deadline_date"] - today).days}
            for r in deadlines
        ],
        "historical_delay_rate_by_product": [
            {"label": r["label"], "rate": float(r["rate"]), "orders": int(r["orders"])} for r in delay_rates
        ],
        "top_delay_reasons": _counts(reasons),
        "decisions_by_type": _counts(decisions),
        "decisions_total": sum(int(r["count"]) for r in decisions),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.get("/risk-overview")
def risk_overview(refresh: bool = False, db: Session = Depends(get_db)):
    if not refresh and _risk_cache["data"] and time.time() - _risk_cache["at"] < RISK_CACHE_SECONDS:
        return {**_risk_cache["data"], "cached": True}

    from app.agents.delay_risk import DelayRiskAgent
    from app.ml import predictor

    try:
        bundle = predictor.load_model()
    except predictor.ModelNotTrainedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    try:
        _read_only(db)
        recent = _rows(db, """SELECT cus_ord_id, product_type, quantity, priority, deadline_date
                              FROM cust_ord_table ORDER BY order_date DESC, cus_ord_id DESC LIMIT :n""",
                       {"n": RISK_OVERVIEW_ORDERS})
    finally:
        db.rollback()

    agent = DelayRiskAgent(db)
    orders, counts = [], {"Low": 0, "Medium": 0, "High": 0, "Unavailable": 0}
    for order in recent:
        item = {"order_id": order["cus_ord_id"], "product_type": order["product_type"],
                "quantity": order["quantity"], "priority": order["priority"],
                "deadline_date": str(order["deadline_date"])}
        try:
            # Existing agent steps only; explain() is never called, so no LLM is used.
            facts = agent.get_order_facts(order["cus_ord_id"])
            resource = agent.get_resource_result(order["cus_ord_id"])
            hist_rate = agent.get_historical_rate(facts.get("product_type"))
            features, _missing = agent.build_features(resource, facts, hist_rate, bundle)
            probability = agent.predict(features, bundle)
            level = agent.classify_risk(probability)
            item.update(risk_level=level, delay_probability_pct=round(probability * 100, 1),
                        risk_drivers=[i for i in resource.get("issues") or [] if i != "MATERIAL_NOT_FOUND"])
        except Exception as e:   # one bad order must not break the overview
            level = "Unavailable"
            item.update(risk_level=level, delay_probability_pct=None, risk_drivers=[], error=str(e)[:200])
        finally:
            db.rollback()       # read-only: nothing is ever committed
        counts[level] += 1
        orders.append(item)

    data = {"counts": counts, "orders": orders,
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _risk_cache.update(at=time.time(), data=data)
    return {**data, "cached": False}
