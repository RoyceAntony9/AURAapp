import uuid
import logging
from fastapi import FastAPI, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from backend.app.config import settings
from backend.app.database import get_db, init_db
from backend.app.models import Job, Report, PersonaArchetype, SimulationResult, Signal
from backend.app.schemas import (
    SimulateRequest, 
    SimulateResponse, 
    JobStatusResponse, 
    PaginatedPersonasResponse,
    PersonaResponse
)
from backend.app.redis_client import redis_client
from backend.app.agents.pipeline import run_simulation_pipeline
from backend.app.services.expansion import expand_archetypes_to_personas

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aura.main")

app = FastAPI(
    title="AURA (AI Unified Risk & Revenue Analysis) API",
    description="Backend API for synthetic market simulation",
    version="1.0.0"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For hackathon ease of development. Can restrict to specific frontend domains in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Application startup: Create database tables
@app.on_event("startup")
async def on_startup():
    logger.info("Initializing database tables...")
    try:
        await init_db()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}")

# API ENDPOINTS

@app.post("/simulate", response_model=SimulateResponse, status_code=status.HTTP_202_ACCEPTED)
async def simulate(request: SimulateRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    job_id = str(uuid.uuid4())
    logger.info(f"Received simulation request. Creating job_id: {job_id}")

    # Create Job record in Database
    new_job = Job(
        id=job_id,
        status="queued",
        progress=0,
        current_stage="Queued",
        idea=request.idea,
        industry=request.industry,
        market=request.market,
        pricing_amount=request.pricing.amount,
        pricing_currency=request.pricing.currency,
        region=request.region,
        timeline=request.timeline
    )
    db.add(new_job)
    await db.commit()

    # Cache status in Redis
    status_data = {
        "status": "queued",
        "progress": 0,
        "current_stage": "Queued",
        "error": None
    }
    redis_client.set_json(f"job:{job_id}:status", status_data)

    # Queue background task (FastAPI native)
    background_tasks.add_task(
        run_simulation_pipeline,
        job_id=job_id,
        idea=request.idea,
        industry=request.industry,
        market=request.market,
        pricing_amount=request.pricing.amount,
        pricing_currency=request.pricing.currency,
        region=request.region,
        timeline=request.timeline
    )

    return SimulateResponse(job_id=job_id, status="queued")


@app.get("/simulate/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    redis_key = f"job:{job_id}:status"
    cached = redis_client.get_json(redis_key)
    
    # Watchdog check: if job is not terminal, check DB to see if it exceeded 120s
    is_terminal = cached and cached.get("status") in ("complete", "failed")
    
    if not is_terminal:
        import datetime
        query = select(Job).where(Job.id == job_id)
        result = await db.execute(query)
        job = result.scalar_one_or_none()
        
        if job and job.status not in ("complete", "failed"):
            created = job.created_at
            now = datetime.datetime.utcnow()
            elapsed = (now - created).total_seconds()
            if elapsed > 120.0:
                logger.warning(f"[{job_id}] Watchdog: job has been running for {elapsed:.1f}s, marking as failed.")
                job.status = "failed"
                job.error = "pipeline timeout"
                await db.commit()
                
                # Update Redis
                status_data = {
                    "status": "failed",
                    "progress": 100,
                    "current_stage": job.current_stage,
                    "error": "pipeline timeout"
                }
                redis_client.set_json(redis_key, status_data)
                
                return JobStatusResponse(
                    status="failed",
                    progress=100,
                    current_stage=job.current_stage,
                    error="pipeline timeout"
                )
        elif not job and not cached:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Job not found"
            )
            
    if cached:
        return JobStatusResponse(
            status=cached["status"],
            progress=cached["progress"],
            current_stage=cached["current_stage"],
            error=cached.get("error")
        )

    # Database fallback
    query = select(Job).where(Job.id == job_id)
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Job not found"
        )

    return JobStatusResponse(
        status=job.status,
        progress=job.progress,
        current_stage=job.current_stage,
        error=job.error
    )


@app.get("/simulate/{job_id}/result")
async def get_job_result(job_id: str, db: AsyncSession = Depends(get_db)):
    # Query Job status
    query = select(Job).where(Job.id == job_id)
    result = await db.execute(query)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Job not found"
        )

    if job.status != "complete":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Simulation is not complete. Current status: {job.status}"
        )

    # Query Report
    report_query = select(Report).where(Report.job_id == job_id)
    report_res = await db.execute(report_query)
    report = report_res.scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Report not generated for this job"
        )

    # Return full report fields (legacy + new ForecastResult fields)
    # Load the report_data JSON fields which contain the new ForecastResult data
    return {
        "job_id": job_id,
        "idea": job.idea,
        "industry": job.industry,
        "market": job.market,
        "pricing_amount": job.pricing_amount,
        "pricing_currency": job.pricing_currency,
        "region": job.region,
        "timeline": job.timeline,
        # Legacy fields (backward compat)
        "executive_summary": report.executive_summary,
        "opportunity_score": report.opportunity_score,
        "opportunity_label": report.opportunity_label,
        "launch_recommendation": report.launch_recommendation,
        "launch_rationale": report.launch_rationale,
        "customer_quotes": report.customer_quotes,
        "revenue_projection": report.revenue_projection,
        "risk_analysis": report.risk_analysis,
        "adoption_curve": report.adoption_curve,
        "market_segments": report.market_segments,
        "pricing_recommendation": report.pricing_recommendation,
        "go_to_market_strategy": report.go_to_market_strategy,
        "confidence_score": report.confidence_score,
        "signal_intelligence": report.signal_intelligence,
        "buyer_journey": report.buyer_journey,
        "simulated_conversations": report.simulated_conversations,
        "competitors_battle": report.competitors_battle,
        "confidence_details": report.confidence_details,
        "objections_list": report.objections_list,
        # Market friction scores
        "launch_difficulty": report.launch_difficulty,
        "price_friction": report.price_friction,
        "social_friction": report.social_friction,
        "behavior_change_cost": report.behavior_change_cost,
        "trust_requirement": report.trust_requirement,
        "infrastructure_requirement": report.infrastructure_requirement,
        "switching_cost": report.switching_cost,
        "time_to_value": report.time_to_value,
        "novelty_penalty": report.novelty_penalty,
        "education_cost": report.education_cost,
        "product_market_fit": report.product_market_fit,
        "social_adoption": report.social_adoption,
        "price_acceptance": report.price_acceptance,
        "trust_barrier": report.trust_barrier,
        "habit_change_required": report.habit_change_required,
        "scenario_tests": report.scenario_tests,
        # NEW ForecastResult fields (extracted from stored JSON columns)
        "pmf_score": report.product_market_fit if report.product_market_fit else report.opportunity_score,
        "pmf_label": ("Strong Fit" if (report.product_market_fit or report.opportunity_score or 0) >= 70
                      else "Moderate Fit" if (report.product_market_fit or report.opportunity_score or 0) >= 40
                      else "Weak Fit"),
        "final_adoption_pct": report.social_adoption if report.social_adoption else float(report.opportunity_score or 0),
        "conversion_rate_pct": report.price_acceptance if report.price_acceptance else 0.0,
        # Structured data from JSON columns
        "funnel": report.buyer_journey.get("_funnel_array", []) if isinstance(report.buyer_journey, dict) else [],
        "diffusion_curve": report.adoption_curve.get("_diffusion_curve", []) if isinstance(report.adoption_curve, dict) else [],
        "competitors": (report.competitors_battle.get("competitors", [])
                       if isinstance(report.competitors_battle, dict) else []),
        "top_objections": [
            {"objection": o.get("issue", ""), "pct": o.get("frequency", 0), "count": o.get("count", 0)}
            for o in (report.objections_list or [])
        ],
        "confidence": report.confidence_details if report.confidence_details else {
            "signal_quality_pct": float(report.confidence_score or 70),
            "persona_consistency_pct": float(report.confidence_score or 70),
            "forecast_stability_pct": float(report.confidence_score or 70),
            "final_confidence_pct": float(report.confidence_score or 70),
            "explainer": "Confidence based on available data quality and model consistency.",
        },
        "market_reception": report.revenue_projection.get("_market_reception", {
            "overall_label": report.opportunity_label or "Mixed",
            "enthusiastic_pct": 25.0, "interested_pct": 35.0,
            "skeptical_pct": 25.0, "rejecting_pct": 15.0,
        }) if isinstance(report.revenue_projection, dict) else {},
        "launch_recommendation_obj": {
            "decision": report.launch_recommendation,
            "rationale": report.launch_rationale,
        },
    }


@app.get("/simulate/{job_id}/personas", response_model=PaginatedPersonasResponse)
async def get_job_personas(
    job_id: str,
    segment: Optional[str] = Query(None, description="Segment ID or name to filter personas"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db)
):
    # Fetch archetypes
    arch_query = select(PersonaArchetype).where(PersonaArchetype.job_id == job_id)
    arch_res = await db.execute(arch_query)
    archetypes = arch_res.scalars().all()
    
    if not archetypes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Personas not found or job not started"
        )

    # Fetch job context for funnel simulation
    job_query = select(Job).where(Job.id == job_id)
    job_res = await db.execute(job_query)
    job = job_res.scalar_one_or_none()

    sig_query = select(Signal).where(Signal.job_id == job_id)
    sig_res = await db.execute(sig_query)
    signals = sig_res.scalars().all()
    signals_list = [
        {
            "market_strength": s.market_strength,
            "competitive_density": s.competitive_density,
            "market_sentiment_score": s.market_sentiment_score,
            "confidence": s.confidence,
        }
        for s in signals
    ]

    sim_query = select(SimulationResult).where(SimulationResult.job_id == job_id)
    sim_res = await db.execute(sim_query)
    simulations = sim_res.scalars().all()

    expanded_personas = expand_archetypes_to_personas(
        job_id=job_id,
        archetypes=archetypes,
        simulations=simulations,
        segment_filter=segment,
        idea=job.idea if job else "",
        industry=job.industry if job else "SaaS",
        market=job.market if job else "",
        pricing_amount=job.pricing_amount if job else 10.0,
        region=job.region if job else "Global",
        timeline=job.timeline if job else "3-6mo",
        signals=signals_list,
    )

    total_count = len(expanded_personas)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    sliced_personas = expanded_personas[start_idx:end_idx]

    return PaginatedPersonasResponse(
        personas=[PersonaResponse(**p) for p in sliced_personas],
        total_count=total_count,
        page=page,
        limit=limit
    )

@app.get("/simulate/{job_id}/archetypes")
async def get_job_archetypes(job_id: str, db: AsyncSession = Depends(get_db)):
    # Fetch archetypes
    arch_query = select(PersonaArchetype).where(PersonaArchetype.job_id == job_id)
    arch_res = await db.execute(arch_query)
    archetypes = arch_res.scalars().all()
    
    if not archetypes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Archetypes not found or job not started"
        )

    # Fetch simulation results
    sim_query = select(SimulationResult).where(SimulationResult.job_id == job_id)
    sim_res = await db.execute(sim_query)
    simulations = sim_res.scalars().all()
    sim_map = {s.archetype_id: s for s in simulations}

    results = []
    for arch in archetypes:
        sim = sim_map.get(arch.id)
        results.append({
            "id": arch.id,
            "name": arch.name,
            "age": arch.age,
            "income_bracket": arch.income_bracket,
            "occupation": arch.occupation,
            "location": arch.location,
            "buying_behavior": arch.buying_behavior,
            "goals": arch.goals,
            "objections": arch.objections,
            "risk_tolerance": arch.risk_tolerance,
            "budget_sensitivity": arch.budget_sensitivity,
            "segment": arch.segment,
            "influence": arch.influence,
            "buying_trigger": arch.buying_trigger,
            "pain_point": arch.pain_point,
            "adoption_probability": arch.adoption_probability,
            "behavior_type": arch.behavior_type,
            "would_buy": sim.would_buy if sim else False,
            "excitement_score": sim.excitement_score if sim else 5,
            "likelihood_score": sim.likelihood_score if sim else 0.5,
            "reasoning": sim.reasoning if sim else "",
            # Enriched persona metrics (previously missing from response)
            "technology_comfort": arch.technology_comfort,
            "risk_appetite": arch.risk_appetite,
            "social_influence": arch.social_influence,
            "income": arch.income,
            "urgency": arch.urgency,
            "existing_alternatives": arch.existing_alternatives,
        })

    return results

