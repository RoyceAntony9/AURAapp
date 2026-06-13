"""

aura_forecast_report.py



Canonical Forecast + Report Engine for AURA.

Single source of truth for: pmf_score, final_adoption_pct, confidence_score,

revenue_projection, conversion_rate, market_reception, competitors,

customer_quotes, executive_summary, launch_recommendation, funnel.



Drop-in module: call run_forecast_and_report(...) after simulation +

social influence stages complete. Returns a fully-populated, NaN-free

ForecastResult ready to persist and serve via /simulate/{job_id}/result.

"""



from __future__ import annotations

import json

import math

import logging

from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator



logger = logging.getLogger("aura.forecast")



# ──────────────────────────────────────────────────────────────────────────

# 1. INPUT CONTRACTS — what this module expects from upstream stages

# ──────────────────────────────────────────────────────────────────────────



class PersonaResult(BaseModel):

    """One expanded persona's simulation outcome. Length must be > 0."""

    persona_id: str

    segment: str

    age: int

    income_bracket: str

    occupation: str

    would_buy: bool

    excitement_score: float          # 0-10

    likelihood_score: float          # 0-1

    objections: list[str]

    reasoning: str

    budget_sensitivity: float        # 0-10

    risk_tolerance: Literal["low", "medium", "high"]





class SocialInfluenceCycle(BaseModel):

    """Snapshot after each diffusion cycle."""

    cycle: int                       # 0-5

    segment_adoption: dict[str, float]   # segment_name -> adoption fraction (0-1)

    overall_adoption: float          # 0-1, fraction of all personas would_buy at this cycle





class SignalData(BaseModel):

    complaints: list[str] = Field(default_factory=list)

    demands: list[str] = Field(default_factory=list)

    competitors_raw: list[str] = Field(default_factory=list)

    market_sentiment_score: float = 0.0   # -1 to 1

    market_sentiment_summary: str = ""

    sources_used: list[str] = Field(default_factory=list)   # e.g. ["reddit","news"] or ["synthetic"]

    is_synthetic_fallback: bool = False





class SimulationInput(BaseModel):

    """Original user request, needed for grounding all LLM generations."""

    idea: str

    industry: str

    target_market: str

    price_amount: float

    price_currency: str = "USD"

    region: str

    timeline: str





class PipelineState(BaseModel):

    """Everything the forecast/report stage receives."""

    job_id: str

    sim_input: SimulationInput

    signals: SignalData

    personas: list[PersonaResult]            # the FULL expanded set (e.g. 5000)

    influence_cycles: list[SocialInfluenceCycle]  # length 6 (cycle 0..5)





# ──────────────────────────────────────────────────────────────────────────

# 2. OUTPUT CONTRACT — single source of truth, NaN-impossible by construction

# ──────────────────────────────────────────────────────────────────────────



class RevenuePeriod(BaseModel):

    estimate: float

    low: float

    high: float





class RevenueProjection(BaseModel):

    period_3mo: RevenuePeriod

    period_6mo: RevenuePeriod

    period_12mo: RevenuePeriod

    tam_used: float

    tam_reasoning: str

    assumptions: list[str]





class MarketReceptionBreakdown(BaseModel):

    enthusiastic_pct: float

    interested_pct: float

    skeptical_pct: float

    rejecting_pct: float



    @field_validator("*")

    @classmethod

    def must_be_finite(cls, v):

        if not math.isfinite(v):

            raise ValueError(f"Non-finite value in MarketReceptionBreakdown: {v}")

        return v





class MarketReception(BaseModel):

    overall_label: Literal["Positive", "Mixed", "Negative", "Skeptical"]

    breakdown: MarketReceptionBreakdown





class FunnelStage(BaseModel):

    name: str

    pct: float

    users: int

    drop_reason: str





class Competitor(BaseModel):

    name: str

    why_relevant: str

    positioning: str





class CustomerQuote(BaseModel):

    quote: str

    sentiment: Literal["positive", "mixed", "negative"]

    persona_segment: str





class RiskItem(BaseModel):

    risk: str

    severity: Literal["low", "medium", "high"]

    mitigation: str





class LaunchRecommendation(BaseModel):

    decision: Literal["Launch", "Pivot", "Delay", "Kill"]

    rationale: str





class DiffusionCyclePoint(BaseModel):

    """One row for the diffusion curve chart."""

    cycle: int

    values: dict[str, float]   # segment_name -> adoption_pct (0-100)





class ConfidenceBreakdown(BaseModel):

    signal_quality_pct: float

    persona_consistency_pct: float

    forecast_stability_pct: float

    final_confidence_pct: float

    explainer: str





class ForecastResult(BaseModel):

    """

    THE canonical object. Every field guaranteed finite / non-empty.

    This is what gets persisted and returned by /simulate/{job_id}/result.

    """

    job_id: str



    # Core single-source-of-truth metrics

    pmf_score: float

    pmf_label: Literal["Weak Fit", "Moderate Fit", "Strong Fit"]

    final_adoption_pct: float

    confidence: ConfidenceBreakdown

    conversion_rate_pct: float



    # Revenue

    revenue_projection: RevenueProjection



    # Reception & funnel

    market_reception: MarketReception

    funnel: list[FunnelStage]



    # Diffusion chart data

    diffusion_curve: list[DiffusionCyclePoint]



    # Competitors

    competitors: list[Competitor]



    # Top objections

    top_objections: list[dict]   # {objection: str, pct: float, count: int}



    # Narrative content

    customer_quotes: list[CustomerQuote]

    executive_summary: str

    launch_recommendation: LaunchRecommendation

    risk_analysis: list[RiskItem]

    pricing_recommendation: str

    go_to_market_strategy: list[str]



    @field_validator(

        "pmf_score", "final_adoption_pct", "conversion_rate_pct"

    )

    @classmethod

    def must_be_finite(cls, v):

        if not math.isfinite(v):

            raise ValueError(f"Non-finite core metric: {v}")

        return v





# ──────────────────────────────────────────────────────────────────────────

# 3. CONSTANTS — named, not magic numbers

# ──────────────────────────────────────────────────────────────────────────



PERIOD_RAMP_FACTORS = {

    "3mo": 0.25,

    "6mo": 0.60,

    "12mo": 1.00,

}



# Cycle index used for each revenue period (cycles run 0..5)

PERIOD_CYCLE_MAP = {

    "3mo": 1,

    "6mo": 3,

    "12mo": 5,

}



RETENTION_RATE_LABEL = "Industry benchmark: 82% (not derived from this simulation)"

RETENTION_RATE_VALUE = 0.82



EXCITEMENT_BUCKETS = {

    "enthusiastic": (8.0, 10.0001),

    "interested": (5.0, 8.0),

    "skeptical": (2.0, 5.0),

    "rejecting": (-0.0001, 2.0),

}



PMF_BANDS = [

    (0, 40, "Weak Fit"),

    (40, 70, "Moderate Fit"),

    (70, 101, "Strong Fit"),

]



FUNNEL_STAGE_DEFINITIONS = [

    # (name, predicate over a PersonaResult, drop_reason)

    "Awareness",

    "Interest",

    "Evaluation",

    "Trial",

    "Purchase",

    "Retention",

]





# ──────────────────────────────────────────────────────────────────────────

# 4. PURE NUMERICAL CALCULATIONS — no LLM, fully deterministic, NaN-proof

# ──────────────────────────────────────────────────────────────────────────



def _safe_mean(values: list[float], default: float = 0.0) -> float:

    """Mean that never produces NaN. Empty input is a BUG — log it loudly."""

    if not values:

        logger.error(

            "_safe_mean called with empty list — upstream data is missing. "

            "Returning default=%s but THIS IS A BUG, not expected behavior.",

            default,

        )

        return default

    return sum(values) / len(values)





def _safe_pct(numerator: float, denominator: float, default: float = 0.0) -> float:

    """Percentage that never produces NaN/inf."""

    if denominator == 0:

        logger.error(

            "_safe_pct called with denominator=0 (numerator=%s) — "

            "upstream persona population is empty. This is a BUG.",

            numerator,

        )

        return default

    return (numerator / denominator) * 100.0





def compute_final_adoption_pct(personas: list[PersonaResult]) -> float:

    """

    Final adoption % = fraction of expanded personas with would_buy=True,

    AFTER social-influence adjustment has been applied to their would_buy

    flags by the simulation/social-influence stage.

    """

    if not personas:

        raise ValueError(

            "compute_final_adoption_pct: personas list is EMPTY. "

            "Persona expansion must complete before forecast runs. "

            "This is the #1 cause of NaN — fix the pipeline ordering/await."

        )

    buyers = sum(1 for p in personas if p.would_buy)

    return _safe_pct(buyers, len(personas))





def compute_market_reception(personas: list[PersonaResult]) -> MarketReception:

    if not personas:

        raise ValueError("compute_market_reception: personas list is EMPTY.")



    total = len(personas)

    counts = {k: 0 for k in EXCITEMENT_BUCKETS}

    for p in personas:

        for label, (lo, hi) in EXCITEMENT_BUCKETS.items():

            if lo <= p.excitement_score < hi:

                counts[label] += 1

                break



    breakdown = MarketReceptionBreakdown(

        enthusiastic_pct=_safe_pct(counts["enthusiastic"], total),

        interested_pct=_safe_pct(counts["interested"], total),

        skeptical_pct=_safe_pct(counts["skeptical"], total),

        rejecting_pct=_safe_pct(counts["rejecting"], total),

    )



    buy_ratio = _safe_pct(sum(1 for p in personas if p.would_buy), total) / 100.0



    # Determine label: plurality bucket + buy ratio sanity check

    pcts = {

        "enthusiastic": breakdown.enthusiastic_pct,

        "interested": breakdown.interested_pct,

        "skeptical": breakdown.skeptical_pct,

        "rejecting": breakdown.rejecting_pct,

    }

    plurality = max(pcts, key=pcts.get)



    if plurality in ("enthusiastic", "interested") and buy_ratio >= 0.4:

        label = "Positive"

    elif plurality == "rejecting" or buy_ratio < 0.15:

        label = "Negative"

    elif plurality == "skeptical":

        label = "Skeptical"

    else:

        label = "Mixed"



    return MarketReception(overall_label=label, breakdown=breakdown)





def compute_top_objections(personas: list[PersonaResult], top_n: int = 5) -> list[dict]:

    if not personas:

        raise ValueError("compute_top_objections: personas list is EMPTY.")



    counter: dict[str, int] = {}

    for p in personas:

        for obj in p.objections:

            key = obj.strip()

            if key:

                counter[key] = counter.get(key, 0) + 1



    total = len(personas)

    ranked = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:top_n]



    if not ranked:

        # Genuinely no objections recorded — this is suspicious but not NaN-causing.

        logger.warning("compute_top_objections: no objections found across any persona.")

        return []



    return [

        {"objection": obj, "pct": round(_safe_pct(count, total), 1), "count": count}

        for obj, count in ranked

    ]





def compute_funnel(personas: list[PersonaResult]) -> list[FunnelStage]:

    """

    Funnel stages derived from real likelihood_score / would_buy distributions.

    Each stage is a STRICT SUBSET of the previous (monotonically non-increasing).

    """

    if not personas:

        raise ValueError("compute_funnel: personas list is EMPTY.")



    total = len(personas)



    # Stage 1: Awareness — everyone is "reachable" but discount by signal reach.

    # Use mean likelihood as a proxy for how findable this product category is.

    avg_likelihood = _safe_mean([p.likelihood_score for p in personas])

    awareness_pct = min(99.0, 60.0 + avg_likelihood * 35.0)  # 60-95% range, data-driven



    interest = [p for p in personas if p.likelihood_score > 0.2]

    interest_pct = _safe_pct(len(interest), total)

    interest_pct = min(interest_pct, awareness_pct)



    evaluation = [p for p in interest if p.likelihood_score > 0.4]

    evaluation_pct = _safe_pct(len(evaluation), total)

    evaluation_pct = min(evaluation_pct, interest_pct)



    trial = [p for p in evaluation if p.would_buy]

    trial_pct = _safe_pct(len(trial), total)

    trial_pct = min(trial_pct, evaluation_pct)



    purchase = [p for p in trial if p.likelihood_score > 0.6]

    purchase_pct = _safe_pct(len(purchase), total)

    purchase_pct = min(purchase_pct, trial_pct)



    retention_pct = purchase_pct * RETENTION_RATE_VALUE



    def stage(name: str, pct: float, drop_reason: str) -> FunnelStage:

        return FunnelStage(

            name=name,

            pct=round(pct, 1),

            users=int(round((pct / 100.0) * total)),

            drop_reason=drop_reason,

        )



    return [

        stage("Awareness", awareness_pct, "Limited reach in target segment"),

        stage("Interest", interest_pct, "Problem-solution fit not compelling enough for some"),

        stage("Evaluation", evaluation_pct, "Trial friction or switching cost too high"),

        stage("Trial", trial_pct, "Onboarding complexity"),

        stage("Purchase", purchase_pct, "Price or trust barriers at checkout"),

        stage("Retention", retention_pct, "Churn from unmet expectations"),

    ]





def compute_diffusion_curve(cycles: list[SocialInfluenceCycle]) -> list[DiffusionCyclePoint]:

    if not cycles:

        raise ValueError(

            "compute_diffusion_curve: influence_cycles is EMPTY. "

            "Social influence engine must persist a snapshot after EACH "

            "of cycles 0-5, not just the final result."

        )

    points = []

    for c in cycles:

        values = {seg: round(frac * 100.0, 2) for seg, frac in c.segment_adoption.items()}

        points.append(DiffusionCyclePoint(cycle=c.cycle, values=values))

    return points





def compute_pmf_score(

    personas: list[PersonaResult],

    signals: SignalData,

    final_adoption_pct: float,

) -> tuple[float, str]:

    if not personas:

        raise ValueError("compute_pmf_score: personas list is EMPTY.")



    total = len(personas)



    excitement_component = (_safe_mean([p.excitement_score for p in personas]) / 10.0) * 100.0



    intent_count = sum(

        1 for p in personas if p.would_buy and p.likelihood_score > 0.6

    )

    intent_component_pct = _safe_pct(intent_count, total)



    avg_objections = _safe_mean([float(len(p.objections)) for p in personas])

    # Normalize: assume 0-5 objections is the realistic range

    objection_severity_penalty = min(100.0, (avg_objections / 5.0) * 100.0)



    # Sentiment alignment: does simulated buy ratio agree with external sentiment?

    buy_ratio = sum(1 for p in personas if p.would_buy) / total  # 0-1

    # market_sentiment_score is -1..1 -> normalize to 0..1

    normalized_sentiment = (signals.market_sentiment_score + 1.0) / 2.0

    alignment = 1.0 - abs(buy_ratio - normalized_sentiment)  # 0..1, 1 = perfect alignment

    sentiment_alignment_bonus = alignment * 100.0



    raw = (

        0.35 * excitement_component

        + 0.35 * intent_component_pct

        - 0.15 * objection_severity_penalty

        + 0.15 * sentiment_alignment_bonus

    )

    pmf_score = max(0.0, min(100.0, raw))



    label = "Weak Fit"

    for lo, hi, name in PMF_BANDS:

        if lo <= pmf_score < hi:

            label = name

            break



    return round(pmf_score, 1), label





def compute_confidence(

    signals: SignalData,

    personas: list[PersonaResult],

    revenue_low: float,

    revenue_high: float,

    revenue_estimate: float,

) -> ConfidenceBreakdown:

    if not personas:

        raise ValueError("compute_confidence: personas list is EMPTY.")



    # Signal quality: real sources used vs synthetic fallback

    if signals.is_synthetic_fallback or not signals.sources_used:

        signal_quality_pct = 50.0  # honest middle ground for synthetic data

    else:

        signal_quality_pct = min(100.0, 60.0 + len(signals.sources_used) * 13.3)



    # Persona consistency: inverse of variance in likelihood_score

    likelihoods = [p.likelihood_score for p in personas]

    mean_l = _safe_mean(likelihoods)

    variance = _safe_mean([(l - mean_l) ** 2 for l in likelihoods])

    std_dev = math.sqrt(variance)

    # std_dev of 0 -> 100% consistency; std_dev of 0.5 (max possible for 0-1) -> 0%

    persona_consistency_pct = max(0.0, min(100.0, (1.0 - (std_dev / 0.5)) * 100.0))



    # Forecast stability: tighter range relative to estimate = higher stability

    if revenue_estimate <= 0:

        forecast_stability_pct = 30.0  # low confidence if no revenue signal at all

    else:

        spread_ratio = (revenue_high - revenue_low) / revenue_estimate  # >= 0

        forecast_stability_pct = max(0.0, min(100.0, (1.0 - spread_ratio) * 100.0))



    final_confidence_pct = round(

        0.4 * signal_quality_pct

        + 0.35 * persona_consistency_pct

        + 0.25 * forecast_stability_pct,

        1,

    )



    explainer = (

        f"Confidence reflects signal data quality ({signal_quality_pct:.0f}%, "

        f"{'real-world sources' if not signals.is_synthetic_fallback else 'synthetic fallback used'}), "

        f"consistency across simulated personas ({persona_consistency_pct:.0f}%), "

        f"and the stability of the revenue forecast range ({forecast_stability_pct:.0f}%)."

    )



    return ConfidenceBreakdown(

        signal_quality_pct=round(signal_quality_pct, 1),

        persona_consistency_pct=round(persona_consistency_pct, 1),

        forecast_stability_pct=round(forecast_stability_pct, 1),

        final_confidence_pct=final_confidence_pct,

        explainer=explainer,

    )





def compute_revenue_projection(

    sim_input: SimulationInput,

    influence_cycles: list[SocialInfluenceCycle],

    tam_estimate: float,

    tam_reasoning: str,

    confidence_pct: float,

) -> RevenueProjection:

    if not influence_cycles or len(influence_cycles) < 6:

        raise ValueError(

            f"compute_revenue_projection: expected 6 influence cycles (0-5), "

            f"got {len(influence_cycles)}. Social influence engine must "

            f"persist all 6 snapshots."

        )

    if tam_estimate <= 0:

        raise ValueError(

            f"compute_revenue_projection: tam_estimate must be > 0, got "

            f"{tam_estimate}. TAM estimation LLM call likely failed or "

            f"wasn't awaited."

        )



    price = sim_input.price_amount



    # confidence -> wider range when confidence is low

    range_factor = max(0.05, (1.0 - confidence_pct / 100.0))  # min 5% range even at 100% confidence



    periods: dict[str, RevenuePeriod] = {}

    for period_key, cycle_idx in PERIOD_CYCLE_MAP.items():

        adoption_frac = influence_cycles[cycle_idx].overall_adoption  # 0-1

        ramp = PERIOD_RAMP_FACTORS[period_key]

        estimate = adoption_frac * tam_estimate * price * ramp

        low = max(0.0, estimate * (1.0 - range_factor))

        high = estimate * (1.0 + range_factor)

        periods[f"period_{period_key}"] = RevenuePeriod(

            estimate=round(estimate, 2),

            low=round(low, 2),

            high=round(high, 2),

        )



    assumptions = [

        f"Total Addressable Market estimated at {tam_estimate:,.0f} potential customers "

        f"in {sim_input.region} for the {sim_input.industry} category.",

        f"Pricing fixed at {sim_input.price_currency} {price:,.2f} per the user's input.",

        f"3-month figure applies a {PERIOD_RAMP_FACTORS['3mo']*100:.0f}% rollout ramp factor "

        f"(early access / soft launch).",

        f"6-month figure applies a {PERIOD_RAMP_FACTORS['6mo']*100:.0f}% rollout ramp factor "

        f"(broader regional rollout).",

        f"12-month figure applies a {PERIOD_RAMP_FACTORS['12mo']*100:.0f}% rollout ramp factor "

        f"(full market availability).",

        f"Adoption rates per period are taken directly from social-influence "

        f"simulation cycles 1, 3, and 5 respectively.",

        f"Revenue ranges widen as overall confidence ({confidence_pct:.0f}%) decreases, "

        f"reflecting forecast uncertainty.",

        RETENTION_RATE_LABEL,

    ]



    return RevenueProjection(

        period_3mo=periods["period_3mo"],

        period_6mo=periods["period_6mo"],

        period_12mo=periods["period_12mo"],

        tam_used=tam_estimate,

        tam_reasoning=tam_reasoning,

        assumptions=assumptions,

    )





def compute_conversion_rate(personas: list[PersonaResult], funnel: list[FunnelStage]) -> float:

    """Conversion rate = Purchase stage % (single source of truth, matches funnel)."""

    purchase_stage = next((s for s in funnel if s.name == "Purchase"), None)

    if purchase_stage is None:

        raise ValueError("compute_conversion_rate: 'Purchase' stage missing from funnel.")

    return purchase_stage.pct





# ──────────────────────────────────────────────────────────────────────────

# 5. LLM-DEPENDENT GENERATIONS — each takes REAL computed values as grounding

# ──────────────────────────────────────────────────────────────────────────

# These functions assume an `llm_client` with an async `generate_json(prompt,

# schema_hint) -> dict` method that calls OpenAI with JSON mode / structured

# output and returns a parsed dict. Implement llm_client separately (or in

# MOCK_MODE, return fixtures from a separate mock_data.py — see section 7).



class LLMClient:

    """Minimal interface contract — implement against your actual OpenAI wrapper."""



    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:

        raise NotImplementedError



    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:

        raise NotImplementedError





async def estimate_tam(llm: LLMClient, sim_input: SimulationInput) -> tuple[float, str]:

    system = (

        "You are a market sizing analyst. Estimate the Total Addressable "

        "Market (TAM) as a NUMBER OF POTENTIAL CUSTOMERS (not dollars) for "

        "the given product, industry, target market, and region. Justify "

        "the number using population estimates, internet/market penetration, "

        "and segment narrowing. Respond ONLY with JSON, no markdown fences: "

        '{"tam_estimate": <integer>, "tam_reasoning": "<2-3 sentences "'

        'explaining the calculation>", "tam_confidence": "low"|"medium"|"high"}'

    )

    user = (

        f"Product idea: {sim_input.idea}\n"

        f"Industry: {sim_input.industry}\n"

        f"Target market: {sim_input.target_market}\n"

        f"Region: {sim_input.region}\n"

        f"Price: {sim_input.price_currency} {sim_input.price_amount}"

    )

    result = await llm.generate_json(system, user)

    tam = float(result.get("tam_estimate", 0))

    if tam <= 0:

        raise ValueError(

            f"estimate_tam: LLM returned non-positive tam_estimate={tam}. "

            f"Raw result: {result}"

        )

    reasoning = result.get("tam_reasoning", "").strip()

    if len(reasoning) < 10:

        raise ValueError(f"estimate_tam: tam_reasoning too short/empty: {result}")

    return tam, reasoning





async def extract_competitors(

    llm: LLMClient, sim_input: SimulationInput, signals: SignalData

) -> list[Competitor]:

    system = (

        "Extract up to 6 real, named companies or products that compete with "

        "or are comparable to the given idea. Only return names that either "

        "appear in the provided source text, OR are well-known real companies "

        "in this space from your general knowledge. Never invent fictional "

        "company names, and never return placeholders like 'Competitor A'. "

        'Respond ONLY with JSON: {"competitors": [{"name": str, '

        '"why_relevant": "<1 sentence>", "positioning": "<1 sentence on how '

        'they differ from this idea>"}]}'

    )

    raw_signal_text = "\n".join(

        signals.complaints + signals.demands + signals.competitors_raw

    )[:4000]

    user = (

        f"Idea: {sim_input.idea}\n"

        f"Industry: {sim_input.industry}\n"

        f"Region: {sim_input.region}\n\n"

        f"Source text from market signals:\n{raw_signal_text or '(no signal text available)'}"

    )

    result = await llm.generate_json(system, user)

    raw_list = result.get("competitors", [])

    competitors = []

    for c in raw_list[:6]:

        name = (c.get("name") or "").strip()

        if not name or name.lower().startswith("competitor "):

            continue

        competitors.append(

            Competitor(

                name=name,

                why_relevant=(c.get("why_relevant") or "").strip() or "Operates in a related market segment.",

                positioning=(c.get("positioning") or "").strip() or "Positioning details unavailable.",

            )

        )

    if not competitors:

        raise ValueError(

            f"extract_competitors: LLM returned zero valid competitors. "

            f"Raw result: {result}. Retry with a general-knowledge-only prompt."

        )

    return competitors





async def generate_customer_quotes(

    llm: LLMClient,

    sim_input: SimulationInput,

    personas: list[PersonaResult],

    market_reception: MarketReception,

) -> list[CustomerQuote]:

    # Sample diverse personas: enthusiastic, skeptical, mixed

    sorted_by_excitement = sorted(personas, key=lambda p: p.excitement_score, reverse=True)

    sample_high = sorted_by_excitement[:3]

    sample_low = sorted_by_excitement[-3:]

    sample_mid = sorted_by_excitement[len(sorted_by_excitement) // 2 - 1 : len(sorted_by_excitement) // 2 + 2]

    sample = sample_high + sample_mid + sample_low



    persona_summaries = "\n".join(

        f"- {p.occupation}, age {p.age}, segment '{p.segment}': "

        f"excitement={p.excitement_score}/10, would_buy={p.would_buy}, "

        f"objections={p.objections}, reasoning: {p.reasoning}"

        for p in sample

    )



    pos_n = max(1, round(market_reception.breakdown.enthusiastic_pct / 100 * 8))

    mid_n = max(1, round(market_reception.breakdown.interested_pct / 100 * 8))

    neg_n = max(1, 8 - pos_n - mid_n)



    system = (

        "Write short customer review quotes (1-3 sentences each) as if real "

        "people tried this specific product. Quotes MUST reference concrete "

        "details of THIS product: its purpose, the stated price, and the "

        "target use case. Do NOT use generic phrases like 'this product is "

        "great' or 'I would definitely recommend'. Vary tone, sentence "

        "structure, and voice across quotes so they read like different "

        "people wrote them — some casual, some detailed, some short and blunt. "

        f"Generate roughly {pos_n} positive, {mid_n} mixed, and {neg_n} "

        "negative/skeptical quotes, matching the overall reception. "

        'Respond ONLY with JSON: {"quotes": [{"quote": str, "sentiment": '

        '"positive"|"mixed"|"negative", "persona_segment": str}]}'

    )

    user = (

        f"Product: {sim_input.idea}\n"

        f"Price: {sim_input.price_currency} {sim_input.price_amount}\n"

        f"Industry: {sim_input.industry}\n"

        f"Target market: {sim_input.target_market}\n\n"

        f"Sample simulated persona reactions for grounding:\n{persona_summaries}"

    )



    result = await llm.generate_json(system, user)

    quotes_raw = result.get("quotes", [])



    GENERIC_PHRASES = [

        "this product is great",

        "i would definitely recommend",

        "highly recommend",

        "game changer",

    ]



    quotes = []

    for q in quotes_raw:

        text = (q.get("quote") or "").strip()

        if not text or any(p in text.lower() for p in GENERIC_PHRASES):

            continue

        sentiment = q.get("sentiment", "mixed")

        if sentiment not in ("positive", "mixed", "negative"):

            sentiment = "mixed"

        quotes.append(

            CustomerQuote(

                quote=text,

                sentiment=sentiment,

                persona_segment=q.get("persona_segment", "General"),

            )

        )



    if len(quotes) < 4:

        raise ValueError(

            f"generate_customer_quotes: only {len(quotes)} valid quotes after "

            f"filtering (need >= 4). Raw result: {result}. Retry."

        )

    return quotes





async def generate_pricing_and_gtm(

    llm: LLMClient,

    sim_input: SimulationInput,

    personas: list[PersonaResult],

    pmf_score: float,

    final_adoption_pct: float,

) -> tuple[str, list[str]]:

    avg_budget_sensitivity = _safe_mean([p.budget_sensitivity for p in personas])



    system = (

        "Based on the given product, its PMF score, adoption rate, and the "

        "average budget sensitivity of simulated customers, provide: "

        "(1) a pricing recommendation as 2-3 sentences of concrete advice "

        "(e.g. keep/raise/lower price, add tiers, freemium), and "

        "(2) a go-to-market strategy as 3-5 short actionable bullet points. "

        'Respond ONLY with JSON: {"pricing_recommendation": str, '

        '"go_to_market_strategy": [str, str, ...]}'

    )

    user = (

        f"Product: {sim_input.idea}\n"

        f"Current price: {sim_input.price_currency} {sim_input.price_amount}\n"

        f"Industry: {sim_input.industry} | Region: {sim_input.region} | "

        f"Timeline: {sim_input.timeline}\n"

        f"PMF score: {pmf_score}/100\n"

        f"Final adoption: {final_adoption_pct:.1f}%\n"

        f"Average budget sensitivity (0=insensitive, 10=very sensitive): "

        f"{avg_budget_sensitivity:.1f}"

    )



    result = await llm.generate_json(system, user)

    pricing = (result.get("pricing_recommendation") or "").strip()

    gtm = [s.strip() for s in result.get("go_to_market_strategy", []) if s.strip()]



    if len(pricing) < 20:

        raise ValueError(f"generate_pricing_and_gtm: pricing_recommendation too short: {result}")

    if len(gtm) < 3:

        raise ValueError(f"generate_pricing_and_gtm: go_to_market_strategy has <3 items: {result}")



    return pricing, gtm





async def generate_executive_report(

    llm: LLMClient,

    sim_input: SimulationInput,

    pmf_score: float,

    pmf_label: str,

    final_adoption_pct: float,

    market_reception: MarketReception,

    top_objections: list[dict],

    revenue: RevenueProjection,

    competitors: list[Competitor],

    pricing_recommendation: str,

) -> tuple[str, LaunchRecommendation, list[RiskItem]]:

    """

    Single LLM call producing executive_summary, launch_recommendation,

    and risk_analysis TOGETHER so they cannot contradict each other.

    """

    objections_text = "; ".join(

        f"{o['objection']} ({o['pct']}% of customers)" for o in top_objections

    ) or "No major objections recorded."



    competitors_text = ", ".join(c.name for c in competitors)



    system = (

        "You are a senior market strategy analyst briefing the FOUNDER of a "

        "product on what the data says about their product's market prospects. "

        "Speak directly about THE PRODUCT and THE MARKET. NEVER mention "

        "'AURA', 'this simulation', 'synthetic personas', 'our analysis tool', "

        "'re-simulation', or any meta-commentary about how this analysis was "

        "produced — speak as if you simply know the market.\n\n"

        "Produce THREE things that must be mutually consistent with each other "

        "and with the launch_recommendation.decision field:\n"

        "1. executive_summary: 2-3 paragraphs. Para 1: what the market is "

        "telling us right now (reception, fit, competitive position). Para 2: "

        "biggest risks/objections and what's working in the product's favor. "

        "Para 3: concrete next steps for the founder, phrased as direct advice "

        "('You should...', 'Before launching, prioritize...').\n"

        "2. launch_recommendation: decision must be one of Launch/Pivot/Delay/Kill, "

        "with a rationale (2-3 sentences) that AGREES with the executive_summary's "

        "tone — if adoption/PMF are strong, decision should lean Launch; if weak, "

        "lean Pivot/Delay.\n"

        "3. risk_analysis: 3-5 risks, each with severity (low/medium/high) and "

        "a concrete mitigation.\n\n"

        'Respond ONLY with JSON: {"executive_summary": str, '

        '"launch_recommendation": {"decision": str, "rationale": str}, '

        '"risk_analysis": [{"risk": str, "severity": str, "mitigation": str}]}'

    )



    user = (

        f"Product: {sim_input.idea}\n"

        f"Industry: {sim_input.industry} | Target market: {sim_input.target_market} | "

        f"Price: {sim_input.price_currency} {sim_input.price_amount} | "

        f"Region: {sim_input.region} | Timeline: {sim_input.timeline}\n\n"

        f"FINDINGS:\n"

        f"- Product-Market Fit score: {pmf_score}/100 ({pmf_label})\n"

        f"- Final simulated adoption: {final_adoption_pct:.1f}%\n"

        f"- Market reception: {market_reception.overall_label} "

        f"(enthusiastic {market_reception.breakdown.enthusiastic_pct:.1f}%, "

        f"interested {market_reception.breakdown.interested_pct:.1f}%, "

        f"skeptical {market_reception.breakdown.skeptical_pct:.1f}%, "

        f"rejecting {market_reception.breakdown.rejecting_pct:.1f}%)\n"

        f"- Top objections: {objections_text}\n"

        f"- 12-month revenue projection: {sim_input.price_currency} "

        f"{revenue.period_12mo.estimate:,.0f} "

        f"(range {revenue.period_12mo.low:,.0f}-{revenue.period_12mo.high:,.0f})\n"

        f"- Key competitors: {competitors_text}\n"

        f"- Pricing recommendation: {pricing_recommendation}"

    )



    result = await llm.generate_json(system, user)



    summary = (result.get("executive_summary") or "").strip()

    if len(summary) < 100:

        raise ValueError(f"generate_executive_report: executive_summary too short: {result}")



    banned_terms = ["aura", "simulation", "synthetic persona", "re-simulation", "this analysis"]

    lowered = summary.lower()

    if any(term in lowered for term in banned_terms):

        raise ValueError(

            f"generate_executive_report: executive_summary contains banned "

            f"meta-commentary term. Summary: {summary}"

        )



    lr_raw = result.get("launch_recommendation", {})

    decision = lr_raw.get("decision", "")

    if decision not in ("Launch", "Pivot", "Delay", "Kill"):

        raise ValueError(f"generate_executive_report: invalid launch decision: {lr_raw}")

    rationale = (lr_raw.get("rationale") or "").strip()

    if len(rationale) < 20:

        raise ValueError(f"generate_executive_report: rationale too short: {lr_raw}")



    risks_raw = result.get("risk_analysis", [])

    risks = []

    for r in risks_raw:

        sev = r.get("severity", "medium")

        if sev not in ("low", "medium", "high"):

            sev = "medium"

        risk_text = (r.get("risk") or "").strip()

        mitigation = (r.get("mitigation") or "").strip()

        if risk_text and mitigation:

            risks.append(RiskItem(risk=risk_text, severity=sev, mitigation=mitigation))



    if len(risks) < 3:

        raise ValueError(f"generate_executive_report: <3 valid risks: {risks_raw}")



    return (

        summary,

        LaunchRecommendation(decision=decision, rationale=rationale),

        risks,

    )





# ──────────────────────────────────────────────────────────────────────────

# 6. ORCHESTRATOR — call this from your pipeline

# ──────────────────────────────────────────────────────────────────────────



async def run_forecast_and_report(

    state: PipelineState, llm: LLMClient

) -> ForecastResult:

    """

    Single entry point. Raises ValueError loudly on any data integrity issue

    rather than producing NaN — caller should catch, log, set job status to

    'failed' with the error message, and optionally retry the failing

    sub-step once with mock/fallback data.

    """

    personas = state.personas

    signals = state.signals

    cycles = state.influence_cycles

    sim_input = state.sim_input



    if not personas:

        raise ValueError(

            f"[{state.job_id}] run_forecast_and_report: personas is EMPTY. "

            f"Persona expansion (target 5000) must complete and be awaited "

            f"BEFORE this stage runs. Check pipeline ordering."

        )

    if len(cycles) < 6:

        raise ValueError(

            f"[{state.job_id}] run_forecast_and_report: influence_cycles has "

            f"{len(cycles)} entries, need 6 (cycle 0-5). Social influence "

            f"engine must snapshot every cycle."

        )



    # ── Pure numerical computations (deterministic, no LLM) ──────────────

    final_adoption_pct = compute_final_adoption_pct(personas)

    market_reception = compute_market_reception(personas)

    top_objections = compute_top_objections(personas)

    funnel = compute_funnel(personas)

    diffusion_curve = compute_diffusion_curve(cycles)

    pmf_score, pmf_label = compute_pmf_score(personas, signals, final_adoption_pct)

    conversion_rate_pct = compute_conversion_rate(personas, funnel)



    # ── LLM-grounded generations (real data passed as context) ───────────

    tam_estimate, tam_reasoning = await estimate_tam(llm, sim_input)



    # confidence depends on revenue range, but revenue range depends on

    # confidence -> resolve with a two-pass: first pass with neutral

    # confidence to get a provisional range, then recompute confidence,

    # then recompute revenue with final confidence.

    provisional_revenue = compute_revenue_projection(

        sim_input, cycles, tam_estimate, tam_reasoning, confidence_pct=50.0

    )

    confidence = compute_confidence(

        signals,

        personas,

        provisional_revenue.period_12mo.low,

        provisional_revenue.period_12mo.high,

        provisional_revenue.period_12mo.estimate,

    )

    revenue_projection = compute_revenue_projection(

        sim_input, cycles, tam_estimate, tam_reasoning,

        confidence_pct=confidence.final_confidence_pct,

    )



    competitors = await extract_competitors(llm, sim_input, signals)

    customer_quotes = await generate_customer_quotes(llm, sim_input, personas, market_reception)

    pricing_recommendation, go_to_market_strategy = await generate_pricing_and_gtm(

        llm, sim_input, personas, pmf_score, final_adoption_pct

    )

    executive_summary, launch_recommendation, risk_analysis = await generate_executive_report(

        llm, sim_input, pmf_score, pmf_label, final_adoption_pct, market_reception,

        top_objections, revenue_projection, competitors, pricing_recommendation,

    )



    result = ForecastResult(

        job_id=state.job_id,

        pmf_score=pmf_score,

        pmf_label=pmf_label,

        final_adoption_pct=round(final_adoption_pct, 1),

        confidence=confidence,

        conversion_rate_pct=conversion_rate_pct,

        revenue_projection=revenue_projection,

        market_reception=market_reception,

        funnel=funnel,

        diffusion_curve=diffusion_curve,

        competitors=competitors,

        top_objections=top_objections,

        customer_quotes=customer_quotes,

        executive_summary=executive_summary,

        launch_recommendation=launch_recommendation,

        risk_analysis=risk_analysis,

        pricing_recommendation=pricing_recommendation,

        go_to_market_strategy=go_to_market_strategy,

    )



    logger.info(

        "[%s] Forecast complete: PMF=%.1f (%s), adoption=%.1f%%, "

        "confidence=%.1f%%, 12mo revenue=%s %.0f, competitors=%s",

        state.job_id, pmf_score, pmf_label, final_adoption_pct,

        confidence.final_confidence_pct, sim_input.price_currency,

        revenue_projection.period_12mo.estimate,

        [c.name for c in competitors],

    )



    return result





# ──────────────────────────────────────────────────────────────────────────

# 7. MOCK MODE — deterministic fixtures for end-to-end testing without API keys

# ──────────────────────────────────────────────────────────────────────────



class MockLLMClient(LLMClient):

    """

    Returns plausible, INPUT-AWARE fixtures so MOCK_MODE still produces

    different output per product (avoids the "always Salesforce/HubSpot"

    bug). Keys off keywords in the prompt to vary fixture selection.

    """



    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:

        text = user_prompt.lower()



        if "tam_estimate" in system_prompt:

            if "saas" in text or "software" in text or "app" in text:

                base = 850_000

            elif "hardware" in text or "device" in text or "bottle" in text:

                base = 120_000

            else:

                base = 300_000

            return {

                "tam_estimate": base,

                "tam_reasoning": (

                    f"Estimated from target market description and regional "

                    f"internet/market penetration assumptions for the stated "

                    f"category (mock estimate, base={base:,})."

                ),

                "tam_confidence": "medium",

            }



        if "competitors" in system_prompt:

            if "saas" in text or "writing" in text or "productivity" in text:

                names = [

                    ("Notion", "Popular all-in-one workspace with AI features", "Broader scope, higher price tiers"),

                    ("Notion AI", "Built-in AI writing assistant for workspaces", "Bundled into existing workspace product"),

                    ("Grammarly", "AI writing assistant focused on grammar/tone", "Narrower focus, strong brand trust"),

                ]

            elif "hardware" in text or "bottle" in text or "wearable" in text:

                names = [

                    ("HidrateSpark", "Smart water bottle with hydration tracking", "Established hardware brand, higher price point"),

                    ("Fitbit", "Wearable health tracking ecosystem", "Broader health tracking, subscription model"),

                    ("Apple Watch", "General wellness tracking on a major platform", "Much higher price, multi-purpose device"),

                ]

            else:

                names = [

                    ("Generic Market Leader Co", "Established player in this category", "Higher price, broader feature set"),

                    ("Niche Challenger Inc", "Smaller competitor targeting similar segment", "Similar price point, fewer integrations"),

                    ("Indirect Substitute", "Adjacent product solving overlapping need", "Different approach to the same problem"),

                ]

            return {"competitors": [

                {"name": n, "why_relevant": w, "positioning": p} for n, w, p in names

            ]}



        if "quotes" in system_prompt:

            return {"quotes": [

                {"quote": "I tried this for two weeks and it actually saved me time on the boring parts of my day, though the setup took longer than I expected.", "sentiment": "positive", "persona_segment": "Early Adopter"},

                {"quote": "Honestly? Works fine. Wouldn't pay much more than this for it though.", "sentiment": "mixed", "persona_segment": "Budget Buyer"},

                {"quote": "Cool idea but I'm not sure I'd switch from what I already use unless it does something dramatically better.", "sentiment": "mixed", "persona_segment": "Pragmatist"},

                {"quote": "Not for me. The price doesn't match what I'm getting and I've seen similar things free elsewhere.", "sentiment": "negative", "persona_segment": "Skeptic"},

                {"quote": "This is exactly the kind of thing I've been looking for. Already told two coworkers about it.", "sentiment": "positive", "persona_segment": "Enthusiast"},

                {"quote": "Decent, but the onboarding flow confused me at first. Got it eventually.", "sentiment": "mixed", "persona_segment": "Solo Professional"},

            ]}



        if "pricing_recommendation" in system_prompt:

            return {

                "pricing_recommendation": (

                    "Current pricing appears roughly aligned with budget "

                    "sensitivity in the target segment. Consider introducing "

                    "a lower-cost entry tier to capture price-sensitive "

                    "early adopters, while reserving advanced features for "

                    "the current price point."

                ),

                "go_to_market_strategy": [

                    "Launch a limited beta with early adopters to gather testimonials",

                    "Focus initial marketing on the segment showing highest excitement scores",

                    "Address top objections directly in landing page copy",

                    "Consider a referral incentive to leverage word-of-mouth diffusion",

                ],

            }



        if "executive_summary" in system_prompt:

            # Extract a couple of numbers from the prompt for plausibility

            return {

                "executive_summary": (

                    "The current market signals point to moderate but real "

                    "interest in this product, with a meaningful share of "

                    "potential customers expressing enthusiasm once they "

                    "understand the core value proposition. Competitive "

                    "pressure exists but is not overwhelming, leaving room "

                    "for differentiation on price and ease of adoption.\n\n"

                    "The most significant friction point is price "

                    "sensitivity combined with switching costs from existing "

                    "tools — addressing this directly in messaging and "

                    "onboarding will materially improve conversion. On the "

                    "positive side, the segments showing the highest "

                    "excitement also show high price acceptance, suggesting "

                    "a viable early-adopter beachhead.\n\n"

                    "You should prioritize a focused launch targeting the "

                    "highest-excitement segment first, simplify onboarding "

                    "to reduce trial friction, and consider a tiered pricing "

                    "structure before a broader regional rollout. Revisit "

                    "pricing after the first cohort's retention data comes in."

                ),

                "launch_recommendation": {

                    "decision": "Launch",

                    "rationale": (

                        "Adoption and product-market fit signals are strong "

                        "enough to justify a focused launch into the "

                        "highest-excitement segment, with pricing and "

                        "onboarding refinements addressed in parallel."

                    ),

                },

                "risk_analysis": [

                    {"risk": "Price sensitivity in budget-conscious segments", "severity": "medium", "mitigation": "Introduce a lower-cost entry tier"},

                    {"risk": "Switching costs from incumbent tools", "severity": "medium", "mitigation": "Provide migration tooling and onboarding guides"},

                    {"risk": "Competitive response from established players", "severity": "low", "mitigation": "Differentiate on speed-to-value and pricing"},

                ],

            }



        raise NotImplementedError(f"MockLLMClient: no fixture for prompt: {system_prompt[:80]}")



    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:

        return "Mock text response."





# ──────────────────────────────────────────────────────────────────────────

# 8. FASTAPI WIRING EXAMPLE

# ──────────────────────────────────────────────────────────────────────────

"""

In your pipeline orchestrator (LangGraph node or background task):



    from aura_forecast_report import (

        run_forecast_and_report, PipelineState, MockLLMClient, ForecastResult

    )



    async def forecast_and_report_node(state: PipelineState) -> ForecastResult:

        llm = MockLLMClient() if os.getenv("MOCK_MODE") == "true" else RealOpenAIClient()

        try:

            result = await asyncio.wait_for(

                run_forecast_and_report(state, llm), timeout=45

            )

        except Exception as e:

            logger.exception("[%s] Forecast/report stage failed: %s", state.job_id, e)

            await set_job_status(state.job_id, "failed", error=str(e))

            raise

        await persist_report(state.job_id, result.model_dump())

        await set_job_status(state.job_id, "complete", progress=100)

        return result



GET /simulate/{job_id}/result should return result.model_dump() directly —

the frontend TypeScript types should be generated from ForecastResult's

JSON schema (result.model_json_schema()) to guarantee field-name parity.

"""





#Integration checklist for your coder:

#Map existing PersonaResult/SocialInfluenceCycle fields to these exact schemas — if names differ, fix the upstream producers, not this module.
#Ensure persona expansion (5000) completes and is awaited before this runs — personas must have length 5000, not 0.
#Ensure social influence engine snapshots all 6 cycles (0–5) with segment_adoption and overall_adoption.
#Replace MockLLMClient with a real OpenAI JSON-mode client for production; keep mock for MOCK_MODE=true.
#Run the two-product differential test from the previous prompt against this module's output — every field should differ meaningfully.
#Generate frontend TypeScript types from ForecastResult.model_json_schema() to eliminate field-name mismatches.