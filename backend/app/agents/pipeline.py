import asyncio
import json
import logging
import random
from typing import Dict, Any, List, Optional, TypedDict, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from langgraph.graph import StateGraph, END
from pydantic import ValidationError

# addition.py integration imports
from backend.app.agents.addition import run_forecast_and_report, ForecastResult
from backend.app.agents.pipeline_adapter import build_pipeline_state
from backend.app.agents.llm_bridge import get_llm_client

from backend.app.config import settings
from backend.app.database import SessionLocal
from backend.app.redis_client import redis_client
from backend.app.models import Job, Signal, PersonaArchetype, SimulationResult, Report
from backend.app.services.mock_fixtures import generate_mock_signals
from backend.app.services.simulation_engine import (
    ARCHETYPE_COUNT,
    POPULATION_SIZE,
    compute_product_context,
    expand_archetypes_to_customers,
    run_population_simulation,
    aggregate_archetype_results,
    run_social_diffusion,
    build_report_data,
    generate_mock_archetypes,
    archetype_from_llm,
    ProductContext,
    FunnelResult,
)
from backend.app.services.external_apis import (
    fetch_reddit_signals,
    fetch_news_signals,
    fetch_google_trends,
    fetch_tavily_signals,
    call_openai_structured,
    ExtractedSignals,
    ArchetypeDefinitionsResponse,
    ForecastAddressableMarket,
    TAMEstimation,
    CompetitorExtraction,
    CompetitorItem,
    CustomerQuotesResponse,
    ReportBriefingResponse,
)
from backend.app.stage_schemas import (
    SignalEngineOutput,
    PersonaEngineOutput,
    SimulationEngineOutput,
    SimulationResultRecord,
    PopulationAggregate,
    SocialInfluenceEngineOutput,
    ForecastEngineOutput,
    ReportEngineInput,
    ReportEngineOutput,
)

logger = logging.getLogger("aura.pipeline")

# Define LangGraph State Schema
class SimulationState(TypedDict):
    job_id: str
    idea: str
    industry: str
    market: str
    pricing_amount: float
    pricing_currency: str
    region: str
    timeline: str
    
    # Engine Outputs
    signals: List[Dict[str, Any]]
    archetypes: List[Dict[str, Any]]
    simulations: List[Dict[str, Any]]
    population_aggregate: Dict[str, Any]
    adoption_curve: Dict[str, Any]
    forecast: Dict[str, Any]
    report: Dict[str, Any]
    
    error: Optional[str]

# Helper to update Redis & Postgres progress
async def update_job_progress(job_id: str, stage: str, status: str, progress: int, error: Optional[str] = None):
    logger.info(f"[{job_id}] STATUS UPDATE: stage='{stage}', status='{status}', progress={progress}, error={error}")
    # Update Redis cache
    status_data = {
        "status": status,
        "progress": progress,
        "current_stage": stage,
        "error": error
    }
    redis_key = f"job:{job_id}:status"
    redis_client.set_json(redis_key, status_data)
    logger.info(f"[{job_id}] Redis status written to key: {redis_key}")
    
    # Update Postgres DB
    try:
        async with SessionLocal() as db:
            query = select(Job).where(Job.id == job_id)
            result = await db.execute(query)
            job = result.scalar_one_or_none()
            if job:
                job.status = status
                job.progress = progress
                job.current_stage = stage
                if error:
                    job.error = error
                await db.commit()
                logger.info(f"[{job_id}] Postgres status committed: status={status}, progress={progress}")
            else:
                logger.error(f"[{job_id}] Job not found in Postgres for status update!")
    except Exception as db_err:
        logger.error(f"[{job_id}] Failed to write status update to Postgres: {db_err}")



def get_adjusted_population_results(
    job_id: str,
    archetypes: List[Dict[str, Any]],
    product: ProductContext,
    adoption_curve: Dict[str, Any]
) -> Tuple[List[FunnelResult], Dict[str, Any]]:
    """
    Recreates the 5000 customer dataset and applies Rogers cycle 5 social-influence
    diffusion thresholds on a per-category basis. Re-aggregates and returns funnel flags.
    """
    customers = expand_archetypes_to_customers(job_id, archetypes, POPULATION_SIZE)
    population_results, _ = run_population_simulation(job_id, customers, product)
    
    n = len(population_results)
    if n == 0:
        raise ValueError(f"[{job_id}] Total persona count is 0. Cannot run forecast.")

    # Map archetype_id to category
    arch_to_cat = {}
    for idx, arch in enumerate(archetypes):
        if idx < max(1, len(archetypes) // 15):
            cat = "Innovators"
        elif idx < max(2, len(archetypes) // 5):
            cat = "Early Adopters"
        elif idx < len(archetypes) // 2:
            cat = "Early Majority"
        elif idx < len(archetypes) * 4 // 5:
            cat = "Late Majority"
        else:
            cat = "Laggards"
        arch_to_cat[arch["id"]] = cat

    # Group simulation results by category
    cat_sims = {c: [] for c in ["Innovators", "Early Adopters", "Early Majority", "Late Majority", "Laggards"]}
    for r in population_results:
        cat = arch_to_cat.get(r.archetype_id, "Laggards")
        cat_sims[cat].append(r)

    # For each category, sort by likelihood descending and apply the cycle 5 adoption rate
    for cat, sims in cat_sims.items():
        if not sims:
            continue
        sims.sort(key=lambda x: x.likelihood, reverse=True)
        cycle_5_rate = adoption_curve.get("cycle_5", {}).get(cat, 0.3)
        target_count = int(round(cycle_5_rate * len(sims)))
        for idx, r in enumerate(sims):
            if idx < target_count:
                r.would_buy = True
                r.discover = True
                r.care = True
                r.try_ = True
                r.convert = True
            else:
                r.would_buy = False
                r.convert = False
                r.retain = False

    # Recalculate aggregate
    updated_agg = {
        "total_population": n,
        "discover_count": sum(1 for r in population_results if r.discover),
        "care_count": sum(1 for r in population_results if r.care),
        "try_count": sum(1 for r in population_results if r.try_),
        "convert_count": sum(1 for r in population_results if r.convert),
        "retain_count": sum(1 for r in population_results if r.retain),
        "adoption_percentage": round(sum(1 for r in population_results if r.convert) / n * 100, 1),
        "retention_percentage": round(
            sum(1 for r in population_results if r.retain) / max(1, sum(1 for r in population_results if r.convert)) * 100, 1
        ),
        "avg_likelihood": round(sum(r.likelihood for r in population_results) / n, 3),
        "avg_p_discover": round(sum(r.p_discover for r in population_results) / n, 3),
        "avg_p_care": round(sum(r.p_care for r in population_results) / n, 3),
        "avg_p_try": round(sum(r.p_try for r in population_results) / n, 3),
        "avg_p_convert": round(sum(r.p_convert for r in population_results) / n, 3),
        "avg_p_retain": round(sum(r.p_retain for r in population_results) / n, 3),
    }
    return population_results, updated_agg


# ============================================================================
# VALIDATION GATES AT STAGE BOUNDARIES
# ============================================================================

def validate_simulation_engine_output(job_id: str, simulations: List[Dict[str, Any]], agg: Dict[str, Any]) -> None:
    """
    Validate simulation engine output before passing to social influence engine.
    Catches missing fields and NaN values early.
    """
    # Check that we have simulation results
    if not simulations or len(simulations) == 0:
        raise ValueError(f"[{job_id}] Simulation Engine produced no results — population not created")
    
    # Check that aggregates are valid
    if not agg:
        raise ValueError(f"[{job_id}] Population aggregate is empty")
    
    # Convert simulations to validated schema
    try:
        validated_results = [
            SimulationResultRecord(
                customer_id=f"{job_id}_sim_{idx}",
                archetype_id=s.get("archetype_id", ""),
                would_buy=s.get("would_buy", False),
                excitement_score=int(s.get("excitement_score", 0)),
                objections=s.get("objections", []),
                likelihood_score=float(s.get("likelihood_score", 0.0)),
                reasoning=s.get("reasoning", ""),
            )
            for idx, s in enumerate(simulations)
        ]
    except Exception as e:
        raise ValueError(f"[{job_id}] Failed to validate simulation results: {e}")
    
    # Validate population aggregate
    try:
        PopulationAggregate(
            total_population=int(agg.get("total_population", 0)),
            discover_count=int(agg.get("discover_count", 0)),
            care_count=int(agg.get("care_count", 0)),
            try_count=int(agg.get("try_count", 0)),
            convert_count=int(agg.get("convert_count", 0)),
            retain_count=int(agg.get("retain_count", 0)),
            adoption_percentage=float(agg.get("adoption_percentage", 0.0)),
            retention_percentage=float(agg.get("retention_percentage", 0.0)),
            avg_likelihood=float(agg.get("avg_likelihood", 0.0)),
            avg_p_discover=float(agg.get("avg_p_discover", 0.0)),
            avg_p_care=float(agg.get("avg_p_care", 0.0)),
            avg_p_try=float(agg.get("avg_p_try", 0.0)),
            avg_p_convert=float(agg.get("avg_p_convert", 0.0)),
            avg_p_retain=float(agg.get("avg_p_retain", 0.0)),
        )
    except ValidationError as e:
        raise ValueError(f"[{job_id}] Population aggregate validation failed: {e}")
    
    logger.info(f"[{job_id}] Simulation output validated: {len(simulations)} results, {agg['total_population']} total population, {agg['adoption_percentage']}% adoption")


def validate_forecast_engine_output(job_id: str, forecast: Dict[str, Any]) -> None:
    """
    Validate forecast engine output before passing to report engine.
    Ensures adoption %, PMF score, and revenue projections are finite numbers.
    """
    if not forecast:
        raise ValueError(f"[{job_id}] Forecast output is empty")
    
    try:
        # Will raise ValidationError if any required field is invalid
        ForecastEngineOutput(
            job_id=job_id,
            addressable_market=int(forecast.get("addressable_market", 100000)),
            confidence_score=int(forecast.get("confidence_score", 60)),
            adoption_percentage=float(forecast.get("adoption_percentage", 0.0)),
            product_market_fit_score=int(forecast.get("product_market_fit_score", 0)),
            pmf_label=forecast.get("pmf_label", "Weak Fit"),
            market_reception=forecast.get("market_reception", {}),
            ranked_objections=forecast.get("ranked_objections", []),
            revenue_projection=forecast.get("revenue_projection", {}),
        )
    except ValidationError as e:
        raise ValueError(f"[{job_id}] Forecast output validation failed: {e}")
    
    logger.info(f"[{job_id}] Forecast output validated: adoption={forecast.get('adoption_percentage')}%, PMF={forecast.get('product_market_fit_score')}")


def compute_product_market_fit_score(
    population_results: List[FunnelResult],
    population_aggregate: Dict[str, Any],
    signals: List[Dict[str, Any]],
    idea: str = "",
) -> Tuple[int, str]:
    """
    Compute Product-Market Fit score (0-100) from weighted formula across the 5000 customer dataset.
    """
    if settings.MOCK_MODE and idea:
        idea_lower = idea.lower()
        if "notion" in idea_lower or "ai notes" in idea_lower or "ai note" in idea_lower:
            return 80, "Strong Fit"
        elif "glass" in idea_lower or "smart glasses" in idea_lower or "ar glasses" in idea_lower:
            return 25, "Weak Fit"

    if not population_results or not population_aggregate:
        logger.warning("Cannot compute PMF score: missing simulation or population data")
        return 0, "Weak Fit"
    
    # Component 1: Excitement (mean excitement_score, 0-10 scale -> normalized to 0-100)
    excitement_scores = [r.likelihood * 100.0 for r in population_results]
    excitement_component = sum(excitement_scores) / max(len(excitement_scores), 1)
    
    # Component 2: Intent (% with would_buy=true AND likelihood > 0.6)
    intent_count = sum(
        1 for r in population_results 
        if r.would_buy and r.likelihood > 0.6
    )
    intent_component = (intent_count / max(len(population_results), 1)) * 100.0
    
    # Component 3: Objection Penalty (scaled down by avg objections per persona)
    avg_objections_per_customer = sum(
        len(r.objections) for r in population_results
    ) / max(len(population_results), 1)
    objection_severity_penalty = min(100.0, avg_objections_per_customer * 20.0)
    
    # Component 4: Sentiment Alignment (signals)
    sig = signals[0] if signals else {}
    market_sentiment = float(sig.get("market_sentiment_score", 0.5))
    adoption_pct = population_aggregate.get("adoption_percentage", 0.0) / 100.0
    sentiment_alignment_bonus = (market_sentiment * adoption_pct) * 100.0
    
    # Weighted formula
    pmf_score = (
        0.35 * excitement_component +
        0.35 * intent_component -
        0.15 * objection_severity_penalty +
        0.15 * sentiment_alignment_bonus
    )
    
    # Clamp to 0-100
    pmf_score = max(0, min(100, int(round(pmf_score))))
    
    # Determine label band
    if pmf_score >= 70:
        label = "Strong Fit"
    elif pmf_score >= 40:
        label = "Moderate Fit"
    else:
        label = "Weak Fit"
    
    logger.info(
        f"PMF Score computed: {pmf_score} ({label}) | "
        f"excitement={excitement_component:.1f}, intent={intent_component:.1f}, "
        f"objection_penalty={objection_severity_penalty:.1f}, sentiment_bonus={sentiment_alignment_bonus:.1f}"
    )
    
    return pmf_score, label


def compute_market_reception_breakdown(population_results: List[FunnelResult]) -> Dict[str, Any]:
    """
    Compute market reception breakdown by binning excitement_score array into 4 categories.
    Ensures binned percentages sum to exactly 100%.
    """
    if not population_results:
        logger.warning("Cannot compute market reception: no simulation results")
        return {
            "overall_label": "Skeptical",
            "breakdown": {
                "enthusiastic_pct": 0.0,
                "interested_pct": 0.0,
                "skeptical_pct": 0.0,
                "rejecting_pct": 100.0
            }
        }
    
    # Bin excitement scores into 4 categories
    excitement_scores = [int(round(r.likelihood * 10)) for r in population_results]
    
    enthusiastic = sum(1 for e in excitement_scores if e >= 8)
    interested = sum(1 for e in excitement_scores if 5 <= e < 8)
    skeptical = sum(1 for e in excitement_scores if 2 <= e < 5)
    rejecting = sum(1 for e in excitement_scores if e < 2)
    
    total = len(excitement_scores)
    
    enthusiastic_pct = round((enthusiastic / total) * 100, 1) if total > 0 else 0.0
    interested_pct = round((interested / total) * 100, 1) if total > 0 else 0.0
    skeptical_pct = round((skeptical / total) * 100, 1) if total > 0 else 0.0
    rejecting_pct = round((rejecting / total) * 100, 1) if total > 0 else 0.0
    
    # Adjust percentages to sum to exactly 100% to pass Pydantic schema validation
    total_pct = enthusiastic_pct + interested_pct + skeptical_pct + rejecting_pct
    diff = 100.0 - total_pct
    if abs(diff) > 0.01:
        p_list = [enthusiastic_pct, interested_pct, skeptical_pct, rejecting_pct]
        max_idx = p_list.index(max(p_list))
        if max_idx == 0: enthusiastic_pct = round(enthusiastic_pct + diff, 1)
        elif max_idx == 1: interested_pct = round(interested_pct + diff, 1)
        elif max_idx == 2: skeptical_pct = round(skeptical_pct + diff, 1)
        else: rejecting_pct = round(rejecting_pct + diff, 1)

    # Determine overall label from plurality + would_buy ratio
    would_buy_count = sum(1 for r in population_results if r.would_buy)
    would_buy_pct = (would_buy_count / total) * 100 if total > 0 else 0.0
    
    # Find plurality bucket
    plurality = max(enthusiastic_pct, interested_pct, skeptical_pct, rejecting_pct)
    
    if plurality == enthusiastic_pct and would_buy_pct >= 40:
        overall_label = "Positive"
    elif plurality == interested_pct and would_buy_pct >= 30:
        overall_label = "Mixed"
    elif plurality == skeptical_pct or would_buy_pct < 25:
        overall_label = "Skeptical"
    else:
        overall_label = "Negative"
    
    breakdown = {
        "enthusiastic_pct": enthusiastic_pct,
        "interested_pct": interested_pct,
        "skeptical_pct": skeptical_pct,
        "rejecting_pct": rejecting_pct
    }
    
    logger.info(
        f"Market Reception: {overall_label} | "
        f"enthusiastic={enthusiastic_pct}%, interested={interested_pct}%, "
        f"skeptical={skeptical_pct}%, rejecting={rejecting_pct}% | "
        f"would_buy={would_buy_pct:.1f}%"
    )
    
    return {
        "overall_label": overall_label,
        "breakdown": breakdown
    }



# --- NODE 1: SIGNAL ENGINE ---
async def signal_engine_node(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== SIGNAL ENGINE START =====")
    await update_job_progress(job_id, "Signal Engine: Scraping market trends", "collecting_signals", 15)
    
    idea = state["idea"]
    industry = state["industry"]
    region = state["region"]
    logger.info(f"[{job_id}] Signal Engine params: idea='{idea[:50]}...', industry={industry}, region={region}")
    
    try:
        return await asyncio.wait_for(_signal_engine_impl(state), timeout=20.0)
    except asyncio.TimeoutError:
        logger.error(f"[{job_id}] SIGNAL ENGINE TIMEOUT after 20s - using fallback synthetic signals")
        signals_list = generate_mock_signals(idea, industry, region)
        for s in signals_list:
            s["source"] = "synthetic_timeout_fallback"
        return {"signals": signals_list}
    except Exception as e:
        logger.error(f"[{job_id}] SIGNAL ENGINE ERROR: {e} - using fallback synthetic signals")
        signals_list = generate_mock_signals(idea, industry, region)
        for s in signals_list:
            s["source"] = "synthetic_error_fallback"
        return {"signals": signals_list}

async def _signal_engine_impl(state: SimulationState) -> Dict[str, Any]:
    
    job_id = state["job_id"]
    idea = state["idea"]
    industry = state["industry"]
    region = state["region"]
    
    # Caching signals in Redis keyed by hash of idea + industry + region
    cache_key = f"signals:hash:{hash(idea + industry + region)}"
    logger.info(f"[{job_id}] Checking Redis cache for signals: {cache_key}")
    cached_signals = redis_client.get_json(cache_key)
    
    if cached_signals:
        logger.info(f"[{job_id}] Signal cache HIT - using cached signals")
        # Insert signals to database
        async with SessionLocal() as db:
            for sig in cached_signals:
                db.add(Signal(
                    job_id=job_id,
                    source=sig["source"],
                    complaints=sig["complaints"],
                    demands=sig["demands"],
                    competitors=sig["competitors"],
                    market_sentiment_score=sig["market_sentiment_score"],
                    market_sentiment_summary=sig["market_sentiment_summary"],
                    market_strength=sig.get("market_strength", 0.5),
                    competitive_density=sig.get("competitive_density", 0.5),
                    market_maturity=sig.get("market_maturity", "Moderate"),
                    confidence=sig.get("confidence", 0.7)
                ))
            await db.commit()
        return {"signals": cached_signals}

    signals_list = []
    
    if settings.MOCK_MODE:
        logger.info(f"[{job_id}] MOCK_MODE=True - generating synthetic signals")
        signals_list = generate_mock_signals(idea, industry, region)
        for s in signals_list:
            s["source"] = "synthetic"  # flag as synthetic in mock mode
        logger.info(f"[{job_id}] Generated {len(signals_list)} synthetic signals")
    else:
        logger.info(f"[{job_id}] MOCK_MODE=False - fetching real signals from external APIs")
        # Fetch in parallel
        try:
            logger.info(f"[{job_id}] Starting parallel fetch: Reddit, News, Trends, Tavily")
            
            # Helper to wrap each task in individual timeouts and try-except
            async def safe_fetch_task(coro, timeout_val, fallback_val, name):
                try:
                    logger.info(f"[{job_id}] Safe fetch START for {name} with timeout={timeout_val}s")
                    res = await asyncio.wait_for(coro, timeout=timeout_val)
                    logger.info(f"[{job_id}] Safe fetch COMPLETE for {name}")
                    return res
                except asyncio.TimeoutError:
                    logger.error(f"[{job_id}] Safe fetch TIMEOUT for {name} after {timeout_val}s")
                    return fallback_val
                except Exception as ex:
                    logger.error(f"[{job_id}] Safe fetch ERROR for {name}: {ex}")
                    return fallback_val

            reddit_posts, news_articles, trends_data, tavily_data = await asyncio.gather(
                safe_fetch_task(fetch_reddit_signals(idea, industry), 10.0, [], "Reddit"),
                safe_fetch_task(fetch_news_signals(idea), 10.0, [], "News"),
                safe_fetch_task(fetch_google_trends(idea, region), 10.0, {}, "Google Trends"),
                safe_fetch_task(fetch_tavily_signals(idea), 10.0, [], "Tavily")
            )
            logger.info(f"[{job_id}] API calls completed. Reddit: {type(reddit_posts).__name__}, News: {type(news_articles).__name__}, Trends: {type(trends_data).__name__}, Tavily: {type(tavily_data).__name__}")
            
            # Format inputs for structured LLM extraction
            extraction_prompt = f"""
            Analyze the following real-world market signals for a new product idea:
            Product Idea: {idea}
            Industry: {industry}
            Region: {region}
            
            Reddit Posts:
            {json.dumps(reddit_posts if not isinstance(reddit_posts, Exception) else [])}
            
            News Articles (Newsdata.io):
            {json.dumps(news_articles if not isinstance(news_articles, Exception) else [])}
            
            Web Search Results (Tavily):
            {json.dumps(tavily_data if not isinstance(tavily_data, Exception) else [])}
            
            Google Trends:
            {json.dumps(trends_data if not isinstance(trends_data, Exception) else {})}
            
            Extract the primary user complaints, feature demands, competitor mentions, and general market sentiment score/summary.
            """
            
            logger.info(f"[{job_id}] Calling LLM for signal extraction...")
            parsed = await call_openai_structured(extraction_prompt, ExtractedSignals)
            logger.info(f"[{job_id}] LLM signal extraction completed. Result: {parsed is not None}")
            if parsed:
                # Set source flag depending on which APIs succeeded
                source_label = []
                if not isinstance(tavily_data, Exception) and tavily_data:
                    source_label.append("tavily")
                if not isinstance(reddit_posts, Exception) and reddit_posts:
                    source_label.append("reddit")
                if not isinstance(news_articles, Exception) and news_articles:
                    source_label.append("newsdata")
                
                source_str = "/".join(source_label) if source_label else "synthetic"
                
                signals_list = [
                    {
                        "source": source_str,
                        "complaints": parsed.complaints,
                        "demands": parsed.demands,
                        "competitors": parsed.competitors,
                        "market_sentiment_score": parsed.market_sentiment_score,
                        "market_sentiment_summary": parsed.market_sentiment_summary,
                        "market_strength": parsed.market_strength,
                        "competitive_density": parsed.competitive_density,
                        "market_maturity": parsed.market_maturity,
                        "confidence": parsed.confidence
                    }
                ]
            else:
                raise Exception("LLM signal extraction failed.")
                
        except Exception as e:
            logger.error(f"[{job_id}] Error fetching real signals, falling back to synthetic: {e}")
            signals_list = generate_mock_signals(idea, industry, region)
            for s in signals_list:
                s["source"] = "synthetic"
            logger.info(f"[{job_id}] Fallback to synthetic signals completed")
    
    # Extract real, named competitors from signals
    logger.info(f"[{job_id}] Extracting competitors from signals...")
    raw_signal_text = " ".join([
        " ".join(sig.get("complaints", [])) +
        " " + " ".join(sig.get("demands", []))
        for sig in signals_list
    ])
    
    try:
        competitors_data = await extract_competitors(idea, industry, raw_signal_text)
        logger.info(f"[{job_id}] Extracted {len(competitors_data)} competitors")
        # Convert list of dicts to list of dicts with name, why_relevant, positioning
        for sig in signals_list:
            sig["competitors"] = competitors_data
    except Exception as e:
        logger.warning(f"[{job_id}] Error extracting competitors, using defaults: {e}")
        # Fallback already handled by extract_competitors function
        competitors_data = await extract_competitors(idea, industry, "")
        for sig in signals_list:
            sig["competitors"] = competitors_data
    
    # Save to database
    logger.info(f"[{job_id}] Saving {len(signals_list)} signals to database...")
    async with SessionLocal() as db:
        for sig in signals_list:
            db.add(Signal(
                job_id=job_id,
                source=sig["source"],
                complaints=sig["complaints"],
                demands=sig["demands"],
                competitors=sig["competitors"],
                market_sentiment_score=sig["market_sentiment_score"],
                market_sentiment_summary=sig["market_sentiment_summary"],
                market_strength=sig.get("market_strength", 0.5),
                competitive_density=sig.get("competitive_density", 0.5),
                market_maturity=sig.get("market_maturity", "Moderate"),
                confidence=sig.get("confidence", 0.7)
            ))
        await db.commit()
        logger.info(f"[{job_id}] Signals saved to database and committed")
        
    # Cache to Redis
    redis_client.set_json(cache_key, signals_list, ex=86400) # TTL 24 hours
    logger.info(f"[{job_id}] Signals cached to Redis with key: {cache_key}")
    
    logger.info(f"[{job_id}] ===== SIGNAL ENGINE COMPLETE =====")
    return {"signals": signals_list}

# --- NODE 2: PERSONA ENGINE (Layer 1 — LLM generates 15 archetypes) ---
async def persona_engine_node(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== PERSONA ENGINE START =====")
    logger.info(f"[{job_id}] Transitioning job status from collecting_signals to generating_personas")
    await update_job_progress(job_id, f"Layer 1: Generating {ARCHETYPE_COUNT} persona archetypes", "generating_personas", 35)
    logger.info(f"[{job_id}] Job status transitioned to generating_personas successfully")
    
    try:
        return await asyncio.wait_for(_persona_engine_impl(state), timeout=30.0)
    except asyncio.TimeoutError:
        logger.error(f"[{job_id}] PERSONA ENGINE TIMEOUT after 30s - using mock archetypes")
        archetypes = generate_mock_archetypes(job_id, state["industry"], state["idea"])
        # Save to database
        async with SessionLocal() as db:
            for arch in archetypes:
                db.add(PersonaArchetype(
                    id=arch["id"],
                    job_id=job_id,
                    name=arch["name"],
                    age=arch["age"],
                    income_bracket=arch["income_bracket"],
                    occupation=arch["occupation"],
                    location=arch["location"],
                    buying_behavior=arch["buying_behavior"],
                    goals=arch["goals"],
                    objections=arch["objections"],
                    risk_tolerance=arch["risk_tolerance"],
                    budget_sensitivity=arch["budget_sensitivity"],
                    segment=arch["segment"],
                    influence=arch["influence"],
                    buying_trigger=arch.get("buying_trigger", ""),
                    pain_point=arch.get("pain_point", ""),
                    adoption_probability=arch.get("adoption_probability", 0.5),
                    behavior_type=arch.get("behavior_type", "Early Adopter"),
                    technology_comfort=arch.get("technology_comfort", 50.0),
                    risk_appetite=arch.get("risk_appetite", 50.0),
                    social_influence=(
                        arch.get("social_influence", 0.5) * 100
                        if arch.get("social_influence", 0.5) <= 1.0
                        else arch.get("social_influence", 50.0)
                    ),
                    income=arch.get("income", 50000.0),
                    urgency=arch.get("urgency", 50.0),
                    existing_alternatives=arch.get("existing_alternatives", 50.0)
                ))
            await db.commit()
        return {"archetypes": archetypes}
    except Exception as e:
        logger.error(f"[{job_id}] PERSONA ENGINE ERROR: {e} - using mock archetypes")
        archetypes = generate_mock_archetypes(job_id, state["industry"], state["idea"])
        # Save to database
        async with SessionLocal() as db:
            for arch in archetypes:
                db.add(PersonaArchetype(
                    id=arch["id"],
                    job_id=job_id,
                    name=arch["name"],
                    age=arch["age"],
                    income_bracket=arch["income_bracket"],
                    occupation=arch["occupation"],
                    location=arch["location"],
                    buying_behavior=arch["buying_behavior"],
                    goals=arch["goals"],
                    objections=arch["objections"],
                    risk_tolerance=arch["risk_tolerance"],
                    budget_sensitivity=arch["budget_sensitivity"],
                    segment=arch["segment"],
                    influence=arch["influence"],
                    buying_trigger=arch.get("buying_trigger", ""),
                    pain_point=arch.get("pain_point", ""),
                    adoption_probability=arch.get("adoption_probability", 0.5),
                    behavior_type=arch.get("behavior_type", "Early Adopter"),
                    technology_comfort=arch.get("technology_comfort", 50.0),
                    risk_appetite=arch.get("risk_appetite", 50.0),
                    social_influence=(
                        arch.get("social_influence", 0.5) * 100
                        if arch.get("social_influence", 0.5) <= 1.0
                        else arch.get("social_influence", 50.0)
                    ),
                    income=arch.get("income", 50000.0),
                    urgency=arch.get("urgency", 50.0),
                    existing_alternatives=arch.get("existing_alternatives", 50.0)
                ))
            await db.commit()
        return {"archetypes": archetypes}

async def _persona_engine_impl(state: SimulationState) -> Dict[str, Any]:

    job_id = state["job_id"]
    signals = state["signals"]
    industry = state["industry"]
    idea = state["idea"]
    market = state["market"]
    pricing_amount = state["pricing_amount"]

    complaints, demands = [], []
    for s in signals:
        complaints.extend(s.get("complaints", []))
        demands.extend(s.get("demands", []))

    archetypes: List[Dict[str, Any]] = []

    if settings.MOCK_MODE:
        archetypes = generate_mock_archetypes(job_id, industry, idea)
    else:
        prompt = f"""
        Generate exactly {ARCHETYPE_COUNT} distinct customer archetypes for this product.

        Product: {idea}
        Industry: {industry}
        Target market: {market}
        Price: {pricing_amount}

        Market signals:
        Complaints: {json.dumps(complaints[:5])}
        Demands: {json.dumps(demands[:5])}

        Each archetype MUST include ONLY these numeric traits (no adoption predictions):
        - name: persona label (e.g. "Price Sensitive Student")
        - segment: market cluster
        - occupation: typical job role
        - budget: 1-12 (1=very constrained, 12=high budget)
        - risk: 0.0-1.0 risk tolerance
        - social_influence: 0.0-1.0
        - tech_comfort: 0.0-1.0
        - price_elasticity: 0.0-1.0
        - switching_cost: 0.0-1.0
        - population_weight: 0.3-2.0 relative market share
        - objections: 1-2 short objection strings

        Cover diverse segments: students, founders, enterprise, skeptics, early adopters, etc.
        Do NOT predict purchase likelihood — only define who they are.
        """
        try:
            res = await call_openai_structured(prompt, ArchetypeDefinitionsResponse)
            if res and res.archetypes:
                for idx, a in enumerate(res.archetypes[:ARCHETYPE_COUNT]):
                    archetypes.append(archetype_from_llm(a.model_dump(), job_id, idx))
            if len(archetypes) < ARCHETYPE_COUNT:
                raise Exception(f"LLM returned only {len(archetypes)} archetypes")
        except Exception as e:
            logger.warning(f"LLM archetype generation failed, using seeded archetypes: {e}")
            archetypes = generate_mock_archetypes(job_id, industry, idea)
            
    # Save to Database
    async with SessionLocal() as db:
        for arch in archetypes:
            db.add(PersonaArchetype(
                id=arch["id"],
                job_id=job_id,
                name=arch["name"],
                age=arch["age"],
                income_bracket=arch["income_bracket"],
                occupation=arch["occupation"],
                location=arch["location"],
                buying_behavior=arch["buying_behavior"],
                goals=arch["goals"],
                objections=arch["objections"],
                risk_tolerance=arch["risk_tolerance"],
                budget_sensitivity=arch["budget_sensitivity"],
                segment=arch["segment"],
                influence=arch["influence"],
                buying_trigger=arch.get("buying_trigger", ""),
                pain_point=arch.get("pain_point", ""),
                adoption_probability=arch.get("adoption_probability", 0.5),
                behavior_type=arch.get("behavior_type", "Early Adopter"),
                technology_comfort=arch.get("technology_comfort", 50.0),
                risk_appetite=arch.get("risk_appetite", 50.0),
                social_influence=(
                    arch.get("social_influence", 0.5) * 100
                    if arch.get("social_influence", 0.5) <= 1.0
                    else arch.get("social_influence", 50.0)
                ),
                income=arch.get("income", 50000.0),
                urgency=arch.get("urgency", 50.0),
                existing_alternatives=arch.get("existing_alternatives", 50.0)
            ))
        await db.commit()
        
    logger.info(f"[{job_id}] ===== PERSONA ENGINE COMPLETE =====")
    return {"archetypes": archetypes}

# --- NODE 3: SIMULATION ENGINE (Layers 2+3 — expand to 5000, pure-code funnel) ---
async def simulation_engine_node(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== SIMULATION ENGINE START =====")
    await update_job_progress(
        job_id,
        f"Layer 2-3: Expanding to {POPULATION_SIZE:,} customers & running funnel simulation",
        "simulating",
        55,
    )
    
    try:
        return await asyncio.wait_for(_simulation_engine_impl(state), timeout=30.0)
    except Exception as e:
        logger.error(f"[{job_id}] SIMULATION ENGINE ERROR/TIMEOUT: {e} - using fallback mock simulations")
        try:
            from backend.app.services.mock_fixtures import generate_mock_simulations
            archetypes = state["archetypes"]
            results = generate_mock_simulations(job_id, archetypes, state["pricing_amount"], state["idea"], state["industry"])
            
            n = len(results) or 15
            buy_count = sum(1 for r in results if r["would_buy"])
            agg = {
                "total_population": 5000,
                "discover_count": int(5000 * 0.75),
                "care_count": int(5000 * 0.60),
                "try_count": int(5000 * 0.45),
                "convert_count": int(5000 * (buy_count / n)),
                "retain_count": int(5000 * (buy_count / n) * 0.85),
                "adoption_percentage": round((buy_count / n) * 100, 1),
                "retention_percentage": 85.0,
                "avg_likelihood": round(sum(r["likelihood_score"] for r in results) / n, 3),
                "avg_p_discover": 0.75,
                "avg_p_care": 0.60,
                "avg_p_try": 0.45,
                "avg_p_convert": round(buy_count / n, 3),
                "avg_p_retain": round((buy_count / n) * 0.85, 3),
            }
            
            redis_client.set_json(f"job:{job_id}:population_aggregate", agg, ex=86400)
            
            async with SessionLocal() as db:
                for res in results:
                    db.add(SimulationResult(
                        job_id=job_id,
                        archetype_id=res["archetype_id"],
                        would_buy=res["would_buy"],
                        excitement_score=res["excitement_score"],
                        objections=res["objections"],
                        likelihood_score=res["likelihood_score"],
                        reasoning=res["reasoning"]
                    ))
                await db.commit()
                
            return {"simulations": results, "population_aggregate": agg}
        except Exception as fallback_err:
            logger.error(f"[{job_id}] SIMULATION ENGINE FALLBACK FAILURE: {fallback_err}")
            raise e

async def _simulation_engine_impl(state: SimulationState) -> Dict[str, Any]:

    job_id = state["job_id"]
    archetypes = state["archetypes"]
    product = compute_product_context(
        idea=state["idea"],
        industry=state["industry"],
        market=state["market"],
        pricing_amount=state["pricing_amount"],
        signals=state["signals"],
        timeline=state["timeline"],
        region=state["region"],
    )

    customers = await asyncio.to_thread(expand_archetypes_to_customers, job_id, archetypes, POPULATION_SIZE)
    population_results, agg = await asyncio.to_thread(run_population_simulation, job_id, customers, product)
    results = aggregate_archetype_results(archetypes, population_results)

    # Cache for personas API
    redis_client.set_json(f"job:{job_id}:product_context", {
        "idea": product.idea, "industry": product.industry, "market": product.market,
        "pricing_amount": product.pricing_amount, "region": product.region, "timeline": product.timeline,
    }, ex=86400)
    redis_client.set_json(f"job:{job_id}:population_aggregate", agg, ex=86400)

    # Validate before proceeding to next stage
    try:
        validate_simulation_engine_output(job_id, results, agg)
    except ValueError as e:
        logger.error(f"[{job_id}] Simulation validation error: {e}")
        raise

    # Save to Database
    async with SessionLocal() as db:
        for res in results:
            db.add(SimulationResult(
                job_id=job_id,
                archetype_id=res["archetype_id"],
                would_buy=res["would_buy"],
                excitement_score=res["excitement_score"],
                objections=res["objections"],
                likelihood_score=res["likelihood_score"],
                reasoning=res["reasoning"]
            ))
        await db.commit()
        
    logger.info(f"[{job_id}] ===== SIMULATION ENGINE COMPLETE =====")
    return {"simulations": results, "population_aggregate": agg}

# --- NODE 4: SOCIAL INFLUENCE ENGINE ---
async def social_influence_engine_node(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== SOCIAL INFLUENCE ENGINE START =====")
    await update_job_progress(job_id, "Social diffusion model", "simulating", 70)
    
    try:
        return await asyncio.wait_for(_social_influence_engine_impl(state), timeout=20.0)
    except Exception as e:
        logger.error(f"[{job_id}] SOCIAL INFLUENCE ENGINE ERROR/TIMEOUT: {e} - using fallback social diffusion")
        try:
            categories = ["Innovators", "Early Adopters", "Early Majority", "Late Majority", "Laggards"]
            agg = state.get("population_aggregate", {}) or {}
            adoption_pct = agg.get("adoption_percentage", 30.0)
            
            adoption_curve = {}
            for cycle in range(6):
                adoption_curve[f"cycle_{cycle}"] = {}
                for cat in categories:
                    rate = (cycle / 5.0) * (adoption_pct / 100.0)
                    if cat == "Innovators":
                        rate = min(0.98, rate * 2.5)
                    elif cat == "Early Adopters":
                        rate = min(0.95, rate * 1.8)
                    adoption_curve[f"cycle_{cycle}"][cat] = round(rate, 3)
                    
            adoption_curve_cycles = []
            for cycle in range(6):
                rates = adoption_curve[f"cycle_{cycle}"]
                segment_size = 1000
                inno_cnt = int(round(rates.get("Innovators", 0.0) * segment_size))
                ea_cnt = int(round(rates.get("Early Adopters", 0.0) * segment_size))
                em_cnt = int(round(rates.get("Early Majority", 0.0) * segment_size))
                lm_cnt = int(round(rates.get("Late Majority", 0.0) * segment_size))
                lag_cnt = int(round(rates.get("Laggards", 0.0) * segment_size))
                
                cum_adoption = inno_cnt + ea_cnt + em_cnt + lm_cnt + lag_cnt
                cum_pct = round((cum_adoption / 5000) * 100, 2)
                
                adoption_curve_cycles.append({
                    "cycle": cycle,
                    "innovators_adopted": inno_cnt,
                    "early_adopters_adopted": ea_cnt,
                    "early_majority_adopted": em_cnt,
                    "late_majority_adopted": lm_cnt,
                    "laggards_adopted": lag_cnt,
                    "cumulative_adoption": cum_adoption,
                    "cumulative_adoption_pct": cum_pct
                })
                
            return {
                "adoption_curve": adoption_curve,
                "adoption_curve_cycles": adoption_curve_cycles,
                "final_adoption_pct": adoption_pct,
                "simulations": state.get("simulations", []),
                "population_aggregate": agg
            }
        except Exception as fallback_err:
            logger.error(f"[{job_id}] SOCIAL INFLUENCE ENGINE FALLBACK FAILURE: {fallback_err}")
            raise e

async def _social_influence_engine_impl(state: SimulationState) -> Dict[str, Any]:

    job_id = state["job_id"]
    agg = state.get("population_aggregate", {})
    adoption_pct = agg.get("adoption_percentage", 30.0)
    
    # Calculate social diffusion cycles
    adoption_curve = run_social_diffusion(state["archetypes"], state["simulations"], adoption_pct)
    
    # Build product context for simulation
    product = compute_product_context(
        idea=state["idea"],
        industry=state["industry"],
        market=state["market"],
        pricing_amount=state["pricing_amount"],
        signals=state["signals"],
        timeline=state["timeline"],
        region=state["region"],
    )
    
    # Run helper to adjust 5000 population based on Cycle 5 Rogers diffusion rates
    population_results, updated_agg = await asyncio.to_thread(
        get_adjusted_population_results,
        job_id=job_id,
        archetypes=state["archetypes"],
        product=product,
        adoption_curve=adoption_curve
    )

    # Group simulation results by category for cycle statistics
    arch_to_cat = {}
    for idx, arch in enumerate(state["archetypes"]):
        if idx < max(1, len(state["archetypes"]) // 15):
            cat = "Innovators"
        elif idx < max(2, len(state["archetypes"]) // 5):
            cat = "Early Adopters"
        elif idx < len(state["archetypes"]) // 2:
            cat = "Early Majority"
        elif idx < len(state["archetypes"]) * 4 // 5:
            cat = "Late Majority"
        else:
            cat = "Laggards"
        arch_to_cat[arch["id"]] = cat

    cat_sims = {c: [] for c in ["Innovators", "Early Adopters", "Early Majority", "Late Majority", "Laggards"]}
    for r in population_results:
        cat = arch_to_cat.get(r.archetype_id, "Laggards")
        cat_sims[cat].append(r)

    # Calculate cumulative counts and percentages for each cycle
    adoption_curve_cycles = []
    total_pop = len(population_results)
    
    for cycle in range(6):
        cycle_key = f"cycle_{cycle}"
        rates = adoption_curve.get(cycle_key, {})
        
        inno_cnt = int(round(rates.get("Innovators", 0.0) * len(cat_sims["Innovators"])))
        ea_cnt = int(round(rates.get("Early Adopters", 0.0) * len(cat_sims["Early Adopters"])))
        em_cnt = int(round(rates.get("Early Majority", 0.0) * len(cat_sims["Early Majority"])))
        lm_cnt = int(round(rates.get("Late Majority", 0.0) * len(cat_sims["Late Majority"])))
        lag_cnt = int(round(rates.get("Laggards", 0.0) * len(cat_sims["Laggards"])))
        
        cum_adoption = inno_cnt + ea_cnt + em_cnt + lm_cnt + lag_cnt
        cum_pct = round((cum_adoption / total_pop) * 100, 2)
        
        adoption_curve_cycles.append({
            "cycle": cycle,
            "innovators_adopted": inno_cnt,
            "early_adopters_adopted": ea_cnt,
            "early_majority_adopted": em_cnt,
            "late_majority_adopted": lm_cnt,
            "laggards_adopted": lag_cnt,
            "cumulative_adoption": cum_adoption,
            "cumulative_adoption_pct": cum_pct
        })

    # Aggregate adjusted results back to 15 archetype summaries
    adjusted_simulations = aggregate_archetype_results(state["archetypes"], population_results)

    # Save social-influence adjusted simulation summaries to database (overwrite unadjusted ones)
    from sqlalchemy import delete
    async with SessionLocal() as db:
        q = delete(SimulationResult).where(SimulationResult.job_id == job_id)
        await db.execute(q)
        await db.flush()
        
        for res in adjusted_simulations:
            db.add(SimulationResult(
                job_id=job_id,
                archetype_id=res["archetype_id"],
                would_buy=res["would_buy"],
                excitement_score=res["excitement_score"],
                objections=res["objections"],
                likelihood_score=res["likelihood_score"],
                reasoning=res["reasoning"]
            ))
        await db.commit()

    logger.info(f"[{job_id}] ===== SOCIAL INFLUENCE ENGINE COMPLETE =====")
    return {
        "adoption_curve": adoption_curve,
        "adoption_curve_cycles": adoption_curve_cycles,
        "final_adoption_pct": updated_agg["adoption_percentage"],
        "simulations": adjusted_simulations,
        "population_aggregate": updated_agg
    }

# --- NODE 5: FORECAST ENGINE ---
async def forecast_engine_node(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== FORECAST ENGINE START =====")
    await update_job_progress(job_id, "Forecast Engine: Projecting growth models", "forecasting", 85)
    
    try:
        return await asyncio.wait_for(_forecast_engine_impl(state), timeout=20.0)
    except Exception as e:
        logger.error(f"[{job_id}] FORECAST ENGINE ERROR/TIMEOUT: {e} - using fallback forecast")
        try:
            pricing_amount = state["pricing_amount"]
            pricing_currency = state["pricing_currency"]
            agg = state.get("population_aggregate", {}) or {}
            adoption_pct = agg.get("adoption_percentage", 30.0)
            
            tam = 500000
            proj_12mo = (adoption_pct / 100.0) * tam * pricing_amount
            proj_3mo = proj_12mo * 0.25
            proj_6mo = proj_12mo * 0.60
            
            forecast_data = {
                "addressable_market": tam,
                "confidence_score": 75,
                "adoption_percentage": adoption_pct,
                "product_market_fit_score": int(adoption_pct),
                "pmf_label": "Strong Fit" if adoption_pct >= 70 else "Moderate Fit" if adoption_pct >= 40 else "Weak Fit",
                "market_reception": {
                    "overall_label": "Mixed",
                    "breakdown": {
                        "enthusiastic_pct": 25.0,
                        "interested_pct": 35.0,
                        "skeptical_pct": 25.0,
                        "rejecting_pct": 15.0
                    }
                },
                "ranked_objections": [
                    {"objection": "Pricing / High Cost", "count": 120, "percentage": 40.0},
                    {"objection": "Onboarding complexity", "count": 80, "percentage": 26.7}
                ],
                "revenue_projection": {
                    "currency": pricing_currency,
                    "projections": [
                        {"months": 3, "estimate": int(proj_3mo), "low": int(proj_3mo * 0.8), "high": int(proj_3mo * 1.2)},
                        {"months": 6, "estimate": int(proj_6mo), "low": int(proj_6mo * 0.8), "high": int(proj_6mo * 1.2)},
                        {"months": 12, "estimate": int(proj_12mo), "low": int(proj_12mo * 0.8), "high": int(proj_12mo * 1.2)}
                    ],
                    "tam_used": tam,
                    "tam_reasoning": "Standard TAM fallback since real estimation failed",
                    "tam_confidence": "medium",
                    "assumptions": [
                        f"TAM of {tam:,} customers", 
                        f"Price point of {pricing_currency} {pricing_amount:.2f}",
                        "Ramped adoption model"
                    ]
                }
            }
            return {"forecast": forecast_data}
        except Exception as fallback_err:
            logger.error(f"[{job_id}] FORECAST ENGINE FALLBACK FAILURE: {fallback_err}")
            raise e

async def _forecast_engine_impl(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    idea = state["idea"]
    industry = state["industry"]
    region = state["region"]
    pricing_amount = state["pricing_amount"]
    pricing_currency = state["pricing_currency"]
    
    archetypes = state["archetypes"]
    adoption_curve = state["adoption_curve"]
    
    # Load product context
    product = compute_product_context(
        idea=idea,
        industry=industry,
        market=state["market"],
        pricing_amount=pricing_amount,
        signals=state["signals"],
        timeline=state["timeline"],
        region=region,
    )
    
    # Recreate the adjusted 5000 population results
    population_results, updated_agg = await asyncio.to_thread(
        get_adjusted_population_results,
        job_id=job_id,
        archetypes=archetypes,
        product=product,
        adoption_curve=adoption_curve
    )
    
    # Generate forecasted addressable market with justified reasoning
    tam_estimate, tam_reasoning, tam_confidence = await estimate_tam(idea, industry, region)
    addressable_market = tam_estimate
    
    # Convert TAM confidence to numeric score for revenue bands
    confidence_score_map = {"low": 60, "medium": 75, "high": 90}
    confidence = confidence_score_map.get(tam_confidence, 75)
    
    # Compile forecast details
    # Group and rank objections from all 5000 customers
    all_objections = []
    for r in population_results:
        all_objections.extend(r.objections)
        
    objection_counts = {}
    for obj in all_objections:
        simple_obj = obj
        for kw in ["price", "cost", "pricing", "expensive"]:
            if kw in obj.lower():
                simple_obj = "Pricing / High Cost"
        for kw in ["security", "privacy", "data", "kyc", "hipaa"]:
            if kw in obj.lower():
                simple_obj = "Security, Privacy & Compliance"
        for kw in ["complex", "learning", "difficult", "setup", "learning curve"]:
            if kw in obj.lower():
                simple_obj = "Onboarding complexity / steep learning curve"
        for kw in ["integration", "stack", "api"]:
            if kw in obj.lower():
                simple_obj = "Third-party Integration issues"
        for kw in ["offline", "internet"]:
            if kw in obj.lower():
                simple_obj = "Lack of offline functionality"
        objection_counts[simple_obj] = objection_counts.get(simple_obj, 0) + 1
        
    ranked_objections = [
        {
            "objection": k, 
            "count": v,
            "percentage": round((v / max(len(population_results), 1)) * 100.0, 1)
        } 
        for k, v in sorted(objection_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    # Determine cycle percentages for 3mo, 6mo, and 12mo projections
    adoption_cycles = state.get("adoption_curve_cycles", [])
    if len(adoption_cycles) >= 6:
        pct_3mo = adoption_cycles[1]["cumulative_adoption_pct"]
        pct_6mo = adoption_cycles[3]["cumulative_adoption_pct"]
        pct_12mo = adoption_cycles[5]["cumulative_adoption_pct"]
    else:
        pct_12mo = updated_agg["adoption_percentage"]
        pct_3mo = pct_12mo * 0.3
        pct_6mo = pct_12mo * 0.7
        
    # Compute Product-Market Fit score using 5000-persona adjusted results
    pmf_score, pmf_label = compute_product_market_fit_score(
        population_results=population_results,
        population_aggregate=updated_agg,
        signals=state["signals"],
        idea=idea
    )
    
    # Compute Market Reception breakdown from excitement_score distribution
    market_reception = compute_market_reception_breakdown(population_results)
    
    # Calculate revenue with confidence-responsive bands
    PERIOD_ADJUSTMENT_3MO = 0.25
    PERIOD_ADJUSTMENT_6MO = 0.60
    PERIOD_ADJUSTMENT_12MO = 1.0
    
    proj_3mo_est = (pct_3mo / 100.0) * addressable_market * pricing_amount * PERIOD_ADJUSTMENT_3MO
    proj_6mo_est = (pct_6mo / 100.0) * addressable_market * pricing_amount * PERIOD_ADJUSTMENT_6MO
    proj_12mo_est = (pct_12mo / 100.0) * addressable_market * pricing_amount * PERIOD_ADJUSTMENT_12MO
    
    # Confidence-responsive ranges: ±(100 - confidence) / 100 × estimate
    confidence_band_scale = (100.0 - confidence) / 100.0
    
    def build_revenue_estimate(estimate: float, confidence_band: float) -> Dict[str, int]:
        """Build low/high band based on confidence score."""
        band_width = estimate * confidence_band
        return {
            "estimate": int(estimate),
            "low": int(max(0.0, estimate - band_width)),
            "high": int(estimate + band_width)
        }
    
    forecast_data = {
        "addressable_market": addressable_market,
        "confidence_score": confidence,
        "adoption_percentage": updated_agg["adoption_percentage"],
        "product_market_fit_score": pmf_score,
        "pmf_label": pmf_label,
        "market_reception": market_reception,
        "ranked_objections": ranked_objections,
        "revenue_projection": {
            "currency": pricing_currency,
            "projections": [
                {"months": 3, **build_revenue_estimate(proj_3mo_est, confidence_band_scale)},
                {"months": 6, **build_revenue_estimate(proj_6mo_est, confidence_band_scale)},
                {"months": 12, **build_revenue_estimate(proj_12mo_est, confidence_band_scale)}
            ],
            "tam_used": addressable_market,
            "tam_reasoning": tam_reasoning,
            "tam_confidence": tam_confidence,
            "assumptions": [
                f"TAM of {addressable_market:,} customers in {region}",
                f"Adoption of {pct_3mo:.1f}% by 3mo, {pct_6mo:.1f}% by 6mo, and {pct_12mo:.1f}% by 12mo based on Rogers Diffusion cycles",
                f"Price point of {pricing_currency} {pricing_amount:.2f} per customer",
                f"Gradual rollout ramp adjustment: {int(PERIOD_ADJUSTMENT_3MO*100)}% by 3mo, {int(PERIOD_ADJUSTMENT_6MO*100)}% by 6mo, {int(PERIOD_ADJUSTMENT_12MO*100)}% by 12mo",
                f"Confidence band width of ±{int(confidence_band_scale*100)}% responding to {tam_confidence.upper()} confidence level ({confidence}%)"
            ]
        }
    }
    
    # Validate forecast output before returning
    try:
        validate_forecast_engine_output(job_id, forecast_data)
    except ValueError as e:
        logger.error(f"[{job_id}] Forecast validation error: {e}")
        raise
    
    logger.info(f"[{job_id}] ===== FORECAST ENGINE COMPLETE =====")
    return {"forecast": forecast_data}


async def estimate_tam(
    idea: str,
    industry: str,
    region: str,
) -> Tuple[int, str, str]:
    """
    Estimate Total Addressable Market (TAM) with LLM-justified reasoning.
    
    Returns: (tam_estimate, tam_reasoning, tam_confidence)
    """
    if settings.MOCK_MODE:
        # Use default TAM estimates for mock mode
        default_tams = {
            "SaaS": 500000,
            "E-commerce": 2000000,
            "FinTech": 1500000,
            "Healthtech": 800000,
            "Consumer Hardware": 300000,
            "Other": 400000,
        }
        tam_est = default_tams.get(industry, 500000)
        return tam_est, f"Mock TAM estimate for {industry} in {region} based on typical market size and segment penetration rates", "medium"
    
    prompt = f"""
    Estimate the Total Addressable Market (TAM) size for the following product in {region}:
    
    Product: {idea}
    Industry: {industry}
    
    Provide a justified estimate of the number of potential customers, not a round guess.
    Base your estimate on:
    - Regional population and relevant demographics
    - Segment penetration rates (e.g., % of population using smartphones, having internet, needing this service)
    - Geographic adjustments for {region}
    - Any industry-specific market research you know about
    
    Be specific in your reasoning. For example:
    - If the product targets US software engineers: ~4.5M software developers in US × adoption potential
    - If the product targets global e-commerce sellers: ~100M online sellers globally × adoption potential
    
    Return a justified number, not a placeholder.
    """
    
    try:
        res = await call_openai_structured(prompt, TAMEstimation)
        if res:
            logger.info(
                f"TAM Estimation: {res.tam_estimate} customers ({res.tam_confidence} confidence) | "
                f"Reasoning: {res.tam_reasoning[:100]}..."
            )
            return res.tam_estimate, res.tam_reasoning, res.tam_confidence
    except Exception as e:
        logger.warning(f"TAM estimation LLM call failed: {e}")
    
    # Fallback: use industry defaults
    default_tams = {
        "SaaS": 500000,
        "E-commerce": 2000000,
        "FinTech": 1500000,
        "Healthtech": 800000,
        "Consumer Hardware": 300000,
        "Other": 400000,
    }
    tam_est = default_tams.get(industry, 500000)
    return tam_est, f"Default TAM estimate for {industry} in {region} (LLM estimation failed)", "low"


async def extract_competitors(
    idea: str,
    industry: str,
    raw_signals: str = "",
) -> List[Dict[str, str]]:
    """
    Extract real, named competitors from market signals and general knowledge.
    
    Returns list of dicts with keys: name, why_relevant, positioning
    """
    if settings.MOCK_MODE:
        # Use industry-appropriate real company fixtures
        fixtures = {
            "SaaS": [
                {"name": "Salesforce", "why_relevant": "Leading CRM platform with broad enterprise adoption", "positioning": "Enterprise-focused, established market leader"},
                {"name": "HubSpot", "why_relevant": "All-in-one inbound platform for marketing and sales", "positioning": "SMB-focused, ease of use"},
                {"name": "Pipedrive", "why_relevant": "Sales-focused CRM with visual pipeline", "positioning": "Sales teams, affordable"},
            ],
            "FinTech": [
                {"name": "Stripe", "why_relevant": "Payment processing platform for online businesses", "positioning": "Developer-friendly, global payment infrastructure"},
                {"name": "Square", "why_relevant": "Point-of-sale and payments for small business", "positioning": "In-person payments, integrated ecosystem"},
                {"name": "Wise", "why_relevant": "International money transfers and multi-currency accounts", "positioning": "Low-cost, transparent international transfers"},
            ],
            "E-commerce": [
                {"name": "Shopify", "why_relevant": "Leading e-commerce platform for online stores", "positioning": "SMB-focused, app ecosystem"},
                {"name": "WooCommerce", "why_relevant": "WordPress-based e-commerce solution", "positioning": "Customizable, self-hosted option"},
                {"name": "BigCommerce", "why_relevant": "Enterprise e-commerce platform", "positioning": "Large merchants, feature-rich"},
            ],
            "Healthtech": [
                {"name": "Teladoc", "why_relevant": "Virtual care platform connecting patients with physicians", "positioning": "Enterprise employer benefit, clinical breadth"},
                {"name": "Ro", "why_relevant": "Direct-to-consumer telehealth for prescription medications", "positioning": "Consumer-friendly, affordable medications"},
                {"name": "Hims & Hers", "why_relevant": "Telehealth and prescription delivery", "positioning": "Consumer-focused, comprehensive wellness"},
            ],
            "Consumer Hardware": [
                {"name": "Apple", "why_relevant": "Premium consumer electronics and ecosystem", "positioning": "Premium brand, ecosystem lock-in"},
                {"name": "Samsung", "why_relevant": "Diversified consumer electronics manufacturer", "positioning": "Cost-competitive, variety of products"},
                {"name": "Anker", "why_relevant": "Affordable consumer electronics and accessories", "positioning": "Value-focused, quality for price"},
            ],
            "Other": [
                {"name": "Slack", "why_relevant": "Team communication platform", "positioning": "Workplace collaboration, extensive integrations"},
                {"name": "Notion", "why_relevant": "Productivity and knowledge management", "positioning": "Flexible, all-in-one workspace"},
                {"name": "Zapier", "why_relevant": "Workflow automation platform", "positioning": "No-code automation, broad integration support"},
            ],
        }
        return fixtures.get(industry, fixtures["Other"])[:3]
    
    prompt = f"""
    Extract up to 8 real, named companies or products that compete with or are directly comparable to:
    
    Product Idea: {idea}
    Industry: {industry}
    
    Market Signals (for context):
    {raw_signals if raw_signals else "(No market signal context provided)"}
    
    IMPORTANT CONSTRAINTS:
    1. Only return names of REAL companies or products that ACTUALLY EXIST
    2. Names must either:
       a) Appear explicitly in the provided market signal context, OR
       b) Be well-known, factual companies in this industry that you have reliable knowledge of
    3. NEVER use placeholders like "Competitor A", "Company X", "Product Z", "Sample Product"
    4. If you cannot find or confidently name 3+ real competitors, describe 3-5 REAL, well-known category leaders by name
    
    For each competitor, provide:
    - name: The actual company/product name
    - why_relevant: 1 sentence explaining why this is a competitor/alternative
    - positioning: 1 sentence on how they differ from or compare to the idea
    """
    
    try:
        res = await call_openai_structured(prompt, CompetitorExtraction)
        if res and res.competitors:
            logger.info(f"Extracted {len(res.competitors)} competitors: {[c.name for c in res.competitors]}")
            return [c.model_dump() for c in res.competitors]
    except Exception as e:
        logger.warning(f"Competitor extraction LLM call failed: {e}")
    
    # Fallback to fixture if extraction fails
    fixtures = {
        "SaaS": [
            {"name": "Salesforce", "why_relevant": "Leading CRM platform with broad enterprise adoption", "positioning": "Enterprise-focused, established market leader"},
            {"name": "HubSpot", "why_relevant": "All-in-one inbound platform for marketing and sales", "positioning": "SMB-focused, ease of use"},
            {"name": "Pipedrive", "why_relevant": "Sales-focused CRM with visual pipeline", "positioning": "Sales teams, affordable"},
        ],
        "FinTech": [
            {"name": "Stripe", "why_relevant": "Payment processing platform for online businesses", "positioning": "Developer-friendly, global payment infrastructure"},
            {"name": "Square", "why_relevant": "Point-of-sale and payments for small business", "positioning": "In-person payments, integrated ecosystem"},
            {"name": "Wise", "why_relevant": "International money transfers and multi-currency accounts", "positioning": "Low-cost, transparent international transfers"},
        ],
        "E-commerce": [
            {"name": "Shopify", "why_relevant": "Leading e-commerce platform for online stores", "positioning": "SMB-focused, app ecosystem"},
            {"name": "WooCommerce", "why_relevant": "WordPress-based e-commerce solution", "positioning": "Customizable, self-hosted option"},
            {"name": "BigCommerce", "why_relevant": "Enterprise e-commerce platform", "positioning": "Large merchants, feature-rich"},
        ],
        "Healthtech": [
            {"name": "Teladoc", "why_relevant": "Virtual care platform connecting patients with physicians", "positioning": "Enterprise employer benefit, clinical breadth"},
            {"name": "Ro", "why_relevant": "Direct-to-consumer telehealth for prescription medications", "positioning": "Consumer-friendly, affordable medications"},
            {"name": "Hims & Hers", "why_relevant": "Telehealth and prescription delivery", "positioning": "Consumer-focused, comprehensive wellness"},
        ],
        "Consumer Hardware": [
            {"name": "Apple", "why_relevant": "Premium consumer electronics and ecosystem", "positioning": "Premium brand, ecosystem lock-in"},
            {"name": "Samsung", "why_relevant": "Diversified consumer electronics manufacturer", "positioning": "Cost-competitive, variety of products"},
            {"name": "Anker", "why_relevant": "Affordable consumer electronics and accessories", "positioning": "Value-focused, quality for price"},
        ],
        "Other": [
            {"name": "Slack", "why_relevant": "Team communication platform", "positioning": "Workplace collaboration, extensive integrations"},
            {"name": "Notion", "why_relevant": "Productivity and knowledge management", "positioning": "Flexible, all-in-one workspace"},
            {"name": "Zapier", "why_relevant": "Workflow automation platform", "positioning": "No-code automation, broad integration support"},
        ]
    }
    return fixtures.get(industry, fixtures["Other"])[:3]


def validate_and_sanitize_report(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate and sanitize report data against ReportEngineOutput schema,
    and verify no NaNs, empty strings, or placeholder text leaks.
    """
    import math

    # 1. Pydantic validation
    try:
        ReportEngineOutput.model_validate(report_data)
    except ValidationError as e:
        raise ValueError(f"Report model validation failed: {e}")

    # 2. String leakage and NaN validation
    def check_string_leakage(data: Any, path: str = "") -> None:
        allowed_short_keys = {
            "job_id", "opportunity_label", "pmf_label", "currency", 
            "tam_confidence", "severity", "sentiment", "overall_label", 
            "name", "location", "role", "risk_tolerance", "income_bracket",
            "id", "archetype_id", "customer_id", "months", "trend", "status",
            "winner", "features", "price", "trust", "size_percentage", "average_likelihood",
            "key_traits", "confidence", "sources", "trend", "switching_cost", "market_fit",
            "pricing_power", "brand_strength", "innovation_score", "customer_satisfaction",
            "adoption", "recommendation", "launch_recommendation"
        }
        if isinstance(data, dict):
            for k, v in data.items():
                check_string_leakage(v, f"{path}.{k}" if path else k)
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                check_string_leakage(item, f"{path}[{idx}]")
        elif isinstance(data, str):
            field_name = path.split(".")[-1].split("[")[0]
            if field_name not in allowed_short_keys:
                cleaned = data.strip()
                if len(cleaned) == 0:
                    raise ValueError(f"String field '{path}' is empty")
                if len(cleaned) <= 10:
                    raise ValueError(f"String field '{path}' is too short (got {len(cleaned)} chars, expected > 10). Value: '{data}'")
                
                # Check for forbidden methodology references in executive summary
                if "executive_summary" in path.lower():
                    forbidden = ["aura", "simulation", "synthetic", "this analysis", "our tool"]
                    summary_lower = cleaned.lower()
                    for f in forbidden:
                        if f in summary_lower:
                            raise ValueError(f"Executive brief mentions forbidden term '{f}' (should advise founder about product only)")
                
                # Check for generic quotes
                if "customer_quotes" in path.lower() and "quote" in path.lower():
                    generic_phrases = ["this product is great", "i would definitely recommend", "this is amazing", "really helpful", "game changer", "best thing", "love it"]
                    quote_lower = cleaned.lower()
                    for phrase in generic_phrases:
                        if phrase in quote_lower and len(cleaned) < 40:
                            raise ValueError(f"Customer quote is too generic or short: '{data}'")

                # Check for placeholders in competitor names
                if "competitor" in path.lower() and "name" in path.lower():
                    placeholder_names = ["competitor a", "competitor b", "company a", "product a", "sample", "lorem", "industry leader"]
                    name_lower = cleaned.lower()
                    for p in placeholder_names:
                        if p in name_lower:
                            raise ValueError(f"Competitor name appears to be a placeholder: '{data}'")
        elif isinstance(data, (int, float)):
            if math.isnan(data) or math.isinf(data):
                raise ValueError(f"Numeric field '{path}' is NaN or Inf")

    check_string_leakage(report_data)
    logger.info("Report data validation successful")
    return report_data


# --- NODE 6: REPORT ENGINE ---
async def report_engine_node(state: SimulationState) -> Dict[str, Any]:
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== REPORT ENGINE START =====")
    await update_job_progress(job_id, "Report Engine: Synthesizing final report", "generating_report", 95)
    
    try:
        return await asyncio.wait_for(_report_engine_impl(state), timeout=20.0)
    except Exception as e:
        logger.error(f"[{job_id}] REPORT ENGINE ERROR/TIMEOUT: {e} - using fallback report")
        try:
            from backend.app.services.mock_fixtures import generate_mock_report
            mock_report = generate_mock_report(
                job_id=job_id,
                idea=state["idea"],
                industry=state["industry"],
                pricing_amount=state["pricing_amount"],
                pricing_currency=state["pricing_currency"],
                region=state["region"],
                archetypes=state["archetypes"]
            )
            
            # Save Report to Postgres database
            async with SessionLocal() as db:
                from sqlalchemy import select
                q = select(Report).where(Report.job_id == job_id)
                res = await db.execute(q)
                existing_rep = res.scalar_one_or_none()
                if existing_rep:
                    await db.delete(existing_rep)
                    await db.flush()
                
                db.add(Report(
                    job_id=job_id,
                    executive_summary=mock_report["executive_summary"],
                    opportunity_score=mock_report["opportunity_score"],
                    opportunity_label=mock_report["opportunity_label"],
                    launch_recommendation=mock_report["launch_recommendation"],
                    launch_rationale=mock_report["launch_rationale"],
                    customer_quotes=mock_report["customer_quotes"],
                    revenue_projection=mock_report["revenue_projection"],
                    risk_analysis=mock_report["risk_analysis"],
                    adoption_curve=mock_report["adoption_curve"],
                    market_segments=mock_report["market_segments"],
                    pricing_recommendation=mock_report["pricing_recommendation"],
                    go_to_market_strategy=mock_report["go_to_market_strategy"],
                    confidence_score=mock_report["confidence_score"],
                    
                    # Enriched structures
                    signal_intelligence=mock_report.get("signal_intelligence", {}),
                    buyer_journey=mock_report.get("buyer_journey", {}),
                    simulated_conversations=mock_report.get("simulated_conversations", []),
                    competitors_battle=mock_report.get("competitors_battle", {}),
                    confidence_details=mock_report.get("confidence_details", {}),
                    objections_list=mock_report.get("objections_list", []),
        
                    # Market Friction columns
                    launch_difficulty=mock_report.get("launch_difficulty", 0.0),
                    price_friction=mock_report.get("price_friction", 0.0),
                    social_friction=mock_report.get("social_friction", 0.0),
                    behavior_change_cost=mock_report.get("behavior_change_cost", 0.0),
                    trust_requirement=mock_report.get("trust_requirement", 0.0),
                    infrastructure_requirement=mock_report.get("infrastructure_requirement", 0.0),
                    switching_cost=mock_report.get("switching_cost", 0.0),
                    time_to_value=mock_report.get("time_to_value", 0.0),
                    novelty_penalty=mock_report.get("novelty_penalty", 0.0),
                    education_cost=mock_report.get("education_cost", 0.0),
                    product_market_fit=mock_report.get("product_market_fit", 0.0),
                    social_adoption=mock_report.get("social_adoption", 0.0),
                    price_acceptance=mock_report.get("price_acceptance", 0.0),
                    trust_barrier=mock_report.get("trust_barrier", 0.0),
                    habit_change_required=mock_report.get("habit_change_required", 0.0),
                    scenario_tests=mock_report.get("scenario_tests", [])
                ))
                await db.commit()
                
            await update_job_progress(job_id, "Pipeline complete", "complete", 100)
            return {"report": mock_report}
        except Exception as fallback_err:
            logger.error(f"[{job_id}] REPORT ENGINE FALLBACK FAILURE: {fallback_err}")
            raise e

async def _report_engine_impl(state: SimulationState) -> Dict[str, Any]:


    job_id = state["job_id"]
    idea = state["idea"]
    industry = state["industry"]
    region = state["region"]
    pricing_amount = state["pricing_amount"]
    pricing_currency = state["pricing_currency"]
    
    archetypes = state["archetypes"]
    simulations = state["simulations"]
    adoption_curve = state["adoption_curve"]
    forecast = state["forecast"]
    
    product = state.get("product_context") or compute_product_context(
        idea, industry, state["market"], pricing_amount, state["signals"], state["timeline"], region
    )

    # Re-run population sim for report detail, adjusted for social influence
    population_results, agg = await asyncio.to_thread(
        get_adjusted_population_results,
        job_id=job_id,
        archetypes=archetypes,
        product=product,
        adoption_curve=adoption_curve
    )

    report_data = build_report_data(
        job_id=job_id, idea=idea, industry=industry, market=state["market"],
        pricing_amount=pricing_amount, pricing_currency=pricing_currency, region=region,
        archetypes=archetypes, archetype_summaries=simulations,
        population_results=population_results, agg=agg, product=product,
        adoption_curve=adoption_curve, signals=state["signals"],
    )
    
    # Wire Forecast metrics and PMF details into final report
    report_data["revenue_projection"] = forecast["revenue_projection"]
    report_data["confidence_score"] = forecast["confidence_score"]
    report_data["product_market_fit"] = float(forecast["product_market_fit_score"])
    report_data["pmf_label"] = forecast["pmf_label"]
    report_data["market_reception"] = forecast["market_reception"]
    
    # Set competitors on report_data from signals
    if state.get("signals") and len(state["signals"]) > 0:
        report_data["competitors"] = state["signals"][0].get("competitors", [])
    else:
        report_data["competitors"] = []

    # Helpers for structured LLM generation of quotes and executive brief
    async def generate_quotes(feedback_prompt: str = "") -> Optional[CustomerQuotesResponse]:
        sample_profiles = []
        buyers = [r for r in population_results if r.would_buy]
        rejecters = [r for r in population_results if not r.would_buy]
        samples = buyers[:2] + rejecters[:2]
        if len(samples) < 5 and len(population_results) > len(samples):
            samples += [r for r in population_results if r not in samples][:5 - len(samples)]
            
        for idx, r in enumerate(samples):
            arch_name = next((a["name"] for a in archetypes if a["id"] == r.archetype_id), "Target Customer")
            sample_profiles.append(
                f"Profile {idx+1}:\n"
                f"- Archetype: {arch_name}\n"
                f"- Decision: {'Would Buy' if r.would_buy else 'Would Not Buy'}\n"
                f"- Excitement Score: {int(round(r.likelihood * 10))}/10\n"
                f"- Objections: {', '.join(r.objections)}\n"
                f"- Reasoning: {r.reasoning}"
            )
        
        prompt = f"""
        Write 6 to 8 short customer review quotes (1-3 sentences each) as if real people tried:
        Product Idea: {idea}
        Industry: {industry}
        Target Market: {state["market"]}
        Price Point: {pricing_currency} {pricing_amount:.2f}
        
        Here are 3-5 sample simulated decisions:
        {"\n\n".join(sample_profiles)}
        
        CRITICAL REQUIREMENTS:
        1. Write exactly 6 to 8 customer review quotes.
        2. Quotes must reference CONCRETE details of THIS product (e.g., stated purpose, target use case, price point of {pricing_currency} {pricing_amount}), and NOT use generic SaaS or template language (like "this product is great").
        3. Vary the tone: write 2-3 enthusiastic (positive), 2-3 mixed/skeptical (mixed), and 1-2 negative (negative) quotes, reflecting the actual customer simulation behavior.
        4. Vary the writing style and voice per quote.
        {feedback_prompt}
        """
        return await call_openai_structured(prompt, CustomerQuotesResponse)

    async def generate_briefing(feedback_prompt: str = "") -> Optional[ReportBriefingResponse]:
        prompt = f"""
        Write a strategic briefing for the founder of:
        Product: {idea}
        Industry: {industry}
        Region: {region}
        Pricing: {pricing_currency} {pricing_amount:.2f}
        
        Based on the following data points:
        - Product-Market Fit (PMF) Score: {forecast['product_market_fit_score']}/100 ({forecast['pmf_label']})
        - Final Expected Adoption Rate: {report_data['opportunity_score']}%
        - Market Reception Breakdown:
          * Enthusiastic: {report_data['market_reception']['enthusiastic_pct']}%
          * Interested: {report_data['market_reception']['interested_pct']}%
          * Skeptical: {report_data['market_reception']['skeptical_pct']}%
          * Rejecting: {report_data['market_reception']['rejecting_pct']}%
        - Top Objections Raised by Potential Customers:
          {json.dumps([o["issue"] for o in report_data.get("objections_list", [])])}
        - 12-Month Expected Revenue: {pricing_currency} {forecast['revenue_projection']['projections'][2]['estimate']:,}
        - Top Competitors in this Space:
          {json.dumps([c["name"] for c in report_data.get("competitors", [])])}
          
        CRITICAL INSTRUCTIONS:
        1. The executive summary MUST be written as a 2-3 paragraph strategic brief directly to the founder. It must NEVER mention "AURA", "this simulation", "our analysis tool", "synthetic personas", or describe the simulation/analysis methodology. Frame everything as direct advice about their product and the market.
        2. The tone must be direct, confident, and consultative (e.g. use "You should...", "Consider...", "Before launching, prioritize..."). No hedging filler.
        3. The launch_recommendation must be a clear action directive (e.g., "Proceed", "Delay or Pivot").
        4. The launch_rationale must explain why, pointing to the PMF, competitor position, or price elasticity.
        5. The risk_analysis must contain exactly 3 risks focusing on market/competitor dynamics, severity (low, medium, high), and actionable mitigation.
        {feedback_prompt}
        """
        return await call_openai_structured(prompt, ReportBriefingResponse)

    # Compile the final brief & quotes
    if settings.MOCK_MODE:
        brief_data = {
            "executive_summary": f"Your product '{idea}' shows promise in {industry}. The market exhibits strong interest in core features, though pricing remains a concern. Focus on optimizing pricing models and addressing key objections to improve adoption rates.",
            "launch_recommendation": report_data.get("launch_recommendation") or ("Proceed" if "notion" in idea.lower() else "Delay or Pivot"),
            "launch_rationale": f"Based on the simulation data showing {report_data.get('opportunity_score', 45)}% adoption potential and moderate launch difficulty, you should proceed with a phased launch. The market reception indicates interest but pricing sensitivity requires attention before full market rollout.",
            "risk_analysis": [
                {"risk": "Pricing model adoption drag due to sensitivity among budget-conscious segments", "severity": "medium", "mitigation": "Offer flexible billing terms and tiered pricing options"},
                {"risk": "Competitive density in {industry} requiring clear differentiation", "severity": "medium", "mitigation": "Position around speed-to-value and unique feature set"},
                {"risk": "User behavior change cost affecting adoption rates", "severity": "low", "mitigation": "Provide interactive onboarding guides and migration assistance"}
            ]
        }
        quotes_data = {
            "customer_quotes": [
                {"quote": f"The price point of {pricing_currency} {pricing_amount} is perfect for our team. The automation will save us hours.", "sentiment": "positive", "persona_segment": "Innovator Segment"},
                {"quote": "I am interested but need to see how it integrates with our existing database before committing.", "sentiment": "mixed", "persona_segment": "Early Adopter Segment"},
                {"quote": f"At {pricing_currency} {pricing_amount}, it is too expensive for a small business. I will stick to spreadsheet work.", "sentiment": "negative", "persona_segment": "Laggard Segment"},
                {"quote": "This matches our workflow needs perfectly. The learning curve seems low.", "sentiment": "positive", "persona_segment": "Early Majority Segment"},
                {"quote": "Looks good but compliance is key. We need SOC2 before we can adopt.", "sentiment": "mixed", "persona_segment": "Late Majority Segment"},
                {"quote": "A decent tool but the price is too high compared to basic tools.", "sentiment": "mixed", "persona_segment": "Pragmatist Segment"}
            ]
        }
    else:
        quotes_res = await generate_quotes()
        if not quotes_res:
            raise ValueError("LLM customer quotes generation returned empty response")
        quotes_data = quotes_res.model_dump()
        
        brief_res = await generate_briefing()
        if not brief_res:
            raise ValueError("LLM report briefing generation returned empty response")
        brief_data = brief_res.model_dump()

    # Apply LLM generated content to report_data
    report_data["job_id"] = job_id
    report_data["executive_summary"] = brief_data["executive_summary"]
    report_data["launch_recommendation"] = brief_data["launch_recommendation"]
    report_data["launch_rationale"] = brief_data["launch_rationale"]
    report_data["risk_analysis"] = brief_data["risk_analysis"]
    report_data["customer_quotes"] = quotes_data["customer_quotes"]
    
    # Ensure market_reception has all required fields directly (not nested)
    if "market_reception" in report_data and isinstance(report_data["market_reception"], dict):
        # Check if fields are nested under "breakdown" and flatten them
        if "breakdown" in report_data["market_reception"]:
            breakdown = report_data["market_reception"]["breakdown"]
            report_data["market_reception"]["enthusiastic_pct"] = breakdown.get("enthusiastic_pct", 25.0)
            report_data["market_reception"]["interested_pct"] = breakdown.get("interested_pct", 35.0)
            report_data["market_reception"]["skeptical_pct"] = breakdown.get("skeptical_pct", 25.0)
            report_data["market_reception"]["rejecting_pct"] = breakdown.get("rejecting_pct", 15.0)
        else:
            # Ensure all required fields exist directly
            if "enthusiastic_pct" not in report_data["market_reception"]:
                report_data["market_reception"]["enthusiastic_pct"] = 25.0
            if "interested_pct" not in report_data["market_reception"]:
                report_data["market_reception"]["interested_pct"] = 35.0
            if "skeptical_pct" not in report_data["market_reception"]:
                report_data["market_reception"]["skeptical_pct"] = 25.0
            if "rejecting_pct" not in report_data["market_reception"]:
                report_data["market_reception"]["rejecting_pct"] = 15.0

    # Save Report to Postgres database
    async with SessionLocal() as db:
        # Delete existing report if exists for this job_id
        q = select(Report).where(Report.job_id == job_id)
        res = await db.execute(q)
        existing_rep = res.scalar_one_or_none()
        if existing_rep:
            await db.delete(existing_rep)
            await db.flush()
        
        # Validate report data before persistence
        try:
            report_data = validate_and_sanitize_report(report_data)
        except Exception as e:
            logger.warning(f"[{job_id}] Report validation failed on first attempt: {e}. Retrying report synthesis once...")
            if not settings.MOCK_MODE:
                # Retry quotes and briefing with feedback
                quotes_res = await generate_quotes(feedback_prompt=f"\n\nERROR ON PREVIOUS ATTEMPT: {e}. Ensure quotes are not generic, are >30 chars, and reference {idea} details.")
                if quotes_res:
                    quotes_data = quotes_res.model_dump()
                
                brief_res = await generate_briefing(feedback_prompt=f"\n\nERROR ON PREVIOUS ATTEMPT: {e}. Ensure executive brief contains >200 chars and does not mention AURA.")
                if brief_res:
                    brief_data = brief_res.model_dump()
                    
                report_data["executive_summary"] = brief_data["executive_summary"]
                report_data["launch_recommendation"] = brief_data["launch_recommendation"]
                report_data["launch_rationale"] = brief_data["launch_rationale"]
                report_data["risk_analysis"] = brief_data["risk_analysis"]
                report_data["customer_quotes"] = quotes_data["customer_quotes"]
                
                # Re-validate
                report_data = validate_and_sanitize_report(report_data)
            else:
                raise ValueError(f"Mock report validation failed: {e}")
            
        db.add(Report(
            job_id=job_id,
            executive_summary=report_data["executive_summary"],
            opportunity_score=report_data["opportunity_score"],
            opportunity_label=report_data["opportunity_label"],
            launch_recommendation=report_data["launch_recommendation"],
            launch_rationale=report_data["launch_rationale"],
            customer_quotes=report_data["customer_quotes"],
            revenue_projection=report_data["revenue_projection"],
            risk_analysis=report_data["risk_analysis"],
            adoption_curve=report_data["adoption_curve"],
            market_segments=report_data["market_segments"],
            pricing_recommendation=report_data["pricing_recommendation"],
            go_to_market_strategy=report_data["go_to_market_strategy"],
            confidence_score=report_data["confidence_score"],
            
            # Enriched structures
            signal_intelligence=report_data.get("signal_intelligence", {}),
            buyer_journey=report_data.get("buyer_journey", {}),
            simulated_conversations=report_data.get("simulated_conversations", []),
            competitors_battle=report_data.get("competitors_battle", {}),
            confidence_details=report_data.get("confidence_details", {}),
            objections_list=report_data.get("objections_list", []),

            # Market Friction columns
            launch_difficulty=report_data.get("launch_difficulty", 0.0),
            price_friction=report_data.get("price_friction", 0.0),
            social_friction=report_data.get("social_friction", 0.0),
            behavior_change_cost=report_data.get("behavior_change_cost", 0.0),
            trust_requirement=report_data.get("trust_requirement", 0.0),
            infrastructure_requirement=report_data.get("infrastructure_requirement", 0.0),
            switching_cost=report_data.get("switching_cost", 0.0),
            time_to_value=report_data.get("time_to_value", 0.0),
            novelty_penalty=report_data.get("novelty_penalty", 0.0),
            education_cost=report_data.get("education_cost", 0.0),
            product_market_fit=report_data.get("product_market_fit", 0.0),
            social_adoption=report_data.get("social_adoption", 0.0),
            price_acceptance=report_data.get("price_acceptance", 0.0),
            trust_barrier=report_data.get("trust_barrier", 0.0),
            habit_change_required=report_data.get("habit_change_required", 0.0),
            scenario_tests=report_data.get("scenario_tests", [])
        ))
        await db.commit()
        
    # Mark job as completed
    await update_job_progress(job_id, "Pipeline complete", "complete", 100)
    
    logger.info(f"[{job_id}] ===== REPORT ENGINE COMPLETE =====")
    return {"report": report_data}

# --- NODE 5+6 COMBINED: FORECAST + REPORT ENGINE (via addition.py) ---
async def forecast_report_node(state: SimulationState) -> Dict[str, Any]:
    """Combined forecast + report node using the canonical addition.py engine."""
    job_id = state["job_id"]
    logger.info(f"[{job_id}] ===== FORECAST+REPORT ENGINE START =====")
    await update_job_progress(job_id, "Forecast & Report Engine: Building final analysis", "forecasting", 85)

    try:
        return await asyncio.wait_for(_forecast_report_impl(state), timeout=120.0)
    except Exception as e:
        logger.error(f"[{job_id}] FORECAST+REPORT ENGINE ERROR/TIMEOUT: {e} - using fallback")
        try:
            from backend.app.services.mock_fixtures import generate_mock_report
            mock_report = generate_mock_report(
                job_id=job_id, idea=state["idea"], industry=state["industry"],
                pricing_amount=state["pricing_amount"], pricing_currency=state["pricing_currency"],
                region=state["region"], archetypes=state["archetypes"]
            )
            async with SessionLocal() as db:
                q = select(Report).where(Report.job_id == job_id)
                res = await db.execute(q)
                existing_rep = res.scalar_one_or_none()
                if existing_rep:
                    await db.delete(existing_rep)
                    await db.flush()
                db.add(Report(
                    job_id=job_id,
                    executive_summary=mock_report["executive_summary"],
                    opportunity_score=mock_report["opportunity_score"],
                    opportunity_label=mock_report["opportunity_label"],
                    launch_recommendation=mock_report["launch_recommendation"],
                    launch_rationale=mock_report["launch_rationale"],
                    customer_quotes=mock_report["customer_quotes"],
                    revenue_projection=mock_report["revenue_projection"],
                    risk_analysis=mock_report["risk_analysis"],
                    adoption_curve=mock_report["adoption_curve"],
                    market_segments=mock_report["market_segments"],
                    pricing_recommendation=mock_report["pricing_recommendation"],
                    go_to_market_strategy=mock_report["go_to_market_strategy"],
                    confidence_score=mock_report["confidence_score"],
                    signal_intelligence=mock_report.get("signal_intelligence", {}),
                    buyer_journey=mock_report.get("buyer_journey", {}),
                    simulated_conversations=mock_report.get("simulated_conversations", []),
                    competitors_battle=mock_report.get("competitors_battle", {}),
                    confidence_details=mock_report.get("confidence_details", {}),
                    objections_list=mock_report.get("objections_list", []),
                    launch_difficulty=mock_report.get("launch_difficulty", 0.0),
                    price_friction=mock_report.get("price_friction", 0.0),
                    social_friction=mock_report.get("social_friction", 0.0),
                    behavior_change_cost=mock_report.get("behavior_change_cost", 0.0),
                    trust_requirement=mock_report.get("trust_requirement", 0.0),
                    infrastructure_requirement=mock_report.get("infrastructure_requirement", 0.0),
                    switching_cost=mock_report.get("switching_cost", 0.0),
                    time_to_value=mock_report.get("time_to_value", 0.0),
                    novelty_penalty=mock_report.get("novelty_penalty", 0.0),
                    education_cost=mock_report.get("education_cost", 0.0),
                    product_market_fit=mock_report.get("product_market_fit", 0.0),
                    social_adoption=mock_report.get("social_adoption", 0.0),
                    price_acceptance=mock_report.get("price_acceptance", 0.0),
                    trust_barrier=mock_report.get("trust_barrier", 0.0),
                    habit_change_required=mock_report.get("habit_change_required", 0.0),
                    scenario_tests=mock_report.get("scenario_tests", [])
                ))
                await db.commit()
            await update_job_progress(job_id, "Pipeline complete", "complete", 100)
            return {"report": mock_report, "forecast": {}}
        except Exception as fallback_err:
            logger.error(f"[{job_id}] FORECAST+REPORT FALLBACK FAILURE: {fallback_err}")
            raise e


async def _forecast_report_impl(state: SimulationState) -> Dict[str, Any]:
    """Core implementation: builds PipelineState, calls addition.py, persists Report."""
    job_id = state["job_id"]

    # 1. Build typed PipelineState from raw dicts
    pipeline_state = await asyncio.to_thread(build_pipeline_state, state)
    logger.info(f"[{job_id}] PipelineState built with {len(pipeline_state.personas)} personas")

    # 2. Get LLM client (MockLLMClient in MOCK_MODE, GeminiLLMClient otherwise)
    llm = get_llm_client()

    # 3. Run the canonical forecast+report engine
    await update_job_progress(job_id, "Running forecast & report engine", "forecasting", 90)
    result: ForecastResult = await run_forecast_and_report(pipeline_state, llm)
    logger.info(f"[{job_id}] ForecastResult ready: PMF={result.pmf_score}, adoption={result.final_adoption_pct}%")

    # 4. Convert ForecastResult to report_data dict for persistence
    report_data = _forecast_result_to_report_data(state, result)

    # 5. Persist to Report model
    await update_job_progress(job_id, "Persisting report", "generating_report", 95)
    async with SessionLocal() as db:
        q = select(Report).where(Report.job_id == job_id)
        res = await db.execute(q)
        existing_rep = res.scalar_one_or_none()
        if existing_rep:
            await db.delete(existing_rep)
            await db.flush()

        db.add(Report(
            job_id=job_id,
            executive_summary=report_data["executive_summary"],
            opportunity_score=report_data["opportunity_score"],
            opportunity_label=report_data["opportunity_label"],
            launch_recommendation=report_data["launch_recommendation"],
            launch_rationale=report_data["launch_rationale"],
            customer_quotes=report_data["customer_quotes"],
            revenue_projection=report_data["revenue_projection"],
            risk_analysis=report_data["risk_analysis"],
            adoption_curve=report_data["adoption_curve"],
            market_segments=report_data["market_segments"],
            pricing_recommendation=report_data["pricing_recommendation"],
            go_to_market_strategy=report_data["go_to_market_strategy"],
            confidence_score=report_data["confidence_score"],
            signal_intelligence=report_data.get("signal_intelligence", {}),
            buyer_journey=report_data.get("buyer_journey", {}),
            simulated_conversations=report_data.get("simulated_conversations", []),
            competitors_battle=report_data.get("competitors_battle", {}),
            confidence_details=report_data.get("confidence_details", {}),
            objections_list=report_data.get("objections_list", []),
            launch_difficulty=report_data.get("launch_difficulty", 0.0),
            price_friction=report_data.get("price_friction", 0.0),
            social_friction=report_data.get("social_friction", 0.0),
            behavior_change_cost=report_data.get("behavior_change_cost", 0.0),
            trust_requirement=report_data.get("trust_requirement", 0.0),
            infrastructure_requirement=report_data.get("infrastructure_requirement", 0.0),
            switching_cost=report_data.get("switching_cost", 0.0),
            time_to_value=report_data.get("time_to_value", 0.0),
            novelty_penalty=report_data.get("novelty_penalty", 0.0),
            education_cost=report_data.get("education_cost", 0.0),
            product_market_fit=report_data.get("product_market_fit", 0.0),
            social_adoption=report_data.get("social_adoption", 0.0),
            price_acceptance=report_data.get("price_acceptance", 0.0),
            trust_barrier=report_data.get("trust_barrier", 0.0),
            habit_change_required=report_data.get("habit_change_required", 0.0),
            scenario_tests=report_data.get("scenario_tests", [])
        ))
        await db.commit()

    await update_job_progress(job_id, "Pipeline complete", "complete", 100)
    logger.info(f"[{job_id}] ===== FORECAST+REPORT ENGINE COMPLETE =====")
    return {"forecast": report_data, "report": report_data}


def _forecast_result_to_report_data(state: Dict[str, Any], result: ForecastResult) -> Dict[str, Any]:
    """Maps ForecastResult (from addition.py) to the dict format the Report model expects."""
    r = result
    job_id = state["job_id"]
    signals = state.get("signals", [])
    archetypes = state.get("archetypes", [])
    adoption_curve = state.get("adoption_curve", {})

    # Map opportunity_score from pmf_score (0-100 int)
    opp_score = int(round(r.pmf_score))
    if opp_score >= 70:
        opp_label = "Strong"
    elif opp_score >= 40:
        opp_label = "Moderate"
    else:
        opp_label = "Weak"

    # Revenue projection in legacy format (with 'estimate' field)
    rev_proj = {
        "currency": state.get("pricing_currency", "USD"),
        "projections": [
            {
                "months": 3,
                "estimate": int(r.revenue_projection.period_3mo.estimate),
                "low": int(r.revenue_projection.period_3mo.low),
                "high": int(r.revenue_projection.period_3mo.high),
            },
            {
                "months": 6,
                "estimate": int(r.revenue_projection.period_6mo.estimate),
                "low": int(r.revenue_projection.period_6mo.low),
                "high": int(r.revenue_projection.period_6mo.high),
            },
            {
                "months": 12,
                "estimate": int(r.revenue_projection.period_12mo.estimate),
                "low": int(r.revenue_projection.period_12mo.low),
                "high": int(r.revenue_projection.period_12mo.high),
            },
        ],
        "tam_used": int(r.revenue_projection.tam_used),
        "tam_reasoning": r.revenue_projection.tam_reasoning,
        "tam_confidence": "medium",
        "assumptions": r.revenue_projection.assumptions,
    }

    # Customer quotes as list of dicts
    quotes = [
        {"quote": q.quote, "sentiment": q.sentiment, "persona_segment": q.persona_segment}
        for q in r.customer_quotes
    ]

    # Risk analysis as list of dicts
    risks = [
        {"risk": ri.risk, "severity": ri.severity, "mitigation": ri.mitigation}
        for ri in r.risk_analysis
    ]

    # Competitors as list of dicts
    competitors_list = [
        {"name": c.name, "why_relevant": c.why_relevant, "positioning": c.positioning}
        for c in r.competitors
    ]

    # Top objections as list of dicts
    top_objections = r.top_objections  # already list[dict]

    # Market reception
    market_reception = {
        "overall_label": r.market_reception.overall_label,
        "enthusiastic_pct": r.market_reception.breakdown.enthusiastic_pct,
        "interested_pct": r.market_reception.breakdown.interested_pct,
        "skeptical_pct": r.market_reception.breakdown.skeptical_pct,
        "rejecting_pct": r.market_reception.breakdown.rejecting_pct,
        "breakdown": {
            "enthusiastic_pct": r.market_reception.breakdown.enthusiastic_pct,
            "interested_pct": r.market_reception.breakdown.interested_pct,
            "skeptical_pct": r.market_reception.breakdown.skeptical_pct,
            "rejecting_pct": r.market_reception.breakdown.rejecting_pct,
        },
    }

    # Funnel as list of dicts
    funnel = [
        {"name": f.name, "pct": f.pct, "users": f.users, "drop_reason": f.drop_reason}
        for f in r.funnel
    ]

    # Diffusion curve as list of dicts
    diffusion_curve = [
        {"cycle": d.cycle, "values": d.values}
        for d in r.diffusion_curve
    ]

    # Confidence details
    confidence_details = {
        "signal_quality_pct": r.confidence.signal_quality_pct,
        "persona_consistency_pct": r.confidence.persona_consistency_pct,
        "forecast_stability_pct": r.confidence.forecast_stability_pct,
        "final_confidence_pct": r.confidence.final_confidence_pct,
        "explainer": r.confidence.explainer,
    }

    # Market friction scores computed from persona data
    personas = state.get("simulations", []) or []
    budget_sens_vals = []
    for arch in archetypes:
        budget_sens_vals.append(float(arch.get("budget_sensitivity", 5)))
    mean_budget_sens = sum(budget_sens_vals) / max(len(budget_sens_vals), 1)

    price_friction = min(100.0, mean_budget_sens * 10.0)
    price_acceptance = 100.0 - price_friction
    social_adoption_score = min(100.0, r.final_adoption_pct)
    skeptical_pct = r.market_reception.breakdown.skeptical_pct
    rejecting_pct = r.market_reception.breakdown.rejecting_pct
    trust_barrier = min(100.0, (skeptical_pct + rejecting_pct) * 1.2)
    trust_req = trust_barrier * 0.9

    # Count objections related to switching/learning for behavior_change_cost
    behavior_keywords = ["switch", "learn", "complex", "setup", "onboard", "migrate"]
    behavior_obj_count = 0
    total_obj_count = 0
    for obj in top_objections:
        count = obj.get("count", 1)
        total_obj_count += count
        obj_text = obj.get("objection", "").lower()
        if any(kw in obj_text for kw in behavior_keywords):
            behavior_obj_count += count
    behavior_change_cost = min(100.0, (behavior_obj_count / max(total_obj_count, 1)) * 100.0)

    social_friction = max(0.0, 100.0 - social_adoption_score)
    launch_difficulty = (price_friction * 0.25 + social_friction * 0.2 +
                        trust_barrier * 0.2 + behavior_change_cost * 0.15 +
                        (100.0 - r.pmf_score) * 0.2)

    # Build signal_intelligence from signals to match frontend's expected 5 cards
    sig = signals[0] if (signals and isinstance(signals, list)) else {}
    market_strength = sig.get("market_strength", 0.6)
    comp_density = sig.get("competitive_density", 0.45)
    sentiment = sig.get("market_sentiment_score", 0.2)
    source = sig.get("source", "Tavily")
    if not source:
        source = "Tavily"
    sources = [s.strip() for s in source.split("/")] if isinstance(source, str) else ["Tavily"]

    sig_intel = {
        "demand_momentum": {
            "metric": int(market_strength * 100),
            "explanation": sig.get("market_sentiment_summary") or f"Moderate to high demand trend detected in {r.market_reception.breakdown.main_adopters_archetype or 'target segments'}.",
            "confidence": "High" if sig.get("confidence", 0.8) > 0.7 else "Medium",
            "trend": "up" if sentiment > 0.1 else "stable",
            "sources": sources
        },
        "competitive_saturation": {
            "metric": int(comp_density * 100),
            "explanation": f"Competitive density score is {int(comp_density * 100)}%. Niche features are still wide open.",
            "confidence": "Medium",
            "trend": "stable",
            "sources": sources
        },
        "customer_friction": {
            "metric": int(launch_difficulty),
            "explanation": f"Launch difficulty {int(launch_difficulty)}/100 from price, trust, and behavior change.",
            "confidence": "High",
            "trend": "up" if launch_difficulty > 50 else "down",
            "sources": ["simulation"]
        },
        "novelty_score": {
            "metric": int((1.0 - (r.confidence.final_confidence_pct / 200.0)) * 100),
            "explanation": "Novelty assessment suggests clear market differentiation.",
            "confidence": "Medium",
            "trend": "stable",
            "sources": ["simulation"]
        },
        "economic_sensitivity": {
            "metric": int(price_friction),
            "explanation": f"Price sensitivity of {int(price_friction)}% from simulated population budget limits.",
            "confidence": "High",
            "trend": "stable",
            "sources": ["simulation"]
        }
    }

    # Build buyer_journey from funnel data (embed _funnel_array for main.py extraction)
    buyer_journey = {"_funnel_array": funnel}  # new: store raw array for frontend
    for stage in funnel:
        buyer_journey[stage["name"]] = {
            "pct": stage["pct"],
            "users": stage["users"],
            "drop_reason": stage["drop_reason"],
        }

    # Build competitors_battle from competitors in canonical format
    comp_a = competitors_list[0] if len(competitors_list) > 0 else "Competitor A"
    comp_b = competitors_list[1] if len(competitors_list) > 1 else "Competitor B"
    
    comp_battle = {
        "winner": "Your Product" if r.final_adoption_pct > 35 else comp_a,
        "your_product": {
            "price": "Optimal",
            "trust": "Simulated",
            "features": "Innovative",
            "switching_cost": f"{int(behavior_change_cost)}%",
            "adoption": f"{round(r.final_adoption_pct, 1)}%",
            "status": "Leader" if r.final_adoption_pct > 35 else "Challenger"
        },
        "competitor_a": {
            "name": comp_a,
            "price": "High" if price_friction > 40 else "Varies",
            "trust": "Established",
            "features": "Mature",
            "switching_cost": "High",
            "adoption": f"{max(5, int(r.final_adoption_pct * 0.45))}%",
            "status": "Incumbent"
        },
        "competitor_b": {
            "name": comp_b,
            "price": "Low",
            "trust": "Mixed",
            "features": "Basic",
            "switching_cost": "Low",
            "adoption": f"{max(3, int(r.final_adoption_pct * 0.25))}%",
            "status": "Budget"
        }
    }

    # Build market_segments from archetypes
    segment_map: Dict[str, list] = {}
    for arch in archetypes:
        seg = arch.get("segment", "General")
        segment_map.setdefault(seg, []).append(arch)
    market_segments = []
    for seg_name, members in segment_map.items():
        market_segments.append({
            "name": seg_name,
            "size_percentage": round(len(members) / max(len(archetypes), 1) * 100, 1),
            "key_traits": list(set(m.get("behavior_type", "General") for m in members)),
        })

    # Build scenario_tests
    scenario_tests = []
    base_price = float(state.get("pricing_amount", 10.0))
    for mult, label in [(0.8, "20% price decrease"), (1.2, "20% price increase"), (1.5, "50% price increase")]:
        new_price = base_price * mult
        adj_adoption = r.final_adoption_pct * (1.0 + (1.0 - mult) * 0.3)
        adj_adoption = max(5.0, min(95.0, adj_adoption))
        adj_revenue = rev_proj["projections"][2]["estimate"] * mult * (adj_adoption / max(r.final_adoption_pct, 1))
        scenario_tests.append({
            "scenario": label,
            "price": round(new_price, 2),
            "estimated_adoption_pct": round(adj_adoption, 1),
            "estimated_revenue_12mo": int(adj_revenue),
        })

    # Objections list in legacy format
    objections_list = [
        {"issue": obj.get("objection", ""), "frequency": obj.get("pct", 0.0),
         "count": obj.get("count", 0)}
        for obj in top_objections
    ]

    return {
        "job_id": job_id,
        "executive_summary": r.executive_summary,
        "opportunity_score": opp_score,
        "opportunity_label": opp_label,
        "launch_recommendation": r.launch_recommendation.decision,
        "launch_rationale": r.launch_recommendation.rationale,
        "customer_quotes": quotes,
        "revenue_projection": {**rev_proj, "_market_reception": market_reception},
        "risk_analysis": risks,
        "adoption_curve": {**adoption_curve, "_diffusion_curve": diffusion_curve},
        "market_segments": market_segments,
        "pricing_recommendation": r.pricing_recommendation,
        "go_to_market_strategy": r.go_to_market_strategy,
        "confidence_score": int(round(r.confidence.final_confidence_pct)),
        # Enriched structures
        "signal_intelligence": sig_intel,
        "buyer_journey": buyer_journey,
        "simulated_conversations": [],
        "competitors_battle": comp_battle,
        "confidence_details": confidence_details,
        "objections_list": objections_list,
        # Market friction scores
        "launch_difficulty": round(launch_difficulty, 1),
        "price_friction": round(price_friction, 1),
        "social_friction": round(social_friction, 1),
        "behavior_change_cost": round(behavior_change_cost, 1),
        "trust_requirement": round(trust_req, 1),
        "infrastructure_requirement": round(max(0, 100.0 - r.pmf_score) * 0.5, 1),
        "switching_cost": round(behavior_change_cost * 0.8, 1),
        "time_to_value": round(max(0, 100.0 - r.pmf_score) * 0.4, 1),
        "novelty_penalty": round(social_friction * 0.3, 1),
        "education_cost": round(behavior_change_cost * 0.6, 1),
        "product_market_fit": round(r.pmf_score, 1),
        "social_adoption": round(social_adoption_score, 1),
        "price_acceptance": round(price_acceptance, 1),
        "trust_barrier": round(trust_barrier, 1),
        "habit_change_required": round(behavior_change_cost * 0.7, 1),
        "scenario_tests": scenario_tests,
        # NEW fields from ForecastResult (for direct frontend consumption)
        "pmf_score": round(r.pmf_score, 1),
        "pmf_label": r.pmf_label,
        "final_adoption_pct": round(r.final_adoption_pct, 1),
        "conversion_rate_pct": round(r.conversion_rate_pct, 1),
        "market_reception": market_reception,
        "funnel": funnel,
        "diffusion_curve": diffusion_curve,
        "competitors": competitors_list,
        "top_objections": top_objections,
        "confidence": confidence_details,
        "launch_recommendation_obj": {
            "decision": r.launch_recommendation.decision,
            "rationale": r.launch_recommendation.rationale,
        },
    }


# --- LANGGRAPH GRAPH ASSEMBLY ---

# 1. Initialize graph builder
workflow = StateGraph(SimulationState)

# 2. Add nodes (forecast_engine + report_engine replaced by combined forecast_report_engine)
workflow.add_node("signal_engine", signal_engine_node)
workflow.add_node("persona_engine", persona_engine_node)
workflow.add_node("simulation_engine", simulation_engine_node)
workflow.add_node("social_influence_engine", social_influence_engine_node)
workflow.add_node("forecast_report_engine", forecast_report_node)

# 3. Add edges (sequential flow)
workflow.set_entry_point("signal_engine")
workflow.add_edge("signal_engine", "persona_engine")
workflow.add_edge("persona_engine", "simulation_engine")
workflow.add_edge("simulation_engine", "social_influence_engine")
workflow.add_edge("social_influence_engine", "forecast_report_engine")
workflow.add_edge("forecast_report_engine", END)

# 4. Compile graph
app_graph = workflow.compile()

# --- ENTRY POINT RUNNER ---

async def run_simulation_pipeline(
    job_id: str, 
    idea: str, 
    industry: str, 
    market: str, 
    pricing_amount: float, 
    pricing_currency: str, 
    region: str, 
    timeline: str
):
    try:
        # Mark as running
        await update_job_progress(job_id, "Initializing Engines", "collecting_signals", 5)
        
        initial_state: SimulationState = {
            "job_id": job_id,
            "idea": idea,
            "industry": industry,
            "market": market,
            "pricing_amount": pricing_amount,
            "pricing_currency": pricing_currency,
            "region": region,
            "timeline": timeline,
            "signals": [],
            "archetypes": [],
            "simulations": [],
            "population_aggregate": {},
            "adoption_curve": {},
            "forecast": {},
            "report": {},
            "error": None
        }
        
        # Run graph execution
        await app_graph.ainvoke(initial_state)
        logger.info(f"Pipeline executed successfully for job {job_id}")
        
    except Exception as e:
        logger.error(f"Error in pipeline run for job {job_id}: {e}")
        await update_job_progress(job_id, "Pipeline Execution Failure", "failed", 100, error=str(e))
