"""
Inter-stage payload schemas for AURA pipeline.
Each stage has explicit input and output contracts with validation.
This prevents silent NaN/undefined bugs by validating field existence and types at stage boundaries.
"""

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Dict, Any, Optional
import math


# ============================================================================
# SIGNAL ENGINE OUTPUTS
# ============================================================================

class CompetitorInfo(BaseModel):
    """A real, named competitor or product in the market."""
    name: str = Field(..., min_length=1, description="Real company or product name, not a placeholder")
    why_relevant: str = Field(..., min_length=10, description="1-2 sentence explanation of relevance")
    positioning: str = Field(..., min_length=10, description="How this competitor differs from the product idea")


class SignalEngineOutput(BaseModel):
    """Complete output from Signal Engine node."""
    job_id: str
    signals: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Raw market signals from Reddit, News, Google Trends, etc."
    )
    competitors: List[CompetitorInfo] = Field(
        default_factory=list,
        description="Named competitors extracted from signals + LLM general knowledge"
    )
    market_sentiment_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Aggregate market sentiment (0=negative, 1=positive)"
    )
    market_sentiment_summary: str = Field(..., min_length=20, description="Summary of market sentiment")
    market_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    competitive_density: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0, description="Signal confidence score")

    @field_validator('competitors')
    @classmethod
    def validate_competitors_not_placeholder(cls, v: List[CompetitorInfo]) -> List[CompetitorInfo]:
        """Ensure no placeholder competitor names like 'Competitor A', 'Company X', etc."""
        placeholder_patterns = ['competitor', 'company a', 'company b', 'product a', 'sample', 'lorem', 'placeholder']
        for competitor in v:
            name_lower = competitor.name.lower()
            if any(p in name_lower for p in placeholder_patterns):
                raise ValueError(
                    f"Competitor name '{competitor.name}' appears to be a placeholder. "
                    "Use real, named companies only."
                )
        return v


# ============================================================================
# PERSONA ENGINE OUTPUTS
# ============================================================================

class PersonaArchetype(BaseModel):
    """Single customer archetype (15 total per job)."""
    id: str = Field(..., description="Unique archetype ID, e.g. job_id_arch_0")
    name: str = Field(..., min_length=3)
    age: int = Field(..., ge=18, le=100)
    income_bracket: str = Field(...)
    occupation: str = Field(..., min_length=3)
    location: str = Field(...)
    buying_behavior: str = Field(..., min_length=20)
    goals: List[str] = Field(default_factory=list, min_items=1)
    objections: List[str] = Field(default_factory=list, max_items=5)
    risk_tolerance: str = Field(..., description="low, medium, high")
    budget_sensitivity: int = Field(..., ge=1, le=10)
    segment: str = Field(..., description="Segment/cluster name")
    influence: float = Field(default=0.5, ge=0.0, le=1.0)
    buying_trigger: str = Field(default="")
    pain_point: str = Field(default="")
    adoption_probability: float = Field(default=0.5, ge=0.0, le=1.0)
    behavior_type: str = Field(default="Early Adopter")
    technology_comfort: float = Field(default=50.0, ge=0.0, le=100.0)
    risk_appetite: float = Field(default=50.0, ge=0.0, le=100.0)
    social_influence: float = Field(default=50.0, ge=0.0, le=100.0)
    income: float = Field(default=50000.0, ge=0.0)
    urgency: float = Field(default=50.0, ge=0.0, le=100.0)
    existing_alternatives: float = Field(default=50.0, ge=0.0, le=100.0)


class PersonaEngineOutput(BaseModel):
    """Complete output from Persona Engine node."""
    job_id: str
    archetypes: List[PersonaArchetype] = Field(..., min_items=15, max_items=15)

    @field_validator('archetypes')
    @classmethod
    def validate_unique_ids(cls, v: List[PersonaArchetype]) -> List[PersonaArchetype]:
        """Ensure all archetype IDs are unique."""
        ids = [a.id for a in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Archetype IDs must be unique")
        return v


# ============================================================================
# SIMULATION ENGINE OUTPUTS
# ============================================================================

class SimulationResultRecord(BaseModel):
    """Single simulated customer result."""
    customer_id: str = Field(..., description="Unique customer ID within population")
    archetype_id: str = Field(..., description="Which archetype this customer is from")
    would_buy: bool = Field(..., description="Passed convert stage")
    excitement_score: int = Field(..., ge=0, le=10, description="0-10 excitement rating")
    objections: List[str] = Field(default_factory=list, max_items=5)
    likelihood_score: float = Field(..., ge=0.0, le=1.0, description="Geometric mean of funnel stages")
    reasoning: str = Field(..., min_length=50, description="First-person explanation of decision")


class PopulationAggregate(BaseModel):
    """Aggregated metrics from population simulation."""
    total_population: int = Field(..., gt=0, description="Total customers simulated")
    discover_count: int = Field(..., ge=0)
    care_count: int = Field(..., ge=0)
    try_count: int = Field(..., ge=0)
    convert_count: int = Field(..., ge=0)
    retain_count: int = Field(..., ge=0)
    adoption_percentage: float = Field(
        ..., ge=0.0, le=100.0,
        description="Percentage of population that would convert"
    )
    retention_percentage: float = Field(..., ge=0.0, le=100.0)
    avg_likelihood: float = Field(..., ge=0.0, le=1.0)
    avg_excitement: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    avg_p_discover: float = Field(..., ge=0.0, le=1.0)
    avg_p_care: float = Field(..., ge=0.0, le=1.0)
    avg_p_try: float = Field(..., ge=0.0, le=1.0)
    avg_p_convert: float = Field(..., ge=0.0, le=1.0)
    avg_p_retain: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode='after')
    def validate_adoption_percentage_is_finite(self) -> 'PopulationAggregate':
        """Ensure adoption_percentage is a real number, not NaN."""
        if math.isnan(self.adoption_percentage) or math.isinf(self.adoption_percentage):
            raise ValueError(
                f"adoption_percentage must be finite; got {self.adoption_percentage}. "
                "Check that total_population > 0 and results were computed correctly."
            )
        return self

    @model_validator(mode='after')
    def validate_conversion_chain(self) -> 'PopulationAggregate':
        """Sanity check: conversion chain should be monotonic."""
        counts = [
            self.discover_count,
            self.care_count,
            self.try_count,
            self.convert_count,
            self.retain_count
        ]
        for i in range(len(counts) - 1):
            if counts[i + 1] > counts[i]:
                raise ValueError(
                    f"Funnel chain is invalid: counts should be monotonic decreasing. "
                    f"Got discover={self.discover_count}, care={self.care_count}, "
                    f"try={self.try_count}, convert={self.convert_count}, retain={self.retain_count}"
                )
        return self


class SimulationEngineOutput(BaseModel):
    """Complete output from Simulation Engine node."""
    job_id: str
    population_results: List[SimulationResultRecord] = Field(
        ..., min_items=5000, max_items=5000,
        description="All 5000 simulated customers"
    )
    population_aggregate: PopulationAggregate = Field(
        ..., description="Aggregated funnel metrics"
    )


# ============================================================================
# SOCIAL INFLUENCE ENGINE OUTPUTS
# ============================================================================

class AdoptionCycleData(BaseModel):
    """Rogers diffusion model results for one cycle."""
    cycle: int = Field(..., ge=0, le=5)
    innovators_adopted: int = Field(..., ge=0)
    early_adopters_adopted: int = Field(..., ge=0)
    early_majority_adopted: int = Field(..., ge=0)
    late_majority_adopted: int = Field(..., ge=0)
    laggards_adopted: int = Field(..., ge=0)
    cumulative_adoption: int = Field(..., ge=0)
    cumulative_adoption_pct: float = Field(..., ge=0.0, le=100.0)


class SocialInfluenceEngineOutput(BaseModel):
    """Complete output from Social Influence Engine node."""
    job_id: str
    adoption_curve: Dict[str, Any] = Field(
        ..., description="6-cycle Rogers diffusion results"
    )
    adoption_curve_cycles: List[AdoptionCycleData] = Field(
        ..., min_items=6, max_items=6,
        description="Per-cycle adoption breakdown"
    )
    final_adoption_pct: float = Field(
        ..., ge=0.0, le=100.0,
        description="Adoption percentage at cycle 5"
    )


# ============================================================================
# FORECAST ENGINE OUTPUTS
# ============================================================================

class TAMEstimate(BaseModel):
    """Total Addressable Market estimation."""
    tam_estimate: int = Field(..., gt=0, description="Estimated number of potential customers")
    tam_reasoning: str = Field(..., min_length=50, description="Justification for TAM number")
    tam_confidence: str = Field(
        ..., pattern="^(low|medium|high)$",
        description="Confidence level in TAM estimate"
    )


class RevenueProjectionPeriod(BaseModel):
    """Revenue projection for one time period."""
    months: int = Field(..., description="3, 6, or 12")
    estimate: float = Field(..., ge=0.0, description="Best estimate")
    low: float = Field(..., ge=0.0, description="Low confidence band")
    high: float = Field(..., ge=0.0, description="High confidence band")

    @model_validator(mode='after')
    def validate_band_ordering(self) -> 'RevenueProjectionPeriod':
        """Ensure low <= estimate <= high."""
        if not (self.low <= self.estimate <= self.high):
            raise ValueError(
                f"Revenue bands must satisfy low <= estimate <= high. "
                f"Got low={self.low}, estimate={self.estimate}, high={self.high}"
            )
        return self


class RevenueProjection(BaseModel):
    """Complete revenue forecast."""
    currency: str = Field(..., min_length=3, max_length=3)
    projections: List[RevenueProjectionPeriod] = Field(..., min_items=3, max_items=3)
    tam_used: int = Field(..., gt=0, description="TAM value used in calculation")
    tam_reasoning: str = Field(..., min_length=30)
    tam_confidence: str = Field(..., pattern="^(low|medium|high)$")
    assumptions: List[str] = Field(
        ..., min_items=3,
        description="Human-readable list of assumptions made in projection"
    )


class RankedObjection(BaseModel):
    """Top objection facing the product."""
    objection: str = Field(..., min_length=5)
    count: int = Field(..., gt=0, description="Number of customers citing this")
    percentage: float = Field(..., ge=0.0, le=100.0, description="Percentage of population")


class ForecastEngineOutput(BaseModel):
    """Complete output from Forecast Engine node."""
    job_id: str
    addressable_market: int = Field(..., gt=0)
    confidence_score: int = Field(..., ge=0, le=100)
    adoption_percentage: float = Field(..., ge=0.0, le=100.0)
    product_market_fit_score: int = Field(
        ..., ge=0, le=100,
        description="NEW: 0-100 PMF score from weighted formula"
    )
    pmf_label: str = Field(
        ..., pattern="^(Weak Fit|Moderate Fit|Strong Fit)$",
        description="Label band for PMF score"
    )
    market_reception: Dict[str, Any] = Field(
        ..., description="Distribution breakdown of customer sentiment"
    )
    ranked_objections: List[RankedObjection] = Field(...)
    revenue_projection: RevenueProjection = Field(...)

    @field_validator('adoption_percentage')
    @classmethod
    def validate_adoption_finite(cls, v: float) -> float:
        """Ensure adoption % is finite."""
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"adoption_percentage must be finite; got {v}")
        return v


# ============================================================================
# REPORT ENGINE INPUTS (AGGREGATED)
# ============================================================================

class ReportEngineInput(BaseModel):
    """Complete input to Report Engine — aggregated from all prior stages."""
    job_id: str
    idea: str
    industry: str
    market: str
    pricing_amount: float
    pricing_currency: str
    region: str
    timeline: str

    # From Signal Engine
    signals: SignalEngineOutput

    # From Persona Engine
    personas: PersonaEngineOutput

    # From Simulation Engine
    population_results: List[SimulationResultRecord]
    population_aggregate: PopulationAggregate

    # From Social Influence Engine
    adoption_curve: Dict[str, Any]
    adoption_curve_cycles: List[AdoptionCycleData]
    final_adoption_pct: float

    # From Forecast Engine
    forecast: ForecastEngineOutput

    @model_validator(mode='after')
    def validate_required_for_report(self) -> 'ReportEngineInput':
        """Ensure all upstream data is present and valid before report generation."""
        errors = []

        # Check population exists and is non-zero
        if not self.population_results or len(self.population_results) == 0:
            errors.append("population_results is empty — simulation must complete before report")
        if self.population_aggregate.total_population == 0:
            errors.append("total_population is 0 — simulation failed to create population")

        # Check adoption % is real
        if self.population_aggregate.adoption_percentage < 0 or self.population_aggregate.adoption_percentage > 100:
            errors.append(
                f"adoption_percentage out of range: {self.population_aggregate.adoption_percentage}"
            )

        # Check forecast metrics
        if self.forecast.adoption_percentage < 0 or self.forecast.adoption_percentage > 100:
            errors.append(f"forecast adoption_percentage invalid: {self.forecast.adoption_percentage}")

        if errors:
            raise ValueError(f"ReportEngineInput validation failed: {'; '.join(errors)}")

        return self


# ============================================================================
# REPORT ENGINE OUTPUT (FINAL)
# ============================================================================

class CustomerQuote(BaseModel):
    """Single customer review quote."""
    quote: str = Field(..., min_length=30, description="Customer review, 1-3 sentences")
    sentiment: str = Field(..., pattern="^(positive|mixed|negative)$")
    persona_segment: str = Field(..., description="Which segment/archetype this represents")


class MarketReceptionBreakdown(BaseModel):
    """Distribution of customer sentiment."""
    overall_label: str = Field(
        ..., pattern="^(Positive|Mixed|Negative|Skeptical)$",
        description="Overall market reception label"
    )
    enthusiastic_pct: float = Field(..., ge=0.0, le=100.0, description="excitement_score >= 8")
    interested_pct: float = Field(..., ge=0.0, le=100.0, description="excitement_score 5-7")
    skeptical_pct: float = Field(..., ge=0.0, le=100.0, description="excitement_score 2-4")
    rejecting_pct: float = Field(..., ge=0.0, le=100.0, description="excitement_score 0-1")

    @model_validator(mode='after')
    def validate_percentages_sum(self) -> 'MarketReceptionBreakdown':
        """Ensure percentages sum to approximately 100%."""
        total = self.enthusiastic_pct + self.interested_pct + self.skeptical_pct + self.rejecting_pct
        if abs(total - 100.0) > 1.0:  # Allow 1% rounding error
            raise ValueError(
                f"Market reception percentages must sum to ~100%; got {total}. "
                f"enthusiastic={self.enthusiastic_pct}, interested={self.interested_pct}, "
                f"skeptical={self.skeptical_pct}, rejecting={self.rejecting_pct}"
            )
        return self


class RiskItem(BaseModel):
    """Single risk with severity and mitigation."""
    risk: str = Field(..., min_length=20)
    severity: str = Field(..., pattern="^(low|medium|high)$")
    mitigation: str = Field(..., min_length=20)


class ReportEngineOutput(BaseModel):
    """Final report output — persisted to database."""
    job_id: str

    # Core metrics
    executive_summary: str = Field(..., min_length=200, description="MUST be about the product, never AURA")
    opportunity_score: int = Field(..., ge=0, le=100, description="Market opportunity strength")
    opportunity_label: str = Field(..., pattern="^(Strong|Moderate|Weak)$")
    launch_recommendation: str = Field(..., min_length=5)
    launch_rationale: str = Field(..., min_length=100)

    # Product-Market Fit
    product_market_fit: float = Field(..., ge=0.0, le=100.0, description="NEW: PMF score")
    pmf_label: str = Field(..., pattern="^(Weak Fit|Moderate Fit|Strong Fit)$")

    # Market Reception
    market_reception: MarketReceptionBreakdown = Field(...)

    # Competitors
    competitors: List[CompetitorInfo] = Field(
        ..., min_items=3,
        description="Real, named competitors — never placeholders"
    )

    # Customer Quotes
    customer_quotes: List[CustomerQuote] = Field(
        ..., min_items=6, max_items=8,
        description="Dynamic, product-specific quotes from actual personas"
    )

    # Revenue
    revenue_projection: RevenueProjection = Field(...)

    # Risk Analysis
    risk_analysis: List[RiskItem] = Field(..., min_items=3)

    # Adoption Curve
    adoption_curve: Dict[str, Any] = Field(...)

    # Market Segments
    market_segments: List[Dict[str, Any]] = Field(default_factory=list)

    # GTM & Pricing
    pricing_recommendation: str = Field(..., min_length=50)
    go_to_market_strategy: List[str] = Field(..., min_items=3, max_items=5)

    # Confidence
    confidence_score: int = Field(..., ge=0, le=100)

    @field_validator('executive_summary')
    @classmethod
    def validate_executive_summary_not_about_aura(cls, v: str) -> str:
        """Ensure executive summary is about the product, not AURA."""
        forbidden = ['aura', 'simulation', 'synthetic persona', 'analysis tool', 'our analysis', 'this tool']
        v_lower = v.lower()
        for word in forbidden:
            if word in v_lower:
                raise ValueError(
                    f"Executive summary must be about the PRODUCT, not AURA. "
                    f"Found forbidden term '{word}' in summary. "
                    f"Summary should brief the founder about their product's prospects."
                )
        return v

    @field_validator('customer_quotes')
    @classmethod
    def validate_quotes_not_generic(cls, v: List[CustomerQuote]) -> List[CustomerQuote]:
        """Ensure customer quotes reference specific product details, not generic SaaS language."""
        generic_phrases = [
            'this product is great',
            'i would definitely recommend',
            'this is amazing',
            'really helpful',
            'game changer',
            'best thing',
            'love it',
            'lorem ipsum'
        ]
        for quote in v:
            quote_lower = quote.quote.lower()
            # Check for generic placeholder phrases
            for phrase in generic_phrases:
                if phrase in quote_lower:
                    # Only raise error if quote doesn't have any concrete references
                    # (e.g., "really helpful for managing finances" is ok)
                    if len(quote.quote) < 40:  # Very short + generic = problem
                        raise ValueError(
                            f"Customer quote appears generic/templated: '{quote.quote}'. "
                            f"Quotes must reference concrete product details (domain, price, use case)."
                        )
        return v

    @field_validator('competitors')
    @classmethod
    def validate_competitors_not_placeholder(cls, v: List[CompetitorInfo]) -> List[CompetitorInfo]:
        """Ensure no placeholder competitor names."""
        if not v:
            raise ValueError("Competitors list cannot be empty — must have at least 3 real competitors")
        placeholder_patterns = ['competitor a', 'competitor b', 'company a', 'product a', 'sample']
        for competitor in v:
            if any(p in competitor.name.lower() for p in placeholder_patterns):
                raise ValueError(
                    f"Competitor name '{competitor.name}' is a placeholder. Use real, named companies only."
                )
        return v
