import httpx
import json
import logging
import asyncio
import hashlib
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from backend.app.config import settings
from backend.app.services.mock_fixtures import (
    generate_mock_signals,
    generate_mock_archetypes,
    generate_mock_simulations,
    generate_mock_report
)

logger = logging.getLogger("aura.external_apis")

# Pydantic schemas for Structured Output
class ExtractedSignals(BaseModel):
    complaints: List[str] = Field(description="List of user pain points and complaints.")
    demands: List[str] = Field(description="List of features and capabilities users are asking for.")
    competitors: List[str] = Field(description="Competitor products or brands mentioned.")
    market_sentiment_score: float = Field(description="Overall sentiment score between -1.0 (very negative) and 1.0 (very positive).")
    market_sentiment_summary: str = Field(description="Brief summary explaining the market sentiment.")
    
    # Discovery metrics
    market_strength: float = Field(description="Overall market demand strength score from 0.0 to 1.0.")
    competitive_density: float = Field(description="Competitive density score from 0.0 to 1.0.")
    market_maturity: str = Field(description="Market maturity classification: Low, Moderate, High.")
    confidence: float = Field(description="Data confidence score from 0.0 to 1.0 based on source quality.")

class ArchetypeDefinition(BaseModel):
    """Layer 1: LLM-generated persona archetype with numeric traits only."""
    name: str = Field(description="Persona label, e.g. 'Price Sensitive Student'.")
    segment: str = Field(description="Market segment cluster name.")
    occupation: str = Field(description="Typical occupation for this archetype.")
    budget: float = Field(description="Budget capacity 1 (very constrained) to 12 (high budget).")
    risk: float = Field(description="Risk tolerance 0.0 to 1.0.")
    social_influence: float = Field(description="Social influence 0.0 to 1.0.")
    tech_comfort: float = Field(description="Technology comfort 0.0 to 1.0.")
    price_elasticity: float = Field(description="Price sensitivity elasticity 0.0 to 1.0.")
    switching_cost: float = Field(description="Perceived switching cost 0.0 to 1.0.")
    population_weight: float = Field(description="Relative population share weight (e.g. 0.5 to 2.0).")
    objections: List[str] = Field(description="1-2 likely objections for this archetype.")

class ArchetypeDefinitionsResponse(BaseModel):
    archetypes: List[ArchetypeDefinition] = Field(description="Exactly 15 distinct persona archetypes.")

class ArchetypePersona(BaseModel):
    name: str = Field(description="Full name of the persona.")
    age: int = Field(description="Age of the persona.")
    income_bracket: str = Field(description="Income bracket, e.g. '$50k - $80k'.")
    occupation: str = Field(description="Occupation.")
    location: str = Field(description="Location, e.g. 'San Francisco, US'.")
    buying_behavior: str = Field(description="Description of buying habits.")
    goals: List[str] = Field(description="Primary goals.")
    objections: List[str] = Field(description="Primary objections or hesitations.")
    risk_tolerance: str = Field(description="Risk tolerance: low, medium, or high.")
    budget_sensitivity: int = Field(description="Budget sensitivity rating from 1 (unconcerned) to 10 (highly sensitive).")
    segment: str = Field(description="Category/cluster name for this persona group.")
    influence: float = Field(description="Influence score from 0.0 to 1.0.")
    
    # Enriched fields
    buying_trigger: str = Field(description="Specific event or value that triggers a purchase decision.")
    pain_point: str = Field(description="The primary day-to-day struggle or pain point.")
    adoption_probability: float = Field(description="Baseline probability of adopting the product (0.0 to 1.0).")
    behavior_type: str = Field(description="Classification: Early Adopter, Risk Avoider, Price Sensitive, or Feature Maximizer.")
    technology_comfort: float = Field(description="Technology comfort score from 0.0 to 100.0.")
    risk_appetite: float = Field(description="Risk appetite score from 0.0 to 100.0.")
    social_influence: float = Field(description="Social influence score from 0.0 to 100.0.")
    income: float = Field(description="Estimated annual income of this persona in local currency.")
    urgency: float = Field(description="Urgency of finding a solution from 0.0 to 100.0.")
    existing_alternatives: float = Field(description="How satisfied they are with existing alternatives from 0.0 to 100.0.")

class ArchetypePersonasResponse(BaseModel):
    personas: List[ArchetypePersona] = Field(description="List of generated persona archetypes.")

class SimulationResponse(BaseModel):
    would_buy: bool = Field(description="Whether this persona would purchase the product.")
    excitement_score: int = Field(description="Excitement score from 0 (indifferent) to 10 (extremely excited).")
    objections: List[str] = Field(description="Objections this persona raised during review.")
    likelihood_score: float = Field(description="Calculated likelihood of purchasing (0.0 to 1.0).")
    reasoning: str = Field(description="First-person explanation of why they would or would not buy it.")

class ForecastAddressableMarket(BaseModel):
    addressable_market_size: int = Field(description="Estimated number of customers in target region.")
    confidence_score: int = Field(description="Confidence rating of the estimate (0 to 100).")


class TAMEstimation(BaseModel):
    """Total Addressable Market estimation with justified reasoning."""
    tam_estimate: int = Field(
        ..., gt=0,
        description="Estimated number of potential customers in the addressable market. Must be justified by reasoning, not a round guess."
    )
    tam_reasoning: str = Field(
        ..., min_length=50,
        description="Detailed justification for the TAM estimate. Should reference population, segment penetration, geography, etc."
    )
    tam_confidence: str = Field(
        ..., pattern="^(low|medium|high)$",
        description="Confidence level in the TAM estimate: low, medium, or high."
    )


class CompetitorItem(BaseModel):
    name: str = Field(..., min_length=1, description="Real company or product name, not a placeholder")
    why_relevant: str = Field(..., min_length=10, description="1-2 sentence explanation of relevance")
    positioning: str = Field(..., min_length=10, description="How this competitor differs from the product idea")


class CompetitorExtraction(BaseModel):
    """Real, named competitors extracted from market signals."""
    competitors: List[CompetitorItem] = Field(
        ..., min_items=1, max_items=8,
        description="List of real, named competitors. Names MUST be real companies/products that actually exist."
    )


class CustomerQuoteItem(BaseModel):
    quote: str = Field(..., min_length=30, description="1-3 sentences customer quote referencing concrete product/price details")
    sentiment: str = Field(..., pattern="^(positive|mixed|negative)$", description="Sentiment of the quote")
    persona_segment: str = Field(..., min_length=3, description="Segment of the persona, e.g. Innovators")


class CustomerQuotesResponse(BaseModel):
    customer_quotes: List[CustomerQuoteItem] = Field(..., min_items=6, max_items=8, description="6 to 8 realistic customer quotes.")


class RiskItem(BaseModel):
    risk: str = Field(..., min_length=20, description="Specific risk description advising the founder")
    severity: str = Field(..., pattern="^(low|medium|high)$", description="Severity level")
    mitigation: str = Field(..., min_length=20, description="Actionable mitigation strategy")


class ReportBriefingResponse(BaseModel):
    executive_summary: str = Field(..., min_length=200, description="A 3-paragraph strategic brief for the founder. Do not mention AURA or synthetic personas.")
    launch_recommendation: str = Field(..., min_length=50, description="Recommended action (e.g., Proceed, Delay or Pivot).")
    launch_rationale: str = Field(..., min_length=100, description="Strategic rationale advising the founder on why this recommendation is given.")
    risk_analysis: List[RiskItem] = Field(..., min_items=3, max_items=3, description="List of exactly 3 primary risks with severity and mitigation.")


class ReportSynthesis(BaseModel):
    executive_summary: str = Field(description="Concise synthesis of simulation findings (MUST BE UNDER 150 WORDS).")
    opportunity_score: int = Field(description="Overall opportunity score (0 to 100).")
    opportunity_label: str = Field(description="Opportunity classification: Strong, Moderate, or Weak.")
    launch_recommendation: str = Field(description="Strategic advice: Launch, Pivot, Delay, or Kill.")
    launch_rationale: str = Field(description="Rationale for the recommendation.")
    customer_quotes: List[str] = Field(description="5-8 realistic quotes drawn from simulated persona reasoning.")
    pricing_recommendation: str = Field(description="Strategic pricing suggestions.")
    go_to_market_strategy: List[str] = Field(description="3-5 specific execution steps.")
    
    # Enriched reporting structures
    signal_intelligence: Dict[str, Any] = Field(description="Step 2: Demand Momentum, Competitive Saturation, Customer Friction, Novelty Score, Economic Sensitivity. Format: {card_id: {metric: int, explanation: str, confidence: str, trend: 'up'|'down'|'stable', sources: list}}")
    buyer_journey: Dict[str, Any] = Field(description="Step 4: awareness, interest, evaluation, trial, purchase, retention. Format: {stage_id: {count: int, conversion_percentage: float, drop_reason: str}}")
    simulated_conversations: List[Dict[str, Any]] = Field(description="Step 5: list of conversation bubbles. Each: {role: str, text: str, sentiment: 'positive'|'neutral'|'negative'}")
    competitors_battle: Dict[str, Any] = Field(description="Step 8: trust, price, features, switching_cost, adoption comparisons with competitor A and B.")
    confidence_details: Dict[str, Any] = Field(description="Step 9: signal, persona, and forecast confidence details with reasoning.")
    objections_list: List[Dict[str, Any]] = Field(description="Step 7: objections list containing issue, severity, affected_users, revenue_loss, action.")

    # Market Friction Model Metrics
    launch_difficulty: float = Field(description="Calculated Launch Difficulty Score (0.0 to 100.0).")
    price_friction: float = Field(description="Price friction score (0.0 to 100.0).")
    social_friction: float = Field(description="Social friction score (0.0 to 100.0).")
    behavior_change_cost: float = Field(description="Behavior change cost score (0.0 to 100.0).")
    trust_requirement: float = Field(description="Trust requirement score (0.0 to 100.0).")
    infrastructure_requirement: float = Field(description="Infrastructure requirement score (0.0 to 100.0).")
    switching_cost: float = Field(description="Switching cost score (0.0 to 100.0).")
    time_to_value: float = Field(description="Time to value score (0.0 to 100.0).")
    novelty_penalty: float = Field(description="Novelty penalty score (0.0 to 100.0).")
    education_cost: float = Field(description="Education cost score (0.0 to 100.0).")
    product_market_fit: float = Field(description="Product Market Fit score (0.0 to 100.0).")
    social_adoption: float = Field(description="Social adoption score (0.0 to 100.0).")
    price_acceptance: float = Field(description="Price acceptance score (0.0 to 100.0).")
    trust_barrier: float = Field(description="Trust barrier score (0.0 to 100.0).")
    habit_change_required: float = Field(description="Habit change required score (0.0 to 100.0).")

# Gemini 2.5 Flash API Async Client Helper (drop-in replacement)
GEMINI_API_LOCK = None
LAST_REQUEST_TIME = 0.0

async def call_openai_structured(prompt: str, response_format: Any) -> Optional[Any]:
    global LAST_REQUEST_TIME, GEMINI_API_LOCK
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY is missing. Falling back to synthetic generators.")
        return None
    
    import asyncio
    import re
    import time
    
    logger.info(f"call_openai_structured START: prompt_len={len(prompt)} | response_format={response_format.__name__}")
    
    if GEMINI_API_LOCK is None:
        GEMINI_API_LOCK = asyncio.Lock()
        
    # Pacing check to stay under 5 RPM limit
    async with GEMINI_API_LOCK:
        now = time.time()
        elapsed = now - LAST_REQUEST_TIME
        if elapsed < 13.0:
            sleep_time = 13.0 - elapsed
            logger.info(f"Rate limiter: sleeping {sleep_time:.2f}s to respect the 5 RPM limit...")
            await asyncio.sleep(sleep_time)
        LAST_REQUEST_TIME = time.time()
    
    max_retries = 10
    for attempt in range(max_retries):
        if attempt > 0:
            async with GEMINI_API_LOCK:
                now = time.time()
                elapsed = now - LAST_REQUEST_TIME
                if elapsed < 13.0:
                    sleep_time = 13.0 - elapsed
                    await asyncio.sleep(sleep_time)
                LAST_REQUEST_TIME = time.time()
        try:
            # Enforce structured format by passing Pydantic json schema in prompt
            schema_json = json.dumps(response_format.model_json_schema())
            gemini_prompt = f"""
            System Instruction: You are a market research analyst. Return only structured JSON data about the product being analyzed — never describe yourself or the simulation platform.
            
            {prompt}
            
            CRITICAL NFR: You must return your response in JSON format.
            The JSON structure MUST conform strictly to the following JSON Schema:
            {schema_json}
            """
            
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            
            headers = {"Content-Type": "application/json"}
            payload = {
                "contents": [{
                    "parts": [{
                        "text": gemini_prompt
                    }]
                }],
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "temperature": 0.7,
                    "maxOutputTokens": 8192
                }
            }
            
            logger.info(f"call_openai_structured: HTTP POST URL='{url[:80]}...' | timeout=45.0s | attempt={attempt+1}/{max_retries}")
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(url, json=payload, headers=headers)
            logger.info(f"call_openai_structured: HTTP POST COMPLETE. Status={res.status_code}")
                
            # Check for rate limits (429)
            if res.status_code == 429:
                delay = 30.0
                try:
                    err_data = res.json()
                    delay_str = None
                    for detail in err_data.get("error", {}).get("details", []):
                        if detail.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                            delay_str = detail.get("retryDelay")
                            break
                    if delay_str and delay_str.endswith("s"):
                        delay = float(delay_str[:-1])
                    else:
                        msg = err_data.get("error", {}).get("message", "")
                        match = re.search(r"retry in ([\d\.]+)s", msg)
                        if match:
                            delay = float(match.group(1))
                except Exception:
                    pass
                # Add buffer
                delay = max(delay + 1.0, 5.0)
                logger.warning(f"Gemini API rate limited (429). Retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})...")
                await asyncio.sleep(delay)
                continue
            
            if res.status_code != 200:
                logger.error(f"Gemini API returned error code {res.status_code}: {res.text}")
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    logger.warning(f"Retrying in {backoff}s due to non-200 status code...")
                    await asyncio.sleep(backoff)
                    continue
                logger.info("call_openai_structured COMPLETE: FAILED")
                return None
                
            data = res.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.error("Gemini returned empty candidates list.")
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    await asyncio.sleep(backoff)
                    continue
                logger.info("call_openai_structured COMPLETE: FAILED")
                return None
                
            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            if not text:
                logger.error("Gemini returned empty text content.")
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt
                    await asyncio.sleep(backoff)
                    continue
                logger.info("call_openai_structured COMPLETE: FAILED")
                return None
                
            parsed = response_format.model_validate_json(text.strip())
            logger.info("call_openai_structured COMPLETE: SUCCESS")
            return parsed
        except Exception as e:
            logger.error(f"Gemini API execution error (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                backoff = 2 ** attempt
                logger.warning(f"Retrying in {backoff}s due to exception: {e}")
                await asyncio.sleep(backoff)
                continue
            logger.info("call_openai_structured COMPLETE: FAILED")
            return None

# Reddit JSON API Client
async def fetch_reddit_signals(query: str, industry: str) -> List[Dict[str, Any]]:
    logger.info(f"fetch_reddit_signals START: query='{query[:30]}...', industry={industry}")
    # Simple search on Reddit via public search endpoint
    subreddits = {
        "SaaS": ["saas", "startups", "technology"],
        "E-commerce": ["ecommerce", "shopify", "dropship"],
        "FinTech": ["fintech", "personalfinance", "investing"],
        "Healthtech": ["healthtech", "medicine", "bioinformatics"],
        "Consumer Hardware": ["hardware", "smarthome", "gadgets"],
        "Other": ["technology", "business", "software"]
    }.get(industry, ["technology", "business"])
    
    posts = []
    headers = {"User-Agent": "AURA/1.0 (market research bot)"}
    logger.info(f"fetch_reddit_signals: Using subreddits {subreddits[:2]} with timeout=10.0s")
    
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            # Search Reddit
            for sub in subreddits[:2]:
                url = f"https://www.reddit.com/r/{sub}/search.json?q={query}&limit=3"
                logger.info(f"fetch_reddit_signals: HTTP GET URL='{url}' | headers={headers} | timeout=10.0s")
                try:
                    res = await client.get(url)
                    logger.info(f"fetch_reddit_signals: HTTP GET COMPLETE. Status={res.status_code}")
                    if res.status_code == 200:
                        data = res.json()
                        children = data.get("data", {}).get("children", [])
                        for child in children:
                            pdata = child.get("data", {})
                            posts.append({
                                "title": pdata.get("title", ""),
                                "text": pdata.get("selftext", "")[:400],
                                "subreddit": sub,
                                "comments_count": pdata.get("num_comments", 0)
                            })
                    else:
                        logger.warning(f"fetch_reddit_signals: Non-200 status code from Reddit r/{sub}: {res.status_code}")
                except Exception as e:
                    logger.warning(f"Error fetching from r/{sub}: {e}")
    except Exception as e:
        logger.error(f"fetch_reddit_signals FAILED: {e}")
        
    logger.info(f"fetch_reddit_signals COMPLETE: fetched {len(posts)} posts")
    return posts

# News API Client (Newsdata.io)
async def fetch_news_signals(query: str) -> List[Dict[str, Any]]:
    logger.info(f"fetch_news_signals START: query='{query[:30]}...'")
    if not settings.NEWS_API_KEY:
        logger.warning("fetch_news_signals: NEWS_API_KEY missing, returning empty")
        return []
    
    # Simple query extraction
    simple_query = " ".join(query.split()[:3])
    url = f"https://newsdata.io/api/1/news?apikey={settings.NEWS_API_KEY}&q={simple_query}&language=en"
    articles = []
    logger.info(f"fetch_news_signals: Fetching from Newsdata.io with timeout=10.0s")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.info(f"fetch_news_signals: HTTP GET URL='{url[:60]}...' | timeout=10.0s")
            res = await client.get(url)
            logger.info(f"fetch_news_signals: HTTP GET COMPLETE. Status={res.status_code}")
            if res.status_code == 200:
                data = res.json()
                for art in data.get("results", [])[:5]:
                    articles.append({
                        "title": art.get("title", ""),
                        "description": art.get("description", "") or art.get("content", "")[:300],
                        "source": art.get("source_id", "News")
                    })
            else:
                logger.warning(f"fetch_news_signals: Non-200 status code from Newsdata: {res.status_code}")
    except Exception as e:
        logger.warning(f"Newsdata API fetch error: {e}")
        
    logger.info(f"fetch_news_signals COMPLETE: fetched {len(articles)} articles")
    return articles

# Tavily Search API Client
async def fetch_tavily_signals(query: str) -> List[Dict[str, Any]]:
    logger.info(f"fetch_tavily_signals START: query='{query[:30]}...'")
    if not settings.TAVILY_API_KEY:
        logger.warning("fetch_tavily_signals: TAVILY_API_KEY missing, returning empty")
        return []
    
    url = "https://api.tavily.com/search"
    results = []
    logger.info(f"fetch_tavily_signals: Fetching from Tavily API with timeout=10.0s")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            logger.info(f"fetch_tavily_signals: HTTP POST URL='{url}' | timeout=10.0s")
            res = await client.post(url, json={
                "api_key": settings.TAVILY_API_KEY,
                "query": query,
                "max_results": 5
            })
            logger.info(f"fetch_tavily_signals: HTTP POST COMPLETE. Status={res.status_code}")
            if res.status_code == 200:
                data = res.json()
                for item in data.get("results", []):
                    results.append({
                        "title": item.get("title", ""),
                        "description": item.get("content", ""),
                        "source": "tavily"
                    })
            else:
                logger.warning(f"fetch_tavily_signals: Non-200 status code from Tavily: {res.status_code}")
    except Exception as e:
        logger.warning(f"Tavily fetch error: {e}")
    logger.info(f"fetch_tavily_signals COMPLETE: fetched {len(results)} results")
    return results

# Google Trends Client
async def fetch_google_trends(query: str, region: str) -> Dict[str, Any]:
    logger.info(f"fetch_google_trends START: query='{query[:30]}...', region={region}")
    # pytrends is blocking and relies on urllib, so we run it in executor to avoid blocking the async event loop.
    def get_trends():
        logger.info(f"fetch_google_trends (executor) START: hl='en-US', tz=360, timeout=10s")
        try:
            from pytrends.request import TrendReq
            pytrends = TrendReq(hl='en-US', tz=360, timeout=10)
            logger.info(f"fetch_google_trends (executor): pytrends initialized")
            
            geo_code = {
                "US": "US",
                "EU": "EU",
                "India": "IN",
                "MENA": "AE",
                "Global": ""
            }.get(region, "")
            
            # Use query first 30 chars
            keywords = [query[:30]]
            logger.info(f"fetch_google_trends (executor): Building payload for keywords={keywords}, geo={geo_code}")
            pytrends.build_payload(keywords, timeframe='today 12-m', geo=geo_code)
            logger.info(f"fetch_google_trends (executor): Payload built, fetching interest_over_time")
            df = pytrends.interest_over_time()
            logger.info(f"fetch_google_trends (executor): interest_over_time fetched, df.empty={df.empty}")
            if not df.empty:
                # Return data as dict
                dates = [str(d.date()) for d in df.index]
                values = [int(v) for v in df.iloc[:, 0]]
                logger.info(f"fetch_google_trends (executor) COMPLETE: Returning {len(dates)} data points")
                return {"dates": dates, "values": values}
        except Exception as e:
            logger.warning(f"Google Trends fetch failed in executor: {e}")
        return {}
        
    try:
        loop = asyncio.get_event_loop()
        logger.info(f"fetch_google_trends: Running get_trends in executor with 15s timeout")
        result = await asyncio.wait_for(loop.run_in_executor(None, get_trends), timeout=15.0)
        logger.info(f"fetch_google_trends COMPLETE: returned {len(result.get('dates', []))} data points")
        return result
    except asyncio.TimeoutError:
        logger.error("fetch_google_trends TIMEOUT after 15s")
        return {}
    except Exception as e:
        logger.error(f"fetch_google_trends FAILED: {e}")
        return {}
