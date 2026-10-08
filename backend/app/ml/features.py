"""
Feature definitions for the Delay Risk model.

One place defines the feature names, so training (train.py) and prediction
(delay_risk.py) always use exactly the same columns, names, units and scale.

Training data: the PostgreSQL `orders` table (3000 rows, inspected in Phase 3).
Prediction data: the Resource & Production Agent result (ResourceAnalyzeResponse)
plus facts from `cust_ord_table`, converted by features_from_resource_result().
"""
import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import text


TARGET = "delayed"

# Categorical columns -> one-hot encoded in the model pipeline
CATEGORICAL_FEATURES = ["product_type", "priority", "machine_status"]

# Yes/no columns -> stored as 0/1 for the model
BOOLEAN_FEATURES = [
    "capacity_shortfall",
    "tight_deadline",
    "material_shortage",
    "supplier_risk",
]

# Numeric columns -> passed to the model unscaled (Random Forest needs no scaling)
NUMERIC_FEATURES = [
    "quantity",
    "days_remaining",
    "machine_capacity_per_day",
    "machine_current_workload_pct",   # FRACTION 0-1 (0.53 = 53%), as in the orders table
    "available_capacity_per_day",
    "required_production_days",
    "material_required",
    "material_stock_available",
    "supplier_lead_time",
    "supplier_reliability",
    "historical_delay_rate_product",
]

# Derived feature: how many deadlines' worth of work the order needs
DERIVED_FEATURES = ["production_to_deadline_ratio"]

# The 18 raw features taken from the data (used for the missing-feature count)
BASE_FEATURES = NUMERIC_FEATURES + BOOLEAN_FEATURES + CATEGORICAL_FEATURES

# Every column the model sees, in a fixed order
FEATURES = NUMERIC_FEATURES + BOOLEAN_FEATURES + DERIVED_FEATURES + CATEGORICAL_FEATURES

# Never use these as features: the target, values computed from the target,
# identifiers and raw dates (data leakage / no generalisation).
LEAKAGE_COLUMNS = [
    "delay_probability",
    "delayed",
    "delay_reasons",
    "order_id",
    "customer_name",
    "order_date",
    "deadline_date",
]

# Rule that reproduces orders.supplier_risk in 100% of the 3000 training rows
SUPPLIER_RELIABILITY_THRESHOLD = 0.8
SUPPLIER_LEAD_TIME_THRESHOLD_DAYS = 12

# Required production days when there is no free capacity at all (Resource
# Agent returns infinity). Set just above the training maximum (449 days).
REQUIRED_DAYS_CAP = 500.0


def supplier_risk_rule(reliability: float, lead_time_days: float) -> bool:
    return (
        reliability < SUPPLIER_RELIABILITY_THRESHOLD
        and lead_time_days > SUPPLIER_LEAD_TIME_THRESHOLD_DAYS
    )


def production_to_deadline_ratio(required_days: float, days_remaining: float) -> float:
    # max(.., 1) avoids division by zero for deadlines today or in the past
    return float(required_days) / max(float(days_remaining), 1.0)


def load_training_data(engine) -> pd.DataFrame:
    """Read the training rows from PostgreSQL (read-only transaction)."""
    columns = ", ".join(BASE_FEATURES + [TARGET])
    with engine.connect() as conn:
        conn.execute(text("SET TRANSACTION READ ONLY"))
        df = pd.read_sql(text(f"SELECT {columns} FROM orders"), conn)
    return prepare_frame(df)


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise dtypes and add the derived feature (same for training and prediction)."""
    df = df.copy()
    for col in NUMERIC_FEATURES:
        df[col] = df[col].astype(float)
    for col in BOOLEAN_FEATURES:
        df[col] = df[col].astype(bool).astype(int)
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype(str)
    df["production_to_deadline_ratio"] = [
        production_to_deadline_ratio(r, d)
        for r, d in zip(df["required_production_days"], df["days_remaining"])
    ]
    return df


def _to_dict(obj: Any) -> Optional[Dict[str, Any]]:
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return dict(obj)


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def features_from_resource_result(
    resource: Dict[str, Any],
    order_facts: Optional[Dict[str, Any]],
    historical_delay_rate: Optional[float],
) -> Tuple[Dict[str, Any], List[str]]:
    """
    Convert a Resource & Production Agent result into the training feature names,
    units and scale. Returns (features, missing_feature_names).

    Conversions (Resource Agent field -> training column):
      calculations.days_remaining              -> days_remaining
      machine.machine_capacity_per_day         -> machine_capacity_per_day
      machine.machine_current_workload_pct     -> machine_current_workload_pct
          The training data stores workload as a FRACTION (0.12 = 12%). A value
          above 1 can only be a percent (e.g. 53), so it is divided by 100.
      machine.status                           -> machine_status
      calculations.available_capacity_per_day  -> available_capacity_per_day
      calculations.required_production_days    -> required_production_days
          (infinity = no free capacity -> capped at REQUIRED_DAYS_CAP)
      calculations.capacity_shortfall (UNITS)  -> capacity_shortfall (BOOLEAN: units > 0)
      calculations.tight_deadline              -> tight_deadline
      calculations.material_required           -> material_required
      material.stock_qty                       -> material_stock_available
          (NOT calculations.material_available, which is stock minus required)
      calculations.material_available < 0      -> material_shortage
      supplier.avg_lead_time_days              -> supplier_lead_time
      supplier.reliability_score               -> supplier_reliability
      supplier_risk_rule(reliability, lead)    -> supplier_risk (same rule as the training data)
      cust_ord_table quantity/product/priority -> quantity, product_type, priority
      SQL on orders (passed in)                -> historical_delay_rate_product
    """
    resource = resource or {}
    order_facts = order_facts or {}
    machine = _to_dict(resource.get("machine"))
    material = _to_dict(resource.get("material"))
    supplier = _to_dict(resource.get("supplier"))
    calcs = _to_dict(resource.get("calculations"))

    f: Dict[str, Any] = {name: None for name in BASE_FEATURES}
    missing: List[str] = []

    if calcs:
        f["days_remaining"] = _num(calcs.get("days_remaining"))
        f["available_capacity_per_day"] = _num(calcs.get("available_capacity_per_day"))
        req_days = _num(calcs.get("required_production_days"))
        if req_days is not None and math.isinf(req_days):
            req_days = REQUIRED_DAYS_CAP
        f["required_production_days"] = req_days
        shortfall = _num(calcs.get("capacity_shortfall"))
        f["capacity_shortfall"] = None if shortfall is None else shortfall > 0
        tight = calcs.get("tight_deadline")
        f["tight_deadline"] = None if tight is None else bool(tight)

    if machine:
        f["machine_capacity_per_day"] = _num(machine.get("machine_capacity_per_day"))
        workload = _num(machine.get("machine_current_workload_pct"))
        if workload is not None and workload > 1:
            workload = workload / 100.0          # percent -> fraction
        f["machine_current_workload_pct"] = workload
        f["machine_status"] = machine.get("status")

    # Material values from calculations are only meaningful if a material was found
    if material:
        f["material_stock_available"] = _num(material.get("stock_qty"))
        if calcs:
            f["material_required"] = _num(calcs.get("material_required"))
            available_after = _num(calcs.get("material_available"))
            f["material_shortage"] = None if available_after is None else available_after < 0

    if supplier:
        lead = _num(supplier.get("avg_lead_time_days"))
        reliability = _num(supplier.get("reliability_score"))
        f["supplier_lead_time"] = lead
        f["supplier_reliability"] = reliability
        if lead is not None and reliability is not None:
            f["supplier_risk"] = supplier_risk_rule(reliability, lead)

    f["historical_delay_rate_product"] = _num(historical_delay_rate)

    # Order facts (not part of the Resource Agent JSON)
    f["quantity"] = _num(order_facts.get("quantity"))
    f["product_type"] = order_facts.get("product_type")
    f["priority"] = order_facts.get("priority")

    # Safe defaults - only where they are sensible. Each one is still reported.
    if f["quantity"] is None:
        missing.append("quantity")
        avail, req = f["available_capacity_per_day"], f["required_production_days"]
        # required_production_days = quantity / available capacity (Resource Agent formula)
        if avail and req is not None and req < REQUIRED_DAYS_CAP:
            f["quantity"] = round(avail * req)
    if not f["product_type"]:
        missing.append("product_type")
        f["product_type"] = "UNKNOWN"            # one-hot encoder ignores unknown values
    if not f["priority"]:
        missing.append("priority")
        f["priority"] = "Medium"                 # the Order Agent's default priority

    for name in BASE_FEATURES:
        if f[name] is None and name not in missing:
            missing.append(name)

    if f["required_production_days"] is not None and f["days_remaining"] is not None:
        f["production_to_deadline_ratio"] = production_to_deadline_ratio(
            f["required_production_days"], f["days_remaining"]
        )
    else:
        f["production_to_deadline_ratio"] = None

    return f, missing


def to_model_frame(features: Dict[str, Any]) -> pd.DataFrame:
    """One-row DataFrame in the exact column order and dtypes used in training."""
    row = {name: features.get(name) for name in FEATURES}
    df = pd.DataFrame([row], columns=FEATURES)
    for col in NUMERIC_FEATURES + DERIVED_FEATURES:
        df[col] = df[col].astype(float)
    for col in BOOLEAN_FEATURES:
        df[col] = df[col].astype(bool).astype(int)
    for col in CATEGORICAL_FEATURES:
        df[col] = df[col].astype(str)
    return df
