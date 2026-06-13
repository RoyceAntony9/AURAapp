import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from backend.app.database import Base

class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued, collecting_signals, etc.
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str] = mapped_column(String, default="Initializing")
    idea: Mapped[str] = mapped_column(Text)
    industry: Mapped[str] = mapped_column(String)
    market: Mapped[str] = mapped_column(String)
    pricing_amount: Mapped[float] = mapped_column(Float)
    pricing_currency: Mapped[str] = mapped_column(String)
    region: Mapped[str] = mapped_column(String)
    timeline: Mapped[str] = mapped_column(String)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )

    # Relationships
    signals: Mapped[List["Signal"]] = relationship("Signal", back_populates="job", cascade="all, delete-orphan")
    archetypes: Mapped[List["PersonaArchetype"]] = relationship("PersonaArchetype", back_populates="job", cascade="all, delete-orphan")
    simulations: Mapped[List["SimulationResult"]] = relationship("SimulationResult", back_populates="job", cascade="all, delete-orphan")
    report: Mapped[Optional["Report"]] = relationship("Report", back_populates="job", uselist=False, cascade="all, delete-orphan")


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String)  # reddit, google_trends, news, synthetic
    complaints: Mapped[List[str]] = mapped_column(JSON, default=list)
    demands: Mapped[List[str]] = mapped_column(JSON, default=list)
    competitors: Mapped[List[str]] = mapped_column(JSON, default=list)
    market_sentiment_score: Mapped[float] = mapped_column(Float)
    market_sentiment_summary: Mapped[str] = mapped_column(Text)
    
    # Enriched discovery metrics
    market_strength: Mapped[float] = mapped_column(Float, default=0.5)
    competitive_density: Mapped[float] = mapped_column(Float, default=0.5)
    market_maturity: Mapped[str] = mapped_column(String, default="Moderate")
    confidence: Mapped[float] = mapped_column(Float, default=0.7)

    job: Mapped["Job"] = relationship("Job", back_populates="signals")


class PersonaArchetype(Base):
    __tablename__ = "persona_archetypes"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g., "jobId_archIndex"
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String)
    age: Mapped[int] = mapped_column(Integer)
    income_bracket: Mapped[str] = mapped_column(String)
    occupation: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String)
    buying_behavior: Mapped[str] = mapped_column(Text)
    goals: Mapped[List[str]] = mapped_column(JSON, default=list)
    objections: Mapped[List[str]] = mapped_column(JSON, default=list)
    risk_tolerance: Mapped[str] = mapped_column(String)  # low, medium, high
    budget_sensitivity: Mapped[int] = mapped_column(Integer)  # 1-10
    segment: Mapped[str] = mapped_column(String)  # cluster name
    influence: Mapped[float] = mapped_column(Float, default=0.5)
    
    # Enriched persona metrics
    buying_trigger: Mapped[str] = mapped_column(String, default="")
    pain_point: Mapped[str] = mapped_column(String, default="")
    adoption_probability: Mapped[float] = mapped_column(Float, default=0.5)
    behavior_type: Mapped[str] = mapped_column(String, default="Early Adopter")  # Early Adopter, Risk Avoider, etc.
    technology_comfort: Mapped[float] = mapped_column(Float, default=50.0)
    risk_appetite: Mapped[float] = mapped_column(Float, default=50.0)
    social_influence: Mapped[float] = mapped_column(Float, default=50.0)
    income: Mapped[float] = mapped_column(Float, default=50000.0)
    urgency: Mapped[float] = mapped_column(Float, default=50.0)
    existing_alternatives: Mapped[float] = mapped_column(Float, default=50.0)

    job: Mapped["Job"] = relationship("Job", back_populates="archetypes")


class SimulationResult(Base):
    __tablename__ = "simulation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"))
    archetype_id: Mapped[str] = mapped_column(String, ForeignKey("persona_archetypes.id", ondelete="CASCADE"))
    would_buy: Mapped[bool] = mapped_column(Boolean)
    excitement_score: Mapped[int] = mapped_column(Integer)
    objections: Mapped[List[str]] = mapped_column(JSON, default=list)
    likelihood_score: Mapped[float] = mapped_column(Float)
    reasoning: Mapped[str] = mapped_column(Text)

    job: Mapped["Job"] = relationship("Job", back_populates="simulations")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String, ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    
    executive_summary: Mapped[str] = mapped_column(Text)
    opportunity_score: Mapped[int] = mapped_column(Integer)
    opportunity_label: Mapped[str] = mapped_column(String)  # Strong, Moderate, Weak
    launch_recommendation: Mapped[str] = mapped_column(String)  # Launch, Pivot, Delay, Kill
    launch_rationale: Mapped[str] = mapped_column(Text)
    customer_quotes: Mapped[List[str]] = mapped_column(JSON, default=list)
    revenue_projection: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)  # 3/6/12mo
    risk_analysis: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)  # risks with severity + mitigation
    adoption_curve: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)  # cycle-by-cycle adoption data
    market_segments: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)  # clustered segment details
    pricing_recommendation: Mapped[str] = mapped_column(Text)
    go_to_market_strategy: Mapped[List[str]] = mapped_column(JSON, default=list)
    confidence_score: Mapped[int] = mapped_column(Integer)
    
    # Enriched reporting structures
    signal_intelligence: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    buyer_journey: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    simulated_conversations: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    competitors_battle: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence_details: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    objections_list: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    # Market Friction Model Metrics
    launch_difficulty: Mapped[float] = mapped_column(Float, default=0.0)
    price_friction: Mapped[float] = mapped_column(Float, default=0.0)
    social_friction: Mapped[float] = mapped_column(Float, default=0.0)
    behavior_change_cost: Mapped[float] = mapped_column(Float, default=0.0)
    trust_requirement: Mapped[float] = mapped_column(Float, default=0.0)
    infrastructure_requirement: Mapped[float] = mapped_column(Float, default=0.0)
    switching_cost: Mapped[float] = mapped_column(Float, default=0.0)
    time_to_value: Mapped[float] = mapped_column(Float, default=0.0)
    novelty_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    education_cost: Mapped[float] = mapped_column(Float, default=0.0)
    product_market_fit: Mapped[float] = mapped_column(Float, default=0.0)
    social_adoption: Mapped[float] = mapped_column(Float, default=0.0)
    price_acceptance: Mapped[float] = mapped_column(Float, default=0.0)
    trust_barrier: Mapped[float] = mapped_column(Float, default=0.0)
    habit_change_required: Mapped[float] = mapped_column(Float, default=0.0)
    scenario_tests: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)

    job: Mapped["Job"] = relationship("Job", back_populates="report")
