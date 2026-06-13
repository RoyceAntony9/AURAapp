"""
Pipeline Adapter: converts SimulationState (raw dicts used by LangGraph nodes)
into PipelineState (typed Pydantic models expected by addition.py's
run_forecast_and_report).
"""

import logging
from typing import Any, Dict, List, Tuple

from backend.app.agents.addition import (
    PipelineState,
    SimulationInput,
    SignalData,
    PersonaResult,
    SocialInfluenceCycle,
)
from backend.app.services.simulation_engine import (
    expand_archetypes_to_customers,
    run_population_simulation,
    compute_product_context,
    POPULATION_SIZE,
    FunnelResult,
    ProductContext,
)

logger = logging.getLogger("aura.pipeline_adapter")


def _build_sim_input(state: Dict[str, Any]) -> SimulationInput:
    """Map flat SimulationState fields → SimulationInput Pydantic model."""
    return SimulationInput(
        idea=state["idea"],
        industry=state["industry"],
        target_market=state["market"],
        price_amount=float(state["pricing_amount"]),
        price_currency=state.get("pricing_currency", "USD"),
        region=state.get("region", "Global"),
        timeline=state.get("timeline", "3-6mo"),
    )


def _build_signal_data(state: Dict[str, Any]) -> SignalData:
    """
    Map state["signals"][0] → SignalData.

    state["signals"] is a list of dicts; we use the first one.
    competitors are dicts with {name, why_relevant, positioning} —
    extract just the names for competitors_raw.
    """
    signals_list = state.get("signals", [])
    if not signals_list:
        logger.warning("pipeline_adapter: no signals in state, using empty SignalData")
        return SignalData(is_synthetic_fallback=True, sources_used=["synthetic"])

    sig = signals_list[0]
    source = sig.get("source", "synthetic")
    is_synthetic = "synthetic" in source.lower()

    # Extract competitor names from the structured competitor dicts
    raw_competitors = sig.get("competitors", [])
    competitors_raw: List[str] = []
    for c in raw_competitors:
        if isinstance(c, dict):
            name = c.get("name", "")
            if name:
                competitors_raw.append(name)
        elif isinstance(c, str):
            competitors_raw.append(c)

    # Determine sources_used
    sources_used = [s.strip() for s in source.split("/") if s.strip()]

    return SignalData(
        complaints=sig.get("complaints", []),
        demands=sig.get("demands", []),
        competitors_raw=competitors_raw,
        market_sentiment_score=float(sig.get("market_sentiment_score", 0.0)),
        market_sentiment_summary=sig.get("market_sentiment_summary", ""),
        sources_used=sources_used,
        is_synthetic_fallback=is_synthetic,
    )


def _build_personas(
    job_id: str,
    archetypes: List[Dict[str, Any]],
    product: ProductContext,
    adoption_curve: Dict[str, Any],
) -> List[PersonaResult]:
    """
    Recreate the 5000-customer population, apply cycle-5 social-influence
    adjustments, and map each FunnelResult → PersonaResult.
    """
    from backend.app.agents.pipeline import get_adjusted_population_results

    population_results, _agg = get_adjusted_population_results(
        job_id=job_id,
        archetypes=archetypes,
        product=product,
        adoption_curve=adoption_curve,
    )

    # Build archetype lookup for demographic info
    arch_map: Dict[str, Dict[str, Any]] = {a["id"]: a for a in archetypes}

    personas: List[PersonaResult] = []
    for r in population_results:
        arch = arch_map.get(r.archetype_id, {})

        # Map budget_sensitivity: archetype stores int 1-10, PersonaResult needs float 0-10
        budget_sens = float(arch.get("budget_sensitivity", 5))

        # Map risk_tolerance string → Literal
        risk_tol_raw = arch.get("risk_tolerance", "medium")
        if risk_tol_raw not in ("low", "medium", "high"):
            risk_tol_raw = "medium"

        personas.append(
            PersonaResult(
                persona_id=r.customer_id,
                segment=arch.get("segment", "General"),
                age=int(arch.get("age", 30)),
                income_bracket=arch.get("income_bracket", "$50k - $80k"),
                occupation=arch.get("occupation", "Professional"),
                would_buy=r.would_buy,
                excitement_score=round(r.likelihood * 10.0, 1),  # 0-1 → 0-10
                likelihood_score=round(r.likelihood, 3),  # stays 0-1
                objections=r.objections,
                reasoning=r.reasoning,
                budget_sensitivity=budget_sens,
                risk_tolerance=risk_tol_raw,
            )
        )

    logger.info(
        "pipeline_adapter: built %d PersonaResult objects from population",
        len(personas),
    )
    return personas


def _build_influence_cycles(
    adoption_curve: Dict[str, Any],
) -> List[SocialInfluenceCycle]:
    """
    Convert adoption_curve dict to list[SocialInfluenceCycle].

    adoption_curve format:
        {"cycle_0": {"Innovators": 0.72, "Early Adopters": 0.65, ...}, ...}
    """
    cycles: List[SocialInfluenceCycle] = []

    for cycle_idx in range(6):
        key = f"cycle_{cycle_idx}"
        segment_adoption = adoption_curve.get(key, {})
        if not segment_adoption:
            logger.warning(
                "pipeline_adapter: missing adoption data for %s, using defaults",
                key,
            )
            segment_adoption = {
                "Innovators": 0.5,
                "Early Adopters": 0.4,
                "Early Majority": 0.3,
                "Late Majority": 0.2,
                "Laggards": 0.1,
            }

        values = list(segment_adoption.values())
        overall = sum(values) / len(values) if values else 0.0

        cycles.append(
            SocialInfluenceCycle(
                cycle=cycle_idx,
                segment_adoption=segment_adoption,
                overall_adoption=round(overall, 4),
            )
        )

    return cycles


def build_pipeline_state(state: Dict[str, Any]) -> PipelineState:
    """
    Master conversion: SimulationState (raw dicts) → PipelineState (typed models).

    This is the single bridge function called from the forecast_report_node.
    """
    job_id = state["job_id"]
    archetypes = state["archetypes"]
    adoption_curve = state.get("adoption_curve", {})

    sim_input = _build_sim_input(state)
    signals = _build_signal_data(state)

    # Build product context for persona re-simulation
    product = compute_product_context(
        idea=state["idea"],
        industry=state["industry"],
        market=state["market"],
        pricing_amount=float(state["pricing_amount"]),
        signals=state.get("signals", []),
        timeline=state.get("timeline", "3-6mo"),
        region=state.get("region", "Global"),
    )

    personas = _build_personas(job_id, archetypes, product, adoption_curve)
    influence_cycles = _build_influence_cycles(adoption_curve)

    pipeline_state = PipelineState(
        job_id=job_id,
        sim_input=sim_input,
        signals=signals,
        personas=personas,
        influence_cycles=influence_cycles,
    )

    logger.info(
        "[%s] PipelineState built: %d personas, %d influence cycles, "
        "synthetic=%s, market=%s",
        job_id,
        len(personas),
        len(influence_cycles),
        signals.is_synthetic_fallback,
        sim_input.target_market,
    )

    return pipeline_state
