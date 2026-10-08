"""
Phase 4 - Recommendation Agent.

Delay Risk result (risk_level, risk_drivers, top_factors) + Resource result
    -> risk Low: "no action needed" (no retrieval)
    -> risk Medium/High:
         build_queries()   one query per (risk driver x candidate action), with the real numbers
         retrieve()        top SOPs from the knowledge base (IR layer, no LLM)
         select_actions()  keep an action ONLY if a retrieved SOP supports it
         rank_actions()    by the driver's model impact, then retrieval score (max 5)
         explain()         Python template with the real numbers (LLM polish optional, off)
         build_result()
The agent only RECOMMENDS. It never changes orders, machines, stock or schedules;
a manager approves, rejects or overrides (saved in recommendation_decisions).
"""
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ir import retriever

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk driver -> candidate actions. Edit this table to change the rules.
#   action        short title shown to the manager
#   query         what to search for in the knowledge base
#   support_terms the action is recommended only if a retrieved SOP contains
#                 at least one of these phrases (lower-case substring match)
# ---------------------------------------------------------------------------
ALTERNATE_SUPPLIER = {
    "action": "Activate an alternate supplier for the material",
    "query": "activate an alternate supplier when the primary supplier cannot deliver the material in time",
    "support_terms": ["alternate supplier"],
}
PARTIAL_DELIVERY = {
    "action": "Offer the customer a partial delivery (split shipment)",
    "query": "offer the customer a partial shipment of completed units before the deadline",
    "support_terms": ["partial shipment", "partial delivery"],
}

ACTION_RULES: Dict[str, List[Dict[str, Any]]] = {
    "MACHINE_CAPACITY_SHORTAGE": [
        {
            "action": "Move production to another machine with free capacity",
            "query": "assign the order to another machine with lower workload, workload balancing across machines",
            "support_terms": ["lowest current workload", "split across machines", "another available", "reallocate capacity"],
        },
        {
            "action": "Authorize overtime or an extra shift",
            "query": "authorize overtime or an extra weekend shift for a capacity shortfall",
            "support_terms": ["overtime", "extra shift", "weekend shift"],
        },
        {
            "action": "Outsource part of the order to a subcontractor",
            "query": "outsource part of the order to a subcontractor when in-house capacity cannot meet the deadline",
            "support_terms": ["outsourc", "subcontract"],
        },
        {
            "action": "Reschedule production (reallocate capacity or later start)",
            "query": "reschedule production, reallocate machine capacity from lower-priority orders, later start date",
            "support_terms": ["later start date", "reallocate capacity", "schedule should be adjusted"],
        },
    ],
    "MACHINE_UNAVAILABLE": [
        {
            "action": "Reassign the order to another available machine",
            "query": "machine breakdown, reassign the order to another available or backup machine",
            "support_terms": ["reassigned to another available", "reassigned to a backup", "redistribute workers to operational machines"],
        },
        {
            "action": "Follow the machine breakdown / maintenance procedure",
            "query": "machine breakdown malfunction procedure, log the fault, maintenance team, downtime",
            "support_terms": ["maintenance system", "maintenance vendor", "maintenance team", "preventive maintenance"],
        },
    ],
    "MATERIAL_SHORTAGE": [
        ALTERNATE_SUPPLIER,
        {
            "action": "Raise an emergency purchase for the missing material",
            "query": "emergency purchase request for a raw material shortage, urgent local purchase",
            "support_terms": ["emergency purchase", "emergency local purchase", "urgent order"],
        },
        PARTIAL_DELIVERY,
    ],
    "SUPPLIER_DELAY_RISK": [
        {
            "action": "Escalate the delay with the supplier",
            "query": "supplier delay escalation policy, contact the supplier to confirm a revised delivery date",
            "support_terms": ["escalat"],
        },
        ALTERNATE_SUPPLIER,
    ],
    "DEADLINE_TOO_TIGHT": [
        {
            "action": "Negotiate a deadline extension with the customer",
            "query": "negotiate a deadline extension with the customer and give a revised delivery estimate",
            "support_terms": ["revised delivery estimate", "contact the customer", "deadline extension"],
        },
        PARTIAL_DELIVERY,
        {
            "action": "Give the order priority on shared machines",
            "query": "prioritize a rush order, schedule a high priority order ahead on shared machines",
            "support_terms": ["scheduled ahead", "prioritiz"],
        },
    ],
}

DRIVER_TEXT = {
    "MACHINE_CAPACITY_SHORTAGE": "machine capacity shortfall",
    "MACHINE_UNAVAILABLE": "machine unavailable or breakdown",
    "MATERIAL_SHORTAGE": "raw material shortage",
    "SUPPLIER_DELAY_RISK": "supplier delay risk",
    "DEADLINE_TOO_TIGHT": "tight deadline",
}

# Which Delay Risk model features belong to which driver (used for ranking)
DRIVER_FEATURES = {
    "MACHINE_CAPACITY_SHORTAGE": ["capacity_shortfall", "available_capacity_per_day", "machine_capacity_per_day",
                                  "machine_current_workload_pct", "required_production_days",
                                  "production_to_deadline_ratio", "quantity"],
    "MACHINE_UNAVAILABLE": ["machine_status", "available_capacity_per_day", "machine_capacity_per_day"],
    "MATERIAL_SHORTAGE": ["material_shortage", "material_required", "material_stock_available"],
    "SUPPLIER_DELAY_RISK": ["supplier_risk", "supplier_lead_time", "supplier_reliability"],
    "DEADLINE_TOO_TIGHT": ["tight_deadline", "days_remaining", "production_to_deadline_ratio",
                           "required_production_days"],
}

MAX_ACTIONS = 5
TOP_K_PER_QUERY = 3


class RecommendationAgent:
    def __init__(self, db: Session):
        self.db = db

    # ---------- entry point ----------
    def run(
        self,
        order_id: str,
        risk_result: Optional[Dict[str, Any]] = None,
        resource_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if risk_result is None or resource_result is None:
            risk_result, resource_result = self.get_earlier_results(order_id, risk_result, resource_result)

        level = risk_result["risk_level"]
        pct = float(risk_result["delay_probability_pct"])
        facts = self.extract_facts(risk_result, resource_result)
        drivers = self.get_drivers(risk_result, resource_result)

        if level == "Low":
            explanation = (f"Delay risk is LOW ({pct:.1f}%). No action needed; "
                           f"the order can proceed as planned.")
            return self.build_result(order_id, "no_action_needed", risk_result, drivers, [], [], {},
                                     explanation, "template", backend=None)

        queries = self.build_queries(drivers, facts, risk_result.get("top_factors") or [])
        retrieved = self.retrieve(queries)
        actions, dropped = self.select_actions(queries, retrieved, facts)
        actions = self.rank_actions(actions, risk_result.get("top_factors") or [])
        status = "recommendations_ready" if actions else "no_supported_actions"
        explanation, source = self.explain(level, pct, drivers, facts, actions)
        return self.build_result(order_id, status, risk_result, drivers, actions, dropped, retrieved,
                                 explanation, source, backend=retriever.backend_name())

    # ---------- earlier agents (imported, unchanged) ----------
    def get_earlier_results(self, order_id, risk_result=None, resource_result=None):
        from app.agents.delay_risk import DelayRiskAgent, OrderNotFoundError

        risk_agent = DelayRiskAgent(self.db)
        try:
            if risk_agent.get_order_facts(order_id) is None:
                raise OrderNotFoundError(f"Order '{order_id}' not found.")
            if resource_result is None:
                resource_result = risk_agent.get_resource_result(order_id)   # no LLM call
            if risk_result is None:
                risk_result = risk_agent.run(order_id=order_id, resource_result=resource_result)
        finally:
            self.db.rollback()   # read-only: nothing is ever committed here
        return risk_result, resource_result

    @staticmethod
    def get_drivers(risk_result: Dict[str, Any], resource_result: Dict[str, Any]) -> List[str]:
        flags = list(risk_result.get("risk_drivers") or []) + list((resource_result or {}).get("issues") or [])
        return [d for d in ACTION_RULES if d in flags]   # fixed order, no duplicates

    @staticmethod
    def extract_facts(risk_result: Dict[str, Any], resource_result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Real numbers for queries, reasons and the explanation (no invented values)."""
        f = risk_result.get("input_features") or {}
        resource = resource_result or {}
        calcs = resource.get("calculations") or {}
        material = resource.get("material") or {}
        supplier = resource.get("supplier") or {}
        machine = resource.get("machine") or {}

        quantity = f.get("quantity")
        days = calcs.get("days_remaining", f.get("days_remaining"))
        available = calcs.get("available_capacity_per_day", f.get("available_capacity_per_day"))
        shortfall = calcs.get("capacity_shortfall")
        if shortfall is None and None not in (quantity, available, days):
            shortfall = max(float(quantity) - float(available) * max(float(days), 0), 0.0)
        material_left = calcs.get("material_available")
        return {
            "quantity": quantity,
            "days_remaining": days,
            "available_capacity_per_day": available,
            "needed_per_day": (float(quantity) / max(float(days), 1.0)) if quantity is not None and days is not None else None,
            "capacity_shortfall": shortfall,
            "required_production_days": calcs.get("required_production_days", f.get("required_production_days")),
            "workload_pct": f.get("machine_current_workload_pct"),
            "machine_id": machine.get("machine_id"),
            "machine_status": machine.get("status", f.get("machine_status")),
            "material_name": material.get("material_name"),
            "material_required": calcs.get("material_required", f.get("material_required")),
            "material_stock": material.get("stock_qty", f.get("material_stock_available")),
            "material_shortage_qty": max(-float(material_left), 0.0) if material_left is not None else None,
            "supplier_id": supplier.get("supplier_id"),
            "supplier_lead_time": supplier.get("avg_lead_time_days", f.get("supplier_lead_time")),
            "supplier_reliability": supplier.get("reliability_score", f.get("supplier_reliability")),
        }

    # ---------- pipeline steps ----------
    def build_queries(self, drivers: List[str], facts: Dict[str, Any],
                      top_factors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        risky = [x["feature"].replace("_", " ") for x in top_factors if x.get("direction") == "increases risk"]
        queries = []
        for driver in drivers:
            numbers = driver_numbers(driver, facts)
            for rule in ACTION_RULES[driver]:
                query = f"{rule['query']}. {DRIVER_TEXT[driver]}"
                if numbers:
                    query += f": {numbers}"
                if risky:
                    query += f". Risk factors: {', '.join(risky[:3])}"
                queries.append({"driver": driver, "rule": rule, "query": query})
        return queries

    def retrieve(self, queries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """Top SOPs per query (keyed by query text)."""
        return {q["query"]: retriever.search(q["query"], top_k=TOP_K_PER_QUERY) for q in queries}

    def select_actions(self, queries: List[Dict[str, Any]], retrieved: Dict[str, List[Dict[str, Any]]],
                       facts: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
        """Keep an action only if at least one retrieved SOP supports it. Never invent one."""
        merged: Dict[str, Dict[str, Any]] = {}
        dropped: List[Dict[str, str]] = []
        for q in queries:
            rule, driver = q["rule"], q["driver"]
            supporting = [
                doc for doc in retrieved[q["query"]]
                if any(term in f"{doc['title']} {doc['text']}".lower() for term in rule["support_terms"])
            ]
            if not supporting:
                logger.info(f"Dropped action '{rule['action']}' for {driver}: no retrieved SOP supports it")
                dropped.append({"action": rule["action"], "driver": driver,
                                "reason": "no retrieved SOP supports this action"})
                continue
            action = merged.setdefault(rule["action"], {"action": rule["action"], "drivers": [],
                                                        "reasons": [], "sources": {}})
            if driver not in action["drivers"]:
                action["drivers"].append(driver)
                action["reasons"].append(driver_reason(driver, facts))
            for doc in supporting:
                best = action["sources"].get(doc["document_id"])
                if best is None or doc["score"] > best["score"]:
                    action["sources"][doc["document_id"]] = {
                        "document_id": doc["document_id"], "title": doc["title"], "score": doc["score"]}

        actions = []
        for a in merged.values():
            rule_terms = [t for q in queries if q["rule"]["action"] == a["action"] for t in q["rule"]["support_terms"]]
            # SOPs that name the action in their title or tags first (most specific), then by score
            titled = {d["document_id"] for docs in retrieved.values() for d in docs
                      if any(t in f"{d['title']} {' '.join(d['tags'])}".lower() for t in rule_terms)}
            sources = sorted(a["sources"].values(), key=lambda s: (s["document_id"] not in titled, -s["score"]))
            actions.append({"action": a["action"], "drivers": a["drivers"], "reason": " ".join(a["reasons"]),
                            "sources": sources, "requires_manager_approval": True})
        # An action that was supported for one driver is not "dropped"
        dropped = [d for d in dropped if d["action"] not in merged]
        return actions, dropped

    def rank_actions(self, actions: List[Dict[str, Any]], top_factors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Rank by the model impact of the action's drivers, then by retrieval score."""
        def driver_weight(driver: str) -> float:
            return sum(f.get("impact", 0.0) for f in top_factors
                       if f.get("direction") == "increases risk" and f.get("feature") in DRIVER_FEATURES[driver])

        ranked = sorted(
            actions,
            key=lambda a: (-max(driver_weight(d) for d in a["drivers"]),
                           -a["sources"][0]["score"]),
        )[:MAX_ACTIONS]
        return [{"rank": i + 1, **a} for i, a in enumerate(ranked)]

    def explain(self, level: str, pct: float, drivers: List[str], facts: Dict[str, Any],
                actions: List[Dict[str, Any]]) -> Tuple[str, str]:
        template = self.template_explanation(level, pct, drivers, facts, actions)
        if os.getenv("USE_LLM_EXPLANATION", "false").strip().lower() != "true" or not actions:
            return template, "template"
        try:
            return self._llm_polish(template, pct, actions), "llm"
        except Exception as e:   # 401, 429, timeout, bad output ... -> template
            logger.warning(f"LLM explanation failed, using template: {e}")
            return template, "template"

    @staticmethod
    def template_explanation(level: str, pct: float, drivers: List[str], facts: Dict[str, Any],
                             actions: List[Dict[str, Any]]) -> str:
        parts = [f"Delay risk is {level.upper()} ({pct:.1f}%)."]
        parts += [driver_reason(d, facts) for d in drivers]
        if not drivers:
            parts.append("The Resource Agent reported no specific risk driver for this order.")
        if actions:
            steps = [
                f"{a['rank']}. {a['action']} (SOP {', '.join(s['document_id'] for s in a['sources'][:2])}: "
                f"{a['sources'][0]['title']})"
                for a in actions
            ]
            parts.append("Recommended actions: " + "; ".join(steps) + ".")
            parts.append("Every action needs manager approval before anything changes.")
        else:
            parts.append("No action could be backed by a knowledge-base SOP, so none is recommended; "
                         "please review the order manually.")
        return " ".join(parts)

    def _llm_polish(self, template: str, pct: float, actions: List[Dict[str, Any]]) -> str:
        from app.services.llm_client import LLMClient

        prompt = (
            "Rewrite this recommendation summary for a production manager in at most 120 words. "
            "Keep every number and every SOP ID (KBxxx) exactly as written. Do not add actions, "
            "procedures, numbers or sources.\n\n"
            f"{template}\n\nReturn JSON: {{\"explanation\": \"...\"}}"
        )
        polished = json.loads(LLMClient().generate(prompt)).get("explanation", "")
        cited = {s["document_id"] for a in actions for s in a["sources"][:2]}
        if f"{pct:.1f}%" not in polished or not all(doc_id in polished for doc_id in cited):
            raise ValueError("LLM output dropped the probability or an SOP ID")
        return polished

    def build_result(self, order_id, status, risk_result, drivers, actions, dropped, retrieved,
                     explanation, explanation_source, backend) -> Dict[str, Any]:
        documents: Dict[str, Dict[str, Any]] = {}
        for results in retrieved.values():
            for doc in results:
                if doc["document_id"] not in documents or doc["score"] > documents[doc["document_id"]]["score"]:
                    documents[doc["document_id"]] = doc
        return {
            "order_id": order_id,
            "status": status,
            "risk_level": risk_result["risk_level"],
            "delay_probability_pct": float(risk_result["delay_probability_pct"]),
            "drivers": drivers,
            "actions": actions,
            "dropped_actions": dropped,
            "retrieved_documents": sorted(documents.values(), key=lambda d: -d["score"]),
            "explanation": explanation,
            "explanation_source": explanation_source,
            "retrieval_backend": backend,
            "data_source": "postgresql",
        }


# ---------- reasons with the real numbers ----------
def _n(value, digits=0) -> str:
    return "?" if value is None else f"{float(value):,.{digits}f}"


def driver_numbers(driver: str, f: Dict[str, Any]) -> str:
    if driver == "MACHINE_CAPACITY_SHORTAGE":
        return (f"shortfall {_n(f['capacity_shortfall'])} units, {_n(f['available_capacity_per_day'])} "
                f"units/day available vs {_n(f['needed_per_day'])} needed")
    if driver == "MATERIAL_SHORTAGE":
        return f"short by {_n(f['material_shortage_qty'])} units of {f['material_name'] or 'material'}"
    if driver == "SUPPLIER_DELAY_RISK":
        return f"lead time {_n(f['supplier_lead_time'])} days, {_n(f['days_remaining'])} days remaining"
    if driver == "DEADLINE_TOO_TIGHT":
        return f"needs {_n(f['required_production_days'], 1)} days, {_n(f['days_remaining'])} days remaining"
    return ""


def driver_reason(driver: str, f: Dict[str, Any]) -> str:
    if driver == "MACHINE_CAPACITY_SHORTAGE":
        return (f"Capacity shortfall of {_n(f['capacity_shortfall'])} units: the machine has "
                f"{_n(f['available_capacity_per_day'])} units/day available vs {_n(f['needed_per_day'])} "
                f"needed per day to finish {_n(f['quantity'])} units in {_n(f['days_remaining'])} days.")
    if driver == "MACHINE_UNAVAILABLE":
        return "No operational machine is available for this order."
    if driver == "MATERIAL_SHORTAGE":
        return (f"Material shortage of {_n(f['material_shortage_qty'])} units of "
                f"{f['material_name'] or 'the material'}: {_n(f['material_required'])} required vs "
                f"{_n(f['material_stock'])} in stock.")
    if driver == "SUPPLIER_DELAY_RISK":
        return (f"Supplier {f['supplier_id'] or ''} has a {_n(f['supplier_lead_time'])}-day lead time and "
                f"reliability {_n(f['supplier_reliability'], 2)}, with {_n(f['days_remaining'])} days remaining.")
    if driver == "DEADLINE_TOO_TIGHT":
        return (f"Production needs {_n(f['required_production_days'], 1)} days but only "
                f"{_n(f['days_remaining'])} days remain.")
    return ""


# ---------- manager decisions (the only write in Phase 4) ----------
CREATE_DECISIONS_SQL = """
CREATE TABLE IF NOT EXISTS recommendation_decisions (
    id          SERIAL PRIMARY KEY,
    order_id    VARCHAR(20)  NOT NULL,
    action      VARCHAR(200) NOT NULL,
    decision    VARCHAR(20)  NOT NULL CHECK (decision IN ('approved', 'rejected', 'overridden')),
    comment     TEXT,
    decided_by  VARCHAR(100) NOT NULL,
    decided_at  TIMESTAMP    NOT NULL DEFAULT NOW()
)
"""
CREATE_DECISIONS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS ix_recommendation_decisions_order_id
    ON recommendation_decisions (order_id)
"""


def ensure_decisions_table(db: Session) -> None:
    db.execute(text(CREATE_DECISIONS_SQL))
    db.execute(text(CREATE_DECISIONS_INDEX_SQL))
    db.commit()


def order_exists(db: Session, order_id: str) -> bool:
    found = db.execute(text("SELECT 1 FROM cust_ord_table WHERE cus_ord_id = :oid"), {"oid": order_id}).scalar()
    db.rollback()
    return found is not None


def save_decision(db: Session, order_id: str, action: str, decision: str,
                  comment: Optional[str], decided_by: str) -> Dict[str, Any]:
    ensure_decisions_table(db)
    row = db.execute(
        text("""
            INSERT INTO recommendation_decisions (order_id, action, decision, comment, decided_by)
            VALUES (:order_id, :action, :decision, :comment, :decided_by)
            RETURNING id, order_id, action, decision, comment, decided_by, decided_at
        """),
        {"order_id": order_id, "action": action, "decision": decision,
         "comment": comment, "decided_by": decided_by},
    ).mappings().fetchone()
    db.commit()
    return dict(row)


def list_decisions(db: Session, order_id: str) -> List[Dict[str, Any]]:
    ensure_decisions_table(db)
    rows = db.execute(
        text("""
            SELECT id, order_id, action, decision, comment, decided_by, decided_at
            FROM recommendation_decisions WHERE order_id = :order_id
            ORDER BY decided_at DESC, id DESC
        """),
        {"order_id": order_id},
    ).mappings().fetchall()
    return [dict(r) for r in rows]
