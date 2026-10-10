"""
Phase 3 - Delay Prediction / Risk Agent.

Resource Agent result (JSON) + PostgreSQL facts
    -> build_features()  (same names/units/scale as the training data)
    -> predict()         (Random Forest probability - the ONLY source of the number)
    -> classify_risk()   (Low / Medium / High)
    -> explain()         (top factors + Python template; LLM polish optional, off by default)
    -> build_result()

The agent is read-only: it never writes to the database.
"""
#
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml import predictor
from app.ml.features import BASE_FEATURES, features_from_resource_result, to_model_frame

logger = logging.getLogger(__name__)


# Risk levels from the project document
LOW_MAX = 0.30      # 0.00 - 0.30  -> Low
MEDIUM_MAX = 0.60   # 0.30 - 0.60  -> Medium, above -> High

# More missing features than this -> refuse to predict instead of guessing
MAX_MISSING_FEATURES = 4

TOP_FACTORS = 5
RISK_DRIVER_FLAGS = [
    "MACHINE_CAPACITY_SHORTAGE",
    "MATERIAL_SHORTAGE",
    "DEADLINE_TOO_TIGHT",
    "SUPPLIER_DELAY_RISK",
]

FEATURE_LABELS = {
    "quantity": "order quantity",
    "days_remaining": "days remaining",
    "machine_capacity_per_day": "machine capacity per day",
    "machine_current_workload_pct": "machine workload",
    "available_capacity_per_day": "available capacity per day",
    "required_production_days": "required production days",
    "material_required": "material required",
    "material_stock_available": "material stock",
    "supplier_lead_time": "supplier lead time (days)",
    "supplier_reliability": "supplier reliability",
    "historical_delay_rate_product": "historical delay rate of the product",
    "capacity_shortfall": "machine capacity shortfall",
    "tight_deadline": "tight deadline",
    "material_shortage": "material shortage",
    "supplier_risk": "supplier risk",
    "production_to_deadline_ratio": "production time vs deadline ratio",
    "product_type": "product type",
    "priority": "priority",
    "machine_status": "machine status",
}


class OrderNotFoundError(LookupError):
    pass


class InvalidRiskInputError(ValueError):
    pass


# Main class responsible for predicting order delay risk using a trained ML model.
class DelayRiskAgent:
    def __init__(self, db: Session, model_path=None):
        self.db = db
        self.model_path = model_path

    # ---------- entry point -----------------
    def run(
        self,
        order_id: Optional[str] = None,
        resource_result: Optional[Dict[str, Any]] = None,
        order: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # Load the trained model and coordinate the complete delay prediction workflow.
        bundle = predictor.load_model(self.model_path)   # fails fast if not trained

        try:
            if resource_result is None:
                if not order_id:
                    raise InvalidRiskInputError("Provide either 'order_id' or 'resource_result'.")
                order_facts = self.get_order_facts(order_id)
                if order_facts is None:
                    raise OrderNotFoundError(f"Order '{order_id}' not found.")
                resource_result = self.get_resource_result(order_id)
            else:
                order_id = order_id or resource_result.get("order_id") or "UNKNOWN"
                order_facts = self.get_order_facts(order_id) or {}

            if order:
                order_facts = {**order_facts, **{k: v for k, v in order.items() if v is not None}}

            hist_rate = self.get_historical_rate(order_facts.get("product_type"))
            features, missing = self.build_features(resource_result, order_facts, hist_rate, bundle)
        finally:
            self.db.rollback()   # end the read-only transaction; nothing is ever committed

        probability = self.predict(features, bundle)
        risk_level = self.classify_risk(probability)
        top_factors = predictor.explain_local(bundle, to_model_frame(features), TOP_FACTORS)
        risk_drivers = [i for i in resource_result.get("issues") or [] if i in RISK_DRIVER_FLAGS]
        explanation, source = self.explain(probability, risk_level, top_factors, features, risk_drivers)
        return self.build_result(
            order_id, probability, risk_level, top_factors, risk_drivers,
            explanation, source, features, missing, bundle,
        )

    # ---------- data access (read-only) ----------
    def _read_only(self) -> None:
        # New transaction in READ ONLY mode: PostgreSQL rejects any write in it.
        self.db.rollback()
        self.db.execute(text("SET TRANSACTION READ ONLY"))
# Retrieve order details from PostgreSQL using a read-only database transaction.
    def get_order_facts(self, order_id: str) -> Optional[Dict[str, Any]]:
        self._read_only()
        row = self.db.execute(
            text("""
                SELECT cus_ord_id, product_type, quantity, priority, deadline_date, material_name
                FROM cust_ord_table WHERE cus_ord_id = :oid
            """),
            {"oid": order_id},
        ).mappings().fetchone()
        return dict(row) if row else None
# Call the Resource & Production Agent to analyze machine capacity and material availability.
    def get_resource_result(self, order_id: str) -> Dict[str, Any]:
        """Run the existing Resource & Production Agent (imported, unchanged).

        Uses its fetch_data() and calculate() steps only, so no LLM call is made.
        """
        from app.agents.resource_production import ResourceProductionAgent
        from app.schemas.resource import ResourceAnalyzeRequest

        self._read_only()
        agent = ResourceProductionAgent(self.db)
        request = ResourceAnalyzeRequest(order_id=order_id)
        data = agent.fetch_data(request)
        if data.get("issue") == "MATERIAL_NOT_FOUND":
            result = agent.build_result(request, data, template_only=True)
        else:
            calcs, issues = agent.calculate(data)
            result = agent.build_result(
                request, data, calcs, issues,
                explanation="(resource explanation skipped by Delay Risk Agent)",
                explanation_source="template",
            )
        return result.model_dump()
# Calculate the historical delay rate for the product to support accurate risk prediction.
    def get_historical_rate(self, product_type: Optional[str]) -> float:
        """Historical delay rate of the product from the `orders` table.

        Uses the stored historical_delay_rate_product column (the same values the
        model was trained on); unknown products fall back to the global average.
        """
        self._read_only()
        rate = None
        if product_type:
            rate = self.db.execute(
                text("""
                    SELECT AVG(historical_delay_rate_product) FROM orders
                    WHERE LOWER(TRIM(product_type)) = LOWER(TRIM(:p))
                """),
                {"p": product_type},
            ).scalar()
        if rate is None:
            rate = self.db.execute(
                text("SELECT AVG(historical_delay_rate_product) FROM orders")
            ).scalar()
        return float(rate)

    # ---------- pipeline steps ----------
    def build_features(
        self,
        resource_result: Dict[str, Any],
        order_facts: Optional[Dict[str, Any]],
        historical_rate: Optional[float],
        bundle: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], List[str]]:
        # Convert order and resource information into the features required by the ML model.
        features, missing = features_from_resource_result(resource_result, order_facts, historical_rate)

        if len(missing) > MAX_MISSING_FEATURES:
            issues = ", ".join(resource_result.get("issues") or []) or "none"
            raise InvalidRiskInputError(
                f"Too many missing features to predict reliably ({len(missing)} of "
                f"{len(BASE_FEATURES)}): {', '.join(missing)}. Resource issues: {issues}."
            )

        # A few missing values: fill with the typical training value (listed in missing_features)
        bundle = bundle or predictor.load_model(self.model_path)
        for name in missing:
            if features.get(name) is None:
                features[name] = bundle["baselines"][name]
        if features.get("production_to_deadline_ratio") is None:
            features["production_to_deadline_ratio"] = bundle["baselines"]["production_to_deadline_ratio"]
        return features, missing

    def predict(self, features: Dict[str, Any], bundle: Optional[Dict[str, Any]] = None) -> float:
        bundle = bundle or predictor.load_model(self.model_path)
        return predictor.predict_proba(bundle, to_model_frame(features))
# Classify the predicted delay probability into Low, Medium, or High risk.
    @staticmethod
    def classify_risk(probability: float) -> str:
        if probability <= LOW_MAX:
            return "Low"
        if probability <= MEDIUM_MAX:
            return "Medium"
        return "High"

    def explain(
        self,
        probability: float,
        risk_level: str,
        top_factors: List[Dict[str, Any]],
        features: Dict[str, Any],
        risk_drivers: List[str],
    ) -> Tuple[str, str]:
        template = self.template_explanation(probability, risk_level, top_factors, features, risk_drivers)

        if os.getenv("USE_LLM_EXPLANATION", "false").strip().lower() != "true":
            return template, "template"
        try:
            return self._llm_polish(template, probability), "llm"
        except Exception as e:   # 401, 429, timeout, bad output ... -> template
            logger.warning(f"LLM explanation failed, using template: {e}")
            return template, "template"
# Generate a human-readable explanation using the prediction and its most influential factors.
    @staticmethod
    def template_explanation(
        probability: float,
        risk_level: str,
        top_factors: List[Dict[str, Any]],
        features: Dict[str, Any],
        risk_drivers: List[str],
    ) -> str:
        pct = probability * 100
        raising = [f for f in top_factors if f["direction"] == "increases risk"]
        lowering = [f for f in top_factors if f["direction"] == "reduces risk"]

        text_out = f"Delay risk is {risk_level.upper()} ({pct:.1f}%). "
        if raising:
            text_out += "Main reasons: " + "; ".join(_describe(f) for f in raising) + ". "
        if lowering:
            text_out += "Lowering the risk: " + "; ".join(_describe(f) for f in lowering) + ". "
        text_out += (
            f"The order needs {features['required_production_days']:.1f} production days with "
            f"{features['days_remaining']:.0f} days remaining (available capacity "
            f"{features['available_capacity_per_day']:.1f} units/day, machine workload "
            f"{features['machine_current_workload_pct'] * 100:.0f}%)."
        )
        if risk_drivers:
            text_out += " Resource Agent flags: " + ", ".join(risk_drivers) + "."
        return text_out

    def _llm_polish(self, template: str, probability: float) -> str:
        from app.services.llm_client import LLMClient

        prompt = (
            "Rewrite this delay-risk explanation for a production manager in at most 90 words. "
            "Keep every number exactly as written; do not add facts or change the risk level.\n\n"
            f"{template}\n\n"
            'Return JSON: {"explanation": "..."}'
        )
        polished = json.loads(LLMClient().generate(prompt)).get("explanation", "")
        if f"{probability * 100:.1f}%" not in polished:
            raise ValueError("LLM output dropped the model's probability")
        return polished

    def build_result(
        self,
        order_id: str,
        probability: float,
        risk_level: str,
        top_factors: List[Dict[str, Any]],
        risk_drivers: List[str],
        explanation: str,
        explanation_source: str,
        features: Dict[str, Any],
        missing: List[str],
        bundle: Dict[str, Any],
    ) -> Dict[str, Any]:
        input_features = {
            k: (round(v, 4) if isinstance(v, float) else v) for k, v in features.items()
        }
        return {
            "order_id": order_id,
            "delay_probability": round(probability, 4),
            "delay_probability_pct": round(probability * 100, 1),
            "risk_level": risk_level,
            "thresholds": {"low_max": LOW_MAX, "medium_max": MEDIUM_MAX},
            "top_factors": top_factors,
            "risk_drivers": risk_drivers,
            "explanation": explanation,
            "explanation_source": explanation_source,
            "input_features": input_features,
            "missing_features": missing,
            "model": {
                "name": bundle["model_name"],
                "trained_at": bundle["trained_at"],
                "roc_auc": bundle["roc_auc"],
                "calibrated": bundle.get("calibrated", False),
            },
            "data_source": "postgresql",
        }


def _describe(factor: Dict[str, Any]) -> str:
    name, value = factor["feature"], factor["value"]
    label = FEATURE_LABELS.get(name, name)
    if isinstance(value, bool):
        shown = "yes" if value else "no"
    elif name == "machine_current_workload_pct":
        shown = f"{value * 100:.0f}%"
    elif isinstance(value, float):
        shown = f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
    else:
        shown = str(value)
    return f"{label} {shown} ({factor['impact'] * 100:.0f}% of impact)"
