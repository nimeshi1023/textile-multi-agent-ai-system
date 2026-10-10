from typing import Dict, List, Any, Optional
import json
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import text
import logging

from app.schemas.resource import (
    ResourceAnalyzeRequest,
    ResourceAnalyzeResponse,
    ResourceCalculations,
    MachineInfo,
    MaterialInfo,
    SupplierInfo
)
from app.db.models import CustOrd
from app.services.llm_client import LLMClient
from app.services.material_service import MaterialService

logger = logging.getLogger(__name__)

# Constants
RELIABILITY_THRESHOLD = 0.8
MIN_CAPACITY_EPSILON = 0.001


def _fmt2(value) -> str:
    """Number with two decimal places and thousands separators, e.g. 1170.3999 -> '1,170.40'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number in (float("inf"), float("-inf")):
        return "∞"
    return f"{number:,.2f}"

class ResourceProductionAgent:
    def __init__(self, db: Session):
        self.db = db
        self.llm_client = LLMClient()

    def run(self, request: ResourceAnalyzeRequest) -> ResourceAnalyzeResponse:
        # 1. Fetch Data
        data = self.fetch_data(request)
        
        if "issue" in data and data["issue"] == "MATERIAL_NOT_FOUND":
            return self.build_result(request, data, None, template_only=True)
            
        # 2. Calculate
        calcs, issues = self.calculate(data)
        
        # 3. Explain
        explanation, explanation_source = self.explain(data, calcs, issues)
        
        # 4. Build Result
        return self.build_result(request, data, calcs, issues, explanation, explanation_source)

    def fetch_data(self, req: ResourceAnalyzeRequest) -> Dict[str, Any]:
        result = {}
        
        # Load Orders
        if req.order_id and not req.quantity:
            order = self.db.query(CustOrd).filter(CustOrd.cus_ord_id == req.order_id).first()
            if order:
                result['order'] = {
                    'order_id': order.cus_ord_id,
                    'product_type': order.product_type,
                    'quantity': order.quantity,
                    'deadline_date': order.deadline_date,
                    'order_date': order.order_date,
                    'material_name': order.material_name,
                    'material_required': order.material_required
                }
            else:
                # Mock if not found
                result['order'] = {
                    'order_id': req.order_id,
                    'quantity': 1,
                    'deadline_date': date.today(),
                    'order_date': date.today(),
                    'material_name': "UNKNOWN"
                }
        else:
            result['order'] = {
                'order_id': req.order_id or "UNKNOWN",
                'product_type': req.product_type,
                'quantity': req.quantity,
                'deadline_date': req.deadline_date,
                'order_date': date.today(),
                'material_name': req.material_name,
                'material_required': req.material_required
            }

        # Material & Suppliers
        mat_name = result['order']['material_name']
        if mat_name:
            mat_query = text("""
                SELECT material_name, stock_qty, usage_per_unit, reorder_lead_time_days, supplier_id 
                FROM materials 
                WHERE LOWER(TRIM(material_name)) = LOWER(TRIM(:mname))
            """)
            try:
                mat_row = self.db.execute(mat_query, {"mname": mat_name}).fetchone()
                if mat_row:
                    result['material'] = MaterialInfo(
                        material_name=mat_row[0],
                        stock_qty=float(mat_row[1]),
                        usage_per_unit=float(mat_row[2]),
                        reorder_lead_time_days=int(mat_row[3]),
                        supplier_id=mat_row[4]
                    )
                    
                    if mat_row[4]:
                        sup_query = text("""
                            SELECT supplier_id, avg_lead_time_days, reliability_score 
                            FROM suppliers 
                            WHERE supplier_id = :sid
                        """)
                        sup_row = self.db.execute(sup_query, {"sid": mat_row[4]}).fetchone()
                        if sup_row:
                            result['supplier'] = SupplierInfo(
                                supplier_id=sup_row[0],
                                avg_lead_time_days=int(sup_row[1]),
                                reliability_score=float(sup_row[2])
                            )
                else:
                    result['issue'] = "MATERIAL_NOT_FOUND"
                    # suggest closest could go here
            except Exception as e:
                logger.error(f"Material DB fetch error: {e}")
                # Fallback mock for testing if DB table is missing
                result['material'] = MaterialInfo(
                    material_name=mat_name,
                    stock_qty=3000.0,
                    usage_per_unit=0.25,
                    reorder_lead_time_days=5,
                    supplier_id="SUP-01"
                )

        # Machine details
        try:
            mch_query = text("""
                SELECT machine_id, machine_capacity_per_day, machine_current_workload_pct, status 
                FROM machines 
                WHERE status = 'Operational' AND machine_id != :fmid
                ORDER BY machine_capacity_per_day DESC LIMIT 1
            """)
            mch_row = self.db.execute(mch_query, {"fmid": req.failed_machine_id or ""}).fetchone()
            if mch_row:
                result['machine'] = MachineInfo(
                    machine_id=mch_row[0],
                    machine_capacity_per_day=float(mch_row[1]),
                    machine_current_workload_pct=float(mch_row[2]),
                    status=mch_row[3]
                )
            else:
                result['machine'] = None
        except Exception as e:
            logger.error(f"Machine DB fetch error: {e}")
            # Fallback mock for testing
            result['machine'] = MachineInfo(
                machine_id="MCH01",
                machine_capacity_per_day=1500.0,
                machine_current_workload_pct=0.0,
                status="Operational"
            )

        return result

    def calculate(self, data: Dict[str, Any]) -> tuple[ResourceCalculations, List[str]]:
        order = data['order']
        mat = data.get('material')
        mch = data.get('machine')
        sup = data.get('supplier')
        
        issues = []
        
        days_remaining = (order['deadline_date'] - order['order_date']).days
        
        material_required, material_source = self.resolve_material_required(order, mat)
        material_available = 0.0
        if mat:
            material_available = float(mat.stock_qty) - material_required
            if material_available < 0:
                issues.append("MATERIAL_SHORTAGE")
                
        available_capacity_per_day = 0.0
        required_production_days = 0.0
        capacity_in_deadline = 0.0
        capacity_shortfall = 0.0
        
        if mch:
            available_capacity_per_day = float(mch.machine_capacity_per_day) * (1.0 - float(mch.machine_current_workload_pct))
            if available_capacity_per_day > MIN_CAPACITY_EPSILON:
                required_production_days = float(order['quantity']) / available_capacity_per_day
                capacity_in_deadline = available_capacity_per_day * max(days_remaining, 0)
                capacity_shortfall = max(float(order['quantity']) - capacity_in_deadline, 0.0)
            else:
                required_production_days = float('inf')
                capacity_shortfall = float(order['quantity'])
                
            if capacity_shortfall > 0:
                issues.append("MACHINE_CAPACITY_SHORTAGE")
        else:
            issues.append("MACHINE_UNAVAILABLE")
            required_production_days = float('inf')
            capacity_shortfall = float(order['quantity'])
            
        tight_deadline = required_production_days > max(days_remaining, 0)
        if tight_deadline and mch:
            issues.append("DEADLINE_TOO_TIGHT")
            
        if sup and mat and material_available < 0:
            if sup.avg_lead_time_days > max(days_remaining, 0) or sup.reliability_score < RELIABILITY_THRESHOLD:
                issues.append("SUPPLIER_DELAY_RISK")

        calcs = ResourceCalculations(
            days_remaining=days_remaining,
            material_required=material_required,
            material_available=material_available,
            available_capacity_per_day=available_capacity_per_day,
            required_production_days=required_production_days,
            capacity_in_deadline=capacity_in_deadline,
            capacity_shortfall=capacity_shortfall,
            tight_deadline=tight_deadline,
            material_required_source=material_source
        )
        return calcs, issues

    def resolve_material_required(self, order: Dict[str, Any], mat) -> tuple[float, str]:
        """Same material_required as the Order Analysis step:
        1. the amount on the order (stated by the customer, or estimated and confirmed by the manager),
        2. otherwise the same estimate the order step uses (quantity x consumption_per_piece
           from material_consumption, via MaterialService),
        3. last resort: quantity x usage_per_unit of the material."""
        stated = order.get('material_required')
        if stated is not None and float(stated) > 0:
            return float(stated), "order"

        if order.get('product_type') and order.get('quantity'):
            for attempt in range(2):
                try:
                    estimate = MaterialService.estimate_material(self.db, order['product_type'], int(order['quantity']))
                    if estimate is not None:
                        return float(estimate), "estimated"
                    break
                except Exception as e:
                    # An earlier failed query (e.g. the machine lookup) leaves the read-only
                    # transaction aborted: roll it back and try once more.
                    logger.error(f"Material estimate failed (attempt {attempt + 1}): {e}")
                    self.db.rollback()

        if mat and order.get('quantity'):
            return float(order['quantity']) * float(mat.usage_per_unit), "usage_per_unit"
        return 0.0, "missing"

    def explain(self, data: Dict[str, Any], calcs: ResourceCalculations, issues: List[str]) -> tuple[str, str]:
        order = data['order']
        mch = data.get('machine')
        
        # Template fallback
        mch_cap = mch.machine_capacity_per_day if mch else 0
        mch_stat = mch.status if mch else "Unavailable"
        mat_req = calcs.material_required
        mat_short = max(0, -calcs.material_available)
        mat_avail = max(0, calcs.material_available) if calcs.material_available > 0 else (mat_req - mat_short)
        req_days = calcs.required_production_days
        tight = calcs.tight_deadline
        iss_str = ", ".join(issues)

        # All numbers are shown with two decimal places (e.g. 1,170.40 instead of 1170.3999999999996)
        cap_s, req_s, avail_s, short_s = (_fmt2(mch_cap), _fmt2(mat_req), _fmt2(mat_avail), _fmt2(mat_short))
        days_s, qty_s = _fmt2(req_days), _fmt2(order['quantity'])

        template_text = (
            f"Machine capacity is {cap_s}/day (status: {mch_stat}). "
            f"Material required is {req_s}, available {avail_s} (shortage: {short_s}). "
            f"Production needs {days_s} days. Deadline tight: {tight}. Issues: {iss_str}."
        )

        prompt = f"""
        You are a Textile Resource and Production Agent.
        Explain the following resource analysis to a production manager.
        All numbers below are verified. Do NOT change them, recalculate them or invent data.
        Write every number exactly as given, with two decimal places.

        ORDER: quantity {qty_s} units, deadline in {calcs.days_remaining} days
        MACHINE: daily available capacity {cap_s} units, status {mch_stat}
        MATERIAL: required {req_s}, available {avail_s} (shortage {short_s})
        CALCULATED: required production days {days_s}, tight_deadline {str(tight).lower()}
        DETECTED ISSUES: {iss_str}

        Write a clear explanation (max 120 words) covering:
        1. Machine capacity problems  2. Material shortages
        3. Production constraints     4. Overall resource availability status
        Return JSON: {{"explanation": "...", "key_constraints": ["..."]}}
        """

        try:
            resp = self.llm_client.generate(prompt)
            # Find JSON block
            if "```json" in resp:
                resp = resp.split("```json")[1].split("```")[0]
            elif "```" in resp:
                resp = resp.split("```")[1].split("```")[0]
            
            parsed = json.loads(resp.strip())
            
            # Simple validation: ensure some numbers exist in the output text to verify LLM didn't hallucinate
            explanation = parsed.get("explanation", "")
            expected = [req_s, req_s.replace(",", ""), qty_s, qty_s.replace(",", ""),
                        str(int(mat_req)), str(order['quantity'])]
            if any(number in explanation for number in expected):
                return explanation or template_text, "llm"
            else:
                return template_text, "template"
        except Exception as e:
            logger.error(f"LLM explanation failed: {e}")
            return template_text, "template"

    def build_result(self, req: ResourceAnalyzeRequest, data: Dict[str, Any], calcs: Optional[ResourceCalculations] = None, issues: List[str] = None, explanation: str = "", explanation_source: str = "template", template_only: bool = False) -> ResourceAnalyzeResponse:
        
        if template_only:
            return ResourceAnalyzeResponse(
                order_id=req.order_id or "UNKNOWN",
                resource_status="INSUFFICIENT",
                issues=["MATERIAL_NOT_FOUND"],
                explanation="Material not found in database.",
                explanation_source="template",
                data_source="postgresql"
            )

        status = "INSUFFICIENT" if issues else "SUFFICIENT"
        
        return ResourceAnalyzeResponse(
            order_id=req.order_id or "UNKNOWN",
            resource_status=status,
            issues=issues,
            machine=data.get('machine').model_dump() if data.get('machine') else None,
            material=data.get('material').model_dump() if data.get('material') else None,
            supplier=data.get('supplier').model_dump() if data.get('supplier') else None,
            calculations=calcs,
            explanation=explanation,
            explanation_source=explanation_source,
            data_source="postgresql"
        )
