import random
from typing import List, Dict, Any, Optional

from backend.app.services.simulation_engine import (
    POPULATION_SIZE,
    compute_product_context,
    expand_archetypes_to_customers,
    run_population_simulation,
    _seed_from,
)


def _arch_to_dict(arch: Any) -> Dict[str, Any]:
    """Normalize SQLAlchemy model or dict archetype."""
    if isinstance(arch, dict):
        return arch
    return {
        "id": arch.id,
        "name": arch.name,
        "segment": arch.segment,
        "occupation": arch.occupation,
        "budget": max(1, 13 - arch.budget_sensitivity),
        "risk": arch.risk_appetite / 100.0,
        "social_influence": arch.social_influence / 100.0 if arch.social_influence > 1 else arch.social_influence,
        "tech_comfort": arch.technology_comfort / 100.0,
        "price_elasticity": arch.budget_sensitivity / 10.0,
        "switching_cost": arch.existing_alternatives / 100.0,
        "population_weight": 1.0,
        "objections": arch.objections or [],
        "age": arch.age,
        "income_bracket": arch.income_bracket,
        "location": arch.location,
        "buying_behavior": arch.buying_behavior,
        "goals": arch.goals,
        "risk_tolerance": arch.risk_tolerance,
        "budget_sensitivity": arch.budget_sensitivity,
        "influence": arch.influence,
        "buying_trigger": getattr(arch, "buying_trigger", ""),
        "pain_point": getattr(arch, "pain_point", ""),
        "adoption_probability": getattr(arch, "adoption_probability", 0.5),
        "behavior_type": getattr(arch, "behavior_type", "General"),
        "technology_comfort": arch.technology_comfort,
        "risk_appetite": arch.risk_appetite,
        "income": getattr(arch, "income", 50000),
        "urgency": getattr(arch, "urgency", 50),
        "existing_alternatives": getattr(arch, "existing_alternatives", 50),
    }


def expand_archetypes_to_personas(
    job_id: str,
    archetypes: List[Any],
    simulations: List[Any],
    segment_filter: str = None,
    total_target: int = POPULATION_SIZE,
    idea: str = "",
    industry: str = "SaaS",
    market: str = "",
    pricing_amount: float = 10.0,
    region: str = "Global",
    timeline: str = "3-6mo",
    signals: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Expand archetypes to population and run per-customer funnel simulation."""
    arch_dicts = [_arch_to_dict(a) for a in archetypes]
    if not arch_dicts:
        return []

    product = compute_product_context(
        idea=idea, industry=industry, market=market,
        pricing_amount=pricing_amount, signals=signals or [],
        timeline=timeline, region=region,
    )
    customers = expand_archetypes_to_customers(job_id, arch_dicts, total_target)
    population_results, _ = run_population_simulation(job_id, customers, product)

    result_map = {r.customer_id: r for r in population_results}
    expanded: List[Dict[str, Any]] = []

    for cust in customers:
        funnel = result_map.get(cust.id)
        if not funnel:
            continue

        if segment_filter:
            slug = cust.segment.lower().replace(" ", "_")
            if slug != segment_filter.lower().replace(" ", "_"):
                continue

        expanded.append({
            "id": cust.id,
            "name": cust.name,
            "age": next((a["age"] for a in arch_dicts if a["id"] == cust.archetype_id), 30),
            "income_bracket": next((a["income_bracket"] for a in arch_dicts if a["id"] == cust.archetype_id), "$50k - $80k"),
            "occupation": cust.occupation,
            "location": next((a["location"] for a in arch_dicts if a["id"] == cust.archetype_id), "Global"),
            "buying_behavior": next((a["buying_behavior"] for a in arch_dicts if a["id"] == cust.archetype_id), ""),
            "goals": next((a["goals"] for a in arch_dicts if a["id"] == cust.archetype_id), []),
            "objections": funnel.objections,
            "risk_tolerance": next((a["risk_tolerance"] for a in arch_dicts if a["id"] == cust.archetype_id), "medium"),
            "budget_sensitivity": max(1, min(10, int(13 - cust.budget))),
            "segment": cust.segment,
            "influence": cust.social_influence,
            "would_buy": funnel.would_buy,
            "likelihood_score": funnel.likelihood,
            "reasoning": funnel.reasoning,
            "buying_trigger": next((a.get("buying_trigger", "") for a in arch_dicts if a["id"] == cust.archetype_id), ""),
            "pain_point": next((a.get("pain_point", "") for a in arch_dicts if a["id"] == cust.archetype_id), ""),
            "adoption_probability": funnel.likelihood,
            "behavior_type": next((a.get("behavior_type", "") for a in arch_dicts if a["id"] == cust.archetype_id), ""),
            "technology_comfort": round(cust.tech_comfort * 100, 1),
            "risk_appetite": round(cust.risk * 100, 1),
            "social_influence": round(cust.social_influence * 100, 1),
            "income": next((a.get("income", 50000) for a in arch_dicts if a["id"] == cust.archetype_id), 50000),
            "urgency": next((a.get("urgency", 50) for a in arch_dicts if a["id"] == cust.archetype_id), 50),
            "existing_alternatives": round(cust.switching_cost * 100, 1),
        })

    return expanded
