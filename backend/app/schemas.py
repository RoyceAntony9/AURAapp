from pydantic import BaseModel, Field, field_validator
from typing import List, Dict, Any, Optional

class PricingModel(BaseModel):
    amount: float = Field(..., gt=0, description="Price amount must be greater than zero")
    currency: str = Field(..., min_length=3, max_length=3, description="3-character currency code, e.g. USD, EUR, INR")

class SimulateRequest(BaseModel):
    idea: str = Field(..., min_length=20, description="Product idea description, minimum 20 characters")
    industry: str = Field(..., description="Industry sector, e.g. SaaS, E-commerce, etc.")
    market: str = Field(..., description="Description of the target market")
    pricing: PricingModel
    region: str = Field(..., description="Target region, e.g. US, EU, India, Global")
    timeline: str = Field(..., description="Target launch timeline")

    @field_validator('industry')
    @classmethod
    def validate_industry(cls, v: str) -> str:
        allowed = ["SaaS", "E-commerce", "FinTech", "Healthtech", "Consumer Hardware", "Other"]
        if v not in allowed:
            raise ValueError(f"Industry must be one of {allowed}")
        return v

    @field_validator('region')
    @classmethod
    def validate_region(cls, v: str) -> str:
        allowed = ["US", "EU", "India", "MENA", "Global"]
        if v not in allowed:
            raise ValueError(f"Region must be one of {allowed}")
        return v

    @field_validator('timeline')
    @classmethod
    def validate_timeline(cls, v: str) -> str:
        allowed = ["<3mo", "3-6mo", "6-12mo", "12mo+"]
        if v not in allowed:
            raise ValueError(f"Timeline must be one of {allowed}")
        return v

class SimulateResponse(BaseModel):
    job_id: str
    status: str

class JobStatusResponse(BaseModel):
    status: str
    progress: int
    current_stage: str
    error: Optional[str] = None

class PersonaResponse(BaseModel):
    id: str
    name: str
    age: int
    income_bracket: str
    occupation: str
    location: str
    buying_behavior: str
    goals: List[str]
    objections: List[str]
    risk_tolerance: str
    budget_sensitivity: int
    segment: str
    influence: float
    would_buy: bool
    likelihood_score: float
    reasoning: str
    buying_trigger: Optional[str] = ""
    pain_point: Optional[str] = ""
    adoption_probability: Optional[float] = 0.5
    behavior_type: Optional[str] = "Early Adopter"
    technology_comfort: Optional[float] = 50.0
    risk_appetite: Optional[float] = 50.0
    social_influence: Optional[float] = 50.0
    income: Optional[float] = 50000.0
    urgency: Optional[float] = 50.0
    existing_alternatives: Optional[float] = 50.0

class PaginatedPersonasResponse(BaseModel):
    personas: List[PersonaResponse]
    total_count: int
    page: int
    limit: int
