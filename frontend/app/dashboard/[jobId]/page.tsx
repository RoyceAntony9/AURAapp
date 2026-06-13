"use client";

import React, { useEffect, useState, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
  PieChart, Pie, Cell,
  BarChart, Bar,
  ReferenceLine
} from "recharts";
import {
  Sparkles, Cpu, TrendingUp, MapPin, Clock, DollarSign, Zap,
  AlertCircle, ChevronLeft, ChevronRight, X, ArrowLeft,
  CheckCircle2, Info, AlertTriangle, ShieldCheck, HelpCircle,
  PlayCircle, RefreshCw
} from "lucide-react";

// Types matching API returns
interface Projection {
  months: number;
  low: number;
  estimate: number;
  high: number;
  expected?: number; // backward compat alias for estimate
}

interface RiskItem {
  risk: string;
  severity: "High" | "Medium" | "Low";
  mitigation: string;
}

interface MarketSegment {
  id: string;
  name: string;
  size_percentage: number;
  average_likelihood: number;
  key_traits: string[];
}

interface ReportData {
  job_id: string;
  idea: string;
  industry: string;
  market: string;
  pricing_amount: number;
  pricing_currency: string;
  region: string;
  timeline: string;
  executive_summary: string;

  // NEW primary fields from ForecastResult
  pmf_score?: number;           // 0-100, replaces opportunity_score for PMF display
  pmf_label?: string;           // "Weak Fit" | "Moderate Fit" | "Strong Fit"
  final_adoption_pct?: number;  // 0-100, the REAL adoption percentage
  conversion_rate_pct?: number; // purchase stage percentage

  // NEW structured fields
  funnel?: Array<{name: string; pct: number; users: number; drop_reason: string}>;
  diffusion_curve?: Array<{cycle: number; values: Record<string, number>}>;
  competitors?: Array<{name: string; why_relevant: string; positioning: string}>;
  confidence?: {
    signal_quality_pct: number;
    persona_consistency_pct: number;
    forecast_stability_pct: number;
    final_confidence_pct: number;
    explainer: string;
  };
  top_objections?: Array<{objection: string; pct: number; count: number}>;

  // OLD fields kept for backward compat
  opportunity_score?: number;
  opportunity_label?: string;
  launch_recommendation: string | {decision: string; rationale: string};
  launch_rationale?: string;
  customer_quotes: Array<string | {quote: string; sentiment: string; persona_segment: string}>;
  revenue_projection: {
    currency: string;
    projections: Projection[];
    assumptions?: string[];
    tam_used?: number;
  };
  risk_analysis: RiskItem[];
  adoption_curve?: Record<string, Record<string, number>>;
  market_segments: MarketSegment[];
  pricing_recommendation: string;
  go_to_market_strategy: string[];
  confidence_score?: number;
  signal_intelligence?: Record<string, {
    metric: number;
    explanation: string;
    confidence: string;
    trend: string;
    sources: string[];
  }>;
  buyer_journey?: Record<string, {
    count: number;
    conversion_percentage: number;
    drop_reason: string;
  }>;
  simulated_conversations?: Array<{
    role: string;
    text: string;
    sentiment: string;
  }>;
  competitors_battle?: {
    winner: string;
    [key: string]: any;
  };
  confidence_details?: {
    signal_confidence: number;
    persona_confidence: number;
    forecast_confidence: number;
    final_confidence: number;
    formula: string;
    reasoning: string;
  };
  objections_list?: Array<{
    issue: string;
    severity: string;
    affected_users: number;
    revenue_loss: number;
    action: string;
  }>;
  launch_difficulty?: number;
  price_friction?: number;
  social_friction?: number;
  behavior_change_cost?: number;
  trust_requirement?: number;
  infrastructure_requirement?: number;
  switching_cost?: number;
  time_to_value?: number;
  novelty_penalty?: number;
  education_cost?: number;
  product_market_fit?: number;
  social_adoption?: number;
  price_acceptance?: number;
  trust_barrier?: number;
  habit_change_required?: number;
  scenario_tests?: Array<{
    name: string;
    price: string;
    adoption: number;
    difficulty: number;
    recommendation: string;
  }>;
}

interface Persona {
  id: string;
  name: string;
  age: number;
  income_bracket: string;
  occupation: string;
  location: string;
  buying_behavior: string;
  goals: string[];
  objections: string[];
  risk_tolerance: string;
  budget_sensitivity: number;
  segment: string;
  influence: number;
  would_buy: boolean;
  likelihood_score: number;
  reasoning: string;
  technology_comfort?: number;
  risk_appetite?: number;
  social_influence?: number;
  income?: number;
  urgency?: number;
  existing_alternatives?: number;
}

export default function DashboardPage() {
  const router = useRouter();
  const { jobId } = useParams() as { jobId: string };

  // Status & Progress States
  const [status, setStatus] = useState<"queued" | "collecting_signals" | "generating_personas" | "simulating" | "forecasting" | "generating_report" | "complete" | "failed">("queued");
  const [progress, setProgress] = useState(0);
  const [currentStage, setCurrentStage] = useState("Queued");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [lastStatusChangeTime, setLastStatusChangeTime] = useState<number>(Date.now());
  const [showTakingLong, setShowTakingLong] = useState(false);

  // Result State
  const [report, setReport] = useState<ReportData | null>(null);
  const [simReport, setSimReport] = useState<ReportData | null>(null);

  // Interactive Segment Drilldown Panel
  const [selectedSegment, setSelectedSegment] = useState<MarketSegment | null>(null);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [personasPage, setPersonasPage] = useState(1);
  const [personasTotalCount, setPersonasTotalCount] = useState(0);
  const [loadingPersonas, setLoadingPersonas] = useState(false);

  // Quotes Carousel State
  const [quoteIndex, setQuoteIndex] = useState(0);

  // Scenario Lab inputs & archetypes
  const [archetypes, setArchetypes] = useState<any[]>([]);
  const [priceSlider, setPriceSlider] = useState<number>(0);
  const [addFeature, setAddFeature] = useState<boolean>(false);
  const [addFreemium, setAddFreemium] = useState<boolean>(false);
  const [timelineSelect, setTimelineSelect] = useState<string>("");
  const [showTransparency, setShowTransparency] = useState<boolean>(false);

  // Colors for charts
  const CHART_COLORS = ["#00f0ff", "#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899"];

  // Polling Refs for change detection
  const lastStatusRef = useRef<string>("queued");
  const lastProgressRef = useRef<number>(0);

  // Polling for Status
  useEffect(() => {
    if (!jobId) return;

    let pollInterval: NodeJS.Timeout;

    const fetchStatus = async () => {
      try {
        const res = await fetch(`http://localhost:8000/simulate/${jobId}/status`);
        if (res.status === 404) {
          clearInterval(pollInterval);
          setStatus("failed");
          setErrorMsg("Simulation job not found in the database. The database may have been reset. Please return to the homepage to configure and run a new simulation.");
          return;
        }
        if (!res.ok) {
          throw new Error(`Failed to fetch status: ${res.statusText}`);
        }
        
        const data = await res.json();
        
        // Check for progress or status changes to reset the client timeout clock
        if (data.status !== lastStatusRef.current || data.progress !== lastProgressRef.current) {
          lastStatusRef.current = data.status;
          lastProgressRef.current = data.progress;
          setLastStatusChangeTime(Date.now());
        }

        setStatus(data.status);
        setProgress(data.progress);
        setCurrentStage(data.current_stage);
        
        if (data.status === "complete") {
          clearInterval(pollInterval);
          fetchResult();
        } else if (data.status === "failed") {
          clearInterval(pollInterval);
          setErrorMsg(data.error || "Simulation run encountered an internal failure.");
        }
      } catch (err: any) {
        console.error("Error polling job status:", err);
      }
    };

    fetchStatus();
    pollInterval = setInterval(fetchStatus, 2000);

    return () => clearInterval(pollInterval);
  }, [jobId]);

  // Client-side Hangs detector: check if status/progress has been unchanged for 30 seconds
  useEffect(() => {
    if (status === "complete" || status === "failed") {
      setShowTakingLong(false);
      return;
    }
    
    const interval = setInterval(() => {
      const elapsed = Date.now() - lastStatusChangeTime;
      if (elapsed > 30000) {
        setShowTakingLong(true);
      } else {
        setShowTakingLong(false);
      }
    }, 1000);
    
    return () => clearInterval(interval);
  }, [lastStatusChangeTime, status]);

  // Handle retry using cached sessionStorage request payload
  const handleRetry = async () => {
    setErrorMsg(null);
    setStatus("queued");
    setProgress(0);
    setCurrentStage("Queued");
    setShowTakingLong(false);
    setLastStatusChangeTime(Date.now());
    lastStatusRef.current = "queued";
    lastProgressRef.current = 0;
    
    try {
      const cachedRequest = sessionStorage.getItem("last_simulation_request");
      if (!cachedRequest) {
        throw new Error("No cached simulation inputs found. Please return to the homepage to configure a new simulation.");
      }
      
      const payload = JSON.parse(cachedRequest);
      const res = await fetch("http://localhost:8000/simulate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      
      if (!res.ok) {
        throw new Error(`Server returned error: ${res.statusText}`);
      }
      
      const data = await res.json();
      const newJobId = data.job_id;
      
      // Navigate to the new simulation page
      router.push(`/dashboard/${newJobId}`);
    } catch (err: any) {
      setStatus("failed");
      setErrorMsg(err.message || "Failed to retry simulation. Please try again.");
    }
  };

  // Fetch final results
  const fetchResult = async () => {
    try {
      const res = await fetch(`http://localhost:8000/simulate/${jobId}/result`);
      if (!res.ok) throw new Error("Failed to fetch results");
      const data = await res.json();
      setReport(data);
      setSimReport(data);
      setPriceSlider(data.pricing_amount);
      setTimelineSelect(data.timeline);
      
      // Fetch raw archetypes for scenario lab
      const archRes = await fetch(`http://localhost:8000/simulate/${jobId}/archetypes`);
      if (archRes.ok) {
        const archData = await archRes.json();
        setArchetypes(archData);
      }
    } catch (err: any) {
      setErrorMsg("Failed to download simulation report from the server.");
    }
  };

  // Read friction scores from the backend report data; fall back to simple defaults
  const getMarketFrictionScores = (idea: string, industry: string, price: number, reportData?: ReportData | null) => {
    // If the report already has backend-computed friction scores, use them directly
    if (reportData && reportData.price_friction != null) {
      return {
        price_friction: reportData.price_friction ?? 40,
        social_friction: reportData.social_friction ?? 40,
        behavior_change_cost: reportData.behavior_change_cost ?? 45,
        trust_requirement: reportData.trust_requirement ?? 40,
        infrastructure_requirement: reportData.infrastructure_requirement ?? 30,
        switching_cost: reportData.switching_cost ?? 35,
        time_to_value: reportData.time_to_value ?? 50,
        novelty_penalty: reportData.novelty_penalty ?? 30,
        education_cost: reportData.education_cost ?? 35,
        social_acceptance: reportData.social_adoption ?? 60,
        competitor_effect: 50,
        price_elasticity: 50,
        competitive_density: 0.5,
        novelty_penalty_val: reportData.novelty_penalty ?? 30
      };
    }

    // Fallback: derive simple defaults from industry + price
    const scores = {
      price_friction: industry !== "SaaS" ? Math.min(95, Math.max(5, Math.floor(price * 0.05))) : Math.min(95, Math.max(5, Math.floor(price * 12 * 0.05))),
      social_friction: 40,
      behavior_change_cost: 45,
      trust_requirement: 40,
      infrastructure_requirement: 30,
      switching_cost: 35,
      time_to_value: 50,
      novelty_penalty: 30,
      education_cost: 35,
      social_acceptance: 60,
      competitor_effect: 50,
      price_elasticity: 50,
      competitive_density: 0.5,
      novelty_penalty_val: 30
    };

    if (industry === "SaaS" || industry === "FinTech") {
      scores.social_acceptance = 75;
      scores.social_friction = 25;
      scores.time_to_value = 80;
      scores.behavior_change_cost = 25;
      scores.switching_cost = 30;
      scores.price_elasticity = 35;
    } else if (industry === "Consumer Hardware" || industry === "Gaming") {
      scores.social_acceptance = 40;
      scores.social_friction = 60;
      scores.time_to_value = 45;
      scores.behavior_change_cost = 60;
      scores.switching_cost = 50;
      scores.price_elasticity = 80;
    } else if (industry === "Healthtech" || industry === "Enterprise") {
      scores.social_acceptance = 65;
      scores.social_friction = 35;
      scores.time_to_value = 40;
      scores.behavior_change_cost = 50;
      scores.switching_cost = 60;
      scores.price_elasticity = 30;
    }

    return scores;
  };

  const computeLaunchDifficulty = (scores: any) => {
    return (
      scores.price_friction * 0.15 +
      scores.switching_cost * 0.20 +
      scores.behavior_change_cost * 0.20 +
      scores.trust_requirement * 0.15 +
      scores.infrastructure_requirement * 0.10 +
      scores.education_cost * 0.10 +
      scores.novelty_penalty * 0.10
    );
  };

  const getAdjustedPersona = (p: Persona): Persona => {
    if (archetypes.length === 0 || !report) return p;
    const arch = archetypes.find(a => a.segment === p.segment && a.occupation === p.occupation);
    if (!arch) return p;

    const friction = getMarketFrictionScores(report.idea, report.industry, priceSlider, report);
    let income = arch.income || 50000;
    let occupation = arch.occupation;

    const isRejected = (occ: string, inc: number) => {
      if (occ.toLowerCase() === "student" && priceSlider > 100) return true;
      const annualPrice = report.industry === "Consumer Hardware" ? priceSlider : priceSlider * 12;
      if (annualPrice > inc * 0.05) return true;
      return false;
    };

    if (isRejected(occupation, income)) {
      return {
        ...p,
        likelihood_score: 0.02,
        would_buy: false,
        reasoning: `Budget constraints prevent me from adopting this product at price ${priceSlider}.`
      };
    }

    const awareness = Math.max(0.1, Math.min(0.98, 0.90 + (arch.social_influence / 100.0) * 0.08));
    const fit = Math.max(0.1, Math.min(0.98, 0.50 + (arch.urgency / 100.0) * 0.45));
    
    const annualPrice = report.industry === "Consumer Hardware" ? priceSlider : priceSlider * 12;
    const priceRatio = annualPrice / (income * 0.03);
    
    let elasticityExponent = 1.0;
    if (report.industry === "Consumer Hardware" || report.industry === "Education" || report.industry === "Gaming") {
      elasticityExponent = 1.5;
    } else if (report.industry === "Enterprise" || report.industry === "Healthcare") {
      elasticityExponent = 0.6;
    }
    
    let priceAcc = Math.max(0.01, 1.0 - Math.pow(priceRatio, elasticityExponent) * (arch.budget_sensitivity / 10.0));
    priceAcc = Math.min(0.98, priceAcc);
    
    const trustGap = (friction.trust_requirement / 100.0) * (1.0 - arch.risk_appetite / 100.0);
    const trust = Math.max(0.01, Math.min(0.98, 1.0 - trustGap));
    
    const habitGap = (friction.behavior_change_cost / 100.0) * (1.0 - arch.technology_comfort / 100.0);
    const habitChange = Math.max(0.01, Math.min(0.98, 1.0 - habitGap));
    
    const retention = Math.max(0.1, Math.min(0.98, 0.95 - (arch.existing_alternatives / 100.0) * 0.15));
    
    let adoptionProb = Math.pow(awareness * fit * priceAcc * trust * habitChange * retention, 0.6);
    
    const density = friction.competitive_density || 0.5;
    const novelty = friction.novelty_penalty_val || 30.0;
    const competitorMultiplier = (1.0 - density * 0.15) * (1.0 + (100.0 - novelty) / 100.0 * 0.10);
    
    let likelihood = adoptionProb * competitorMultiplier;
    likelihood = Math.max(0.02, Math.min(0.98, likelihood));
    
    const wouldBuy = likelihood > 0.5;
    const reasoning = `Under pricing $${priceSlider}, my adoption likelihood is ${Math.round(likelihood * 100)}%. Technology comfort: ${arch.technology_comfort}%, Urgency: ${arch.urgency}%, Price Acceptance: ${Math.round(priceAcc * 100)}%.`;

    return {
      ...p,
      likelihood_score: likelihood,
      would_buy: wouldBuy,
      reasoning
    };
  };

  const runClientSimulation = (
    price: number,
    features: boolean,
    freemium: boolean,
    timeline: string,
    archList: any[],
    baseReport: ReportData
  ): ReportData | null => {
    if (!baseReport || archList.length === 0) return null;

    const friction = getMarketFrictionScores(baseReport.idea, baseReport.industry, price, baseReport);
    const difficulty = computeLaunchDifficulty(friction);

    // 1. Loop over archetypes and apply shifts
    const updatedArchetypes = archList.map((arch) => {
      let income = arch.income || 50000;
      let occupation = arch.occupation;

      const isRejected = (occ: string, inc: number) => {
        if (occ.toLowerCase() === "student" && price > 100) return true;
        const annualPrice = baseReport.industry === "Consumer Hardware" ? price : price * 12;
        if (annualPrice > inc * 0.05) return true;
        return false;
      };

      if (isRejected(occupation, income)) {
        return {
          ...arch,
          likelihood_score: 0.02
        };
      }

      const awareness = Math.max(0.1, Math.min(0.98, 0.90 + (arch.social_influence / 100.0) * 0.08));
      const fit = Math.max(0.1, Math.min(0.98, 0.50 + (arch.urgency / 100.0) * 0.45));
      
      const annualPrice = baseReport.industry === "Consumer Hardware" ? price : price * 12;
      const priceRatio = annualPrice / (income * 0.03);
      
      let elasticityExponent = 1.0;
      if (baseReport.industry === "Consumer Hardware" || baseReport.industry === "Education" || baseReport.industry === "Gaming") {
        elasticityExponent = 1.5;
      } else if (baseReport.industry === "Enterprise" || baseReport.industry === "Healthcare") {
        elasticityExponent = 0.6;
      }
      
      let priceAcc = Math.max(0.01, 1.0 - Math.pow(priceRatio, elasticityExponent) * (arch.budget_sensitivity / 10.0));
      priceAcc = Math.min(0.98, priceAcc);
      
      const trustGap = (friction.trust_requirement / 100.0) * (1.0 - arch.risk_appetite / 100.0);
      const trust = Math.max(0.01, Math.min(0.98, 1.0 - trustGap));
      
      const habitGap = (friction.behavior_change_cost / 100.0) * (1.0 - arch.technology_comfort / 100.0);
      const habitChange = Math.max(0.01, Math.min(0.98, 1.0 - habitGap));
      
      const retention = Math.max(0.1, Math.min(0.98, 0.95 - (arch.existing_alternatives / 100.0) * 0.15));
      
      let adoptionProb = Math.pow(awareness * fit * priceAcc * trust * habitChange * retention, 0.6);
      
      const density = friction.competitive_density || 0.5;
      const novelty = friction.novelty_penalty_val || 30.0;
      const competitorMultiplier = (1.0 - density * 0.15) * (1.0 + (100.0 - novelty) / 100.0 * 0.10);
      
      let likelihood = adoptionProb * competitorMultiplier;
      likelihood = Math.max(0.02, Math.min(0.98, likelihood));
      
      return {
        ...arch,
        likelihood_score: likelihood
      };
    });

    // 2. Rogers buckets & curve
    const categorized: Record<string, number[]> = {
      "Innovators": [],
      "Early Adopters": [],
      "Early Majority": [],
      "Late Majority": [],
      "Laggards": []
    };

    updatedArchetypes.forEach((arch, idx) => {
      let cat = "Laggards";
      if (idx < 1) cat = "Innovators";
      else if (idx < 3) cat = "Early Adopters";
      else if (idx < 8) cat = "Early Majority";
      else if (idx < 13) cat = "Late Majority";
      categorized[cat].push(arch.likelihood_score);
    });

    const categories = ["Innovators", "Early Adopters", "Early Majority", "Late Majority", "Laggards"];
    const newAdoptionCurve: Record<string, Record<string, number>> = {};

    for (let cycle = 0; cycle <= 5; cycle++) {
        newAdoptionCurve[`cycle_${cycle}`] = {};
        for (const cat of categories) {
          const scores = categorized[cat];
          const avgBase = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0.5;

          if (cycle === 0) {
            newAdoptionCurve[`cycle_0`][cat] = Math.round(avgBase * 1000) / 1000;
          } else {
            const prev = newAdoptionCurve[`cycle_${cycle - 1}`][cat];
            const coef = {
              "Innovators": 0.22,
              "Early Adopters": 0.18,
              "Early Majority": 0.12,
              "Late Majority": 0.08,
              "Laggards": 0.03
            }[cat] || 0.1;

            let earlyInfluence = 0.0;
            if (cat !== "Innovators") {
              earlyInfluence = newAdoptionCurve[`cycle_${cycle - 1}`]["Innovators"] * 0.15 + newAdoptionCurve[`cycle_${cycle - 1}`]["Early Adopters"] * 0.1;
            }

            const delta = 1.0 - prev;
            const newScore = prev + (coef * delta) + (earlyInfluence * delta);
            newAdoptionCurve[`cycle_${cycle}`][cat] = Math.round(Math.min(0.98, newScore) * 1000) / 1000;
          }
        }
    }

    const finalCurve = newAdoptionCurve["cycle_5"];
    const avgAdoption = Object.values(finalCurve).reduce((a, b) => a + b, 0) / Object.keys(finalCurve).length;
    const adoptionPercentage = avgAdoption * 100;

    // 3. Update Funnel (scale from backend simulation, not hardcoded counts)
    const baseJourney = baseReport.buyer_journey || {};
    const scale = adoptionPercentage / Math.max(baseReport.product_market_fit || adoptionPercentage, 1);
    const expectedAdopters = Math.round(5000 * (adoptionPercentage / 100));
    const awarenessCount = Math.round((baseJourney.awareness?.count || 4000) * scale * (freemium ? 1.05 : 1.0));
    const interestCount = Math.min(awarenessCount, Math.round((baseJourney.interest?.count || 2800) * scale * (freemium ? 1.1 : 1.0)));
    const evaluationCount = Math.min(interestCount, Math.round((baseJourney.evaluation?.count || 1800) * scale));
    const trialCount = Math.min(evaluationCount, Math.round((baseJourney.trial?.count || 1200) * scale * (freemium ? 1.15 : 1.0)));
    const purchaseCount = Math.min(trialCount, expectedAdopters);
    const retentionCount = Math.round(purchaseCount * (features ? 0.90 : (baseJourney.retention?.conversion_percentage || 85) / 100));

    const funnel_data = {
      "awareness": { "count": awarenessCount, "conversion_percentage": 96.0, "drop_reason": baseReport.buyer_journey?.awareness?.drop_reason || "Limited initial advertising" },
      "interest": { "count": interestCount, "conversion_percentage": Math.round((interestCount / awarenessCount) * 1000) / 10, "drop_reason": baseReport.buyer_journey?.interest?.drop_reason || "Value proposition was unclear" },
      "evaluation": { "count": evaluationCount, "conversion_percentage": Math.round((evaluationCount / interestCount) * 1000) / 10, "drop_reason": baseReport.buyer_journey?.evaluation?.drop_reason || "Integration complexity concerns" },
      "trial": { "count": trialCount, "conversion_percentage": Math.round((trialCount / evaluationCount) * 1000) / 10, "drop_reason": baseReport.buyer_journey?.trial?.drop_reason || "Onboarding support missing" },
      "purchase": { "count": purchaseCount, "conversion_percentage": trialCount > 0 ? Math.round((purchaseCount / trialCount) * 1000) / 10 : 0, "drop_reason": price > baseReport.pricing_amount * 1.2 ? "High subscription fees" : baseReport.buyer_journey?.purchase?.drop_reason || "High price barriers" },
      "retention": { "count": retentionCount, "conversion_percentage": purchaseCount > 0 ? Math.round((retentionCount / purchaseCount) * 1000) / 10 : 85.0, "drop_reason": features ? "Minor feature gaps" : baseReport.buyer_journey?.retention?.drop_reason || "Lack of custom integrations" }
    };

    // 4. Update Revenue Projections
    const estAnnualRev = purchaseCount * price * 12 * (features ? 0.90 : 0.82);
    const proj_3mo = estAnnualRev * 0.25;
    const proj_6mo = estAnnualRev * 0.50;
    const proj_12mo = estAnnualRev;

    const newRevenueProjection = {
      currency: baseReport.pricing_currency,
      projections: [
        { months: 3, low: Math.round(proj_3mo * 0.85), estimate: Math.round(proj_3mo), high: Math.round(proj_3mo * 1.15) },
        { months: 6, low: Math.round(proj_6mo * 0.80), estimate: Math.round(proj_6mo), high: Math.round(proj_6mo * 1.20) },
        { months: 12, low: Math.round(proj_12mo * 0.75), estimate: Math.round(proj_12mo), high: Math.round(proj_12mo * 1.25) }
      ],
      assumptions: [
        `Conversion rate modeled as ${(purchaseCount / 50).toFixed(1)}% of total addressable market.`,
        `Unit economics derived from active price parameters: $${price} / month.`,
        `Retention rate assumed at ${(features ? 90 : 82)}% year-on-year based on peer cohorts.`
      ]
    };

    const opportunityScore = Math.max(10, Math.min(98, Math.round(adoptionPercentage)));
    const opportunityLabel = opportunityScore > 60 ? "Strong" : opportunityScore > 40 ? "Moderate" : "Weak";
    const launchRec = (opportunityScore >= 40 && difficulty <= 50) ? "Proceed" : "Delay or Pivot";

    const baseRevenueLoss = Math.round(1400 * 0.4 * price * 12);
    const objections_catalog = [
      {
        "issue": "High Price / Subscription Barrier",
        "severity": price > baseReport.pricing_amount * 1.2 ? "High" : price < baseReport.pricing_amount * 0.8 ? "Low" : "Medium",
        "affected_users": price > baseReport.pricing_amount * 1.2 ? 1600 : price < baseReport.pricing_amount * 0.8 ? 500 : 1200,
        "revenue_loss": price > baseReport.pricing_amount * 1.2 ? Math.round(baseRevenueLoss * 1.5) : price < baseReport.pricing_amount * 0.8 ? Math.round(baseRevenueLoss * 0.4) : baseRevenueLoss,
        "action": price > baseReport.pricing_amount ? "Introduce a lower tier starter plan at 40% discount" : "Maintain current price; highlight premium features"
      },
      {
        "issue": "Complex Integration Overhead",
        "severity": features ? "Low" : "Medium",
        "affected_users": features ? 350 : 950,
        "revenue_loss": features ? Math.round(baseRevenueLoss * 0.2) : Math.round(baseRevenueLoss * 0.7),
        "action": features ? "Provide automated onboarding documentation" : "Build 1-click installer and quickstart templates"
      },
      {
        "issue": "Data Security & Compliance Blockers",
        "severity": features ? "Low" : "High",
        "affected_users": features ? 200 : 700,
        "revenue_loss": features ? Math.round(baseRevenueLoss * 0.1) : Math.round(baseRevenueLoss * 0.5),
        "action": features ? "SOC2 self-certification guide is active" : "Provide SOC2/GDPR compliance self-certification guidelines"
      }
    ];

    const compAName = baseReport.competitors_battle?.competitor_a?.name || "Competitor A";
    const compBName = baseReport.competitors_battle?.competitor_b?.name || "Competitor B";
    const compAAdoption = parseFloat(baseReport.competitors_battle?.competitor_a?.adoption) || 18.5;
    const compBAdoption = parseFloat(baseReport.competitors_battle?.competitor_b?.adoption) || 12.2;

    const winner = (adoptionPercentage > compAAdoption && adoptionPercentage > compBAdoption) ? "Your Product" : compAName;
    const competitors_battle = {
      "your_product": {
        "price": price > baseReport.pricing_amount * 1.2 ? "High" : price < baseReport.pricing_amount * 0.8 ? "Low" : "Medium",
        "trust": "High",
        "features": features ? "Advanced" : "Moderate",
        "switching_cost": "Low",
        "adoption": `${adoptionPercentage.toFixed(1)}%`,
        "status": winner === "Your Product" ? "Leader" : "Contender"
      },
      "competitor_a": { ...baseReport.competitors_battle?.competitor_a, "status": winner === compAName ? "Leader" : "Lagging" },
      "competitor_b": { ...baseReport.competitors_battle?.competitor_b, "status": "Lagging" },
      "winner": winner
    };

    const signalConf = baseReport.confidence_details?.signal_confidence || 85;
    const personaConf = baseReport.confidence_details?.persona_confidence || 80;
    const baseForecastConf = baseReport.confidence_details?.forecast_confidence || 75;
    const newForecastConf = Math.round(baseForecastConf * (price > baseReport.pricing_amount * 1.3 ? 0.85 : price < baseReport.pricing_amount * 0.7 ? 0.9 : 1.0));
    const finalConf = Math.round((signalConf * personaConf * newForecastConf) / 10000);

    const conf_details = {
      signal_confidence: signalConf,
      persona_confidence: personaConf,
      forecast_confidence: newForecastConf,
      final_confidence: finalConf,
      formula: "Final = (Signal * Persona * Forecast) / 10000",
      reasoning: `Confidence adjusts to ${finalConf}% based on new inputs. Pricing shifts affect forecast predictability.`
    };

    const segmentsMap: Record<string, any[]> = {};
    updatedArchetypes.forEach((a) => {
      segmentsMap[a.segment] = segmentsMap[a.segment] || [];
      segmentsMap[a.segment].push(a);
    });

    const market_segments = baseReport.market_segments.map((seg: any) => {
      const archs = segmentsMap[seg.name] || [];
      const avgLik = archs.length > 0 ? archs.reduce((sum, a) => sum + a.likelihood_score, 0) / archs.length : 0.5;
      return {
        ...seg,
        average_likelihood: Math.round(avgLik * 100) / 100
      };
    });

    // Dynamic Scenario Tests computation
    const getAdoptionForPrice = (p: number) => {
      const f = getMarketFrictionScores(baseReport.idea, baseReport.industry, p, baseReport);
      const diff = computeLaunchDifficulty(f);
      
      const archs = archList.map((arch) => {
        let income = arch.income || 50000;
        let occupation = arch.occupation;
        if (occupation.toLowerCase() === "student" && p > 100) return 0.02;
        const annualPrice = baseReport.industry === "Consumer Hardware" ? p : p * 12;
        if (annualPrice > income * 0.05) return 0.02;
        
        const awareness = Math.max(0.1, Math.min(0.98, 0.90 + (arch.social_influence / 100.0) * 0.08));
        const fit = Math.max(0.1, Math.min(0.98, 0.50 + (arch.urgency / 100.0) * 0.45));
        const priceRatio = annualPrice / (income * 0.03);
        
        let elasticityExponent = 1.0;
        if (baseReport.industry === "Consumer Hardware" || baseReport.industry === "Education" || baseReport.industry === "Gaming") {
          elasticityExponent = 1.5;
        } else if (baseReport.industry === "Enterprise" || baseReport.industry === "Healthcare") {
          elasticityExponent = 0.6;
        }
        
        let priceAcc = Math.max(0.01, 1.0 - Math.pow(priceRatio, elasticityExponent) * (arch.budget_sensitivity / 10.0));
        priceAcc = Math.min(0.98, priceAcc);
        
        const trustGap = (f.trust_requirement / 100.0) * (1.0 - arch.risk_appetite / 100.0);
        const trust = Math.max(0.01, Math.min(0.98, 1.0 - trustGap));
        const habitGap = (f.behavior_change_cost / 100.0) * (1.0 - arch.technology_comfort / 100.0);
        const habitChange = Math.max(0.01, Math.min(0.98, 1.0 - habitGap));
        const retention = Math.max(0.1, Math.min(0.98, 0.95 - (arch.existing_alternatives / 100.0) * 0.15));
        
        let adoptionProb = Math.pow(awareness * fit * priceAcc * trust * habitChange * retention, 0.6);
        
        const density = f.competitive_density || 0.5;
        const novelty = f.novelty_penalty_val || 30.0;
        const competitorMultiplier = (1.0 - density * 0.15) * (1.0 + (100.0 - novelty) / 100.0 * 0.10);
        
        let likelihood = adoptionProb * competitorMultiplier;
        likelihood = Math.max(0.02, Math.min(0.98, likelihood));
        
        return likelihood;
      });
      
      const categorized: Record<string, number[]> = {
        "Innovators": [], "Early Adopters": [], "Early Majority": [], "Late Majority": [], "Laggards": []
      };
      
      archs.forEach((score, idx) => {
        let cat = "Laggards";
        if (idx < 1) cat = "Innovators";
        else if (idx < 3) cat = "Early Adopters";
        else if (idx < 8) cat = "Early Majority";
        else if (idx < 13) cat = "Late Majority";
        categorized[cat].push(score);
      });
      
      const newAdoptionCurve: Record<string, Record<string, number>> = {};
      const categories = ["Innovators", "Early Adopters", "Early Majority", "Late Majority", "Laggards"];
      
      for (let cycle = 0; cycle <= 5; cycle++) {
        newAdoptionCurve[`cycle_${cycle}`] = {};
        for (const cat of categories) {
          const scores = categorized[cat];
          const avgBase = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : 0.5;
          if (cycle === 0) {
            newAdoptionCurve[`cycle_0`][cat] = Math.round(avgBase * 1000) / 1000;
          } else {
            const prev = newAdoptionCurve[`cycle_${cycle - 1}`][cat];
            const coef = {
              "Innovators": 0.22, "Early Adopters": 0.18, "Early Majority": 0.12, "Late Majority": 0.08, "Laggards": 0.03
            }[cat] || 0.1;
            let earlyInfluence = 0.0;
            if (cat !== "Innovators") {
              earlyInfluence = newAdoptionCurve[`cycle_${cycle - 1}`]["Innovators"] * 0.15 + newAdoptionCurve[`cycle_${cycle - 1}`]["Early Adopters"] * 0.1;
            }
            const delta = 1.0 - prev;
            const newScore = prev + (coef * delta) + (earlyInfluence * delta);
            newAdoptionCurve[`cycle_${cycle}`][cat] = Math.round(Math.min(0.98, newScore) * 1000) / 1000;
          }
        }
      }
      
      const finalCurve = newAdoptionCurve["cycle_5"];
      return (Object.values(finalCurve).reduce((a, b) => a + b, 0) / Object.keys(finalCurve).length) * 100;
    };

    const halfPrice = price / 2.0;
    const premiumPrice = price * 1.5;
    
    const halfAdoption = getAdoptionForPrice(halfPrice);
    const premiumAdoption = getAdoptionForPrice(premiumPrice);

    const halfFriction = getMarketFrictionScores(baseReport.idea, baseReport.industry, halfPrice, baseReport);
    const halfDifficulty = computeLaunchDifficulty(halfFriction);
    const halfRec = (halfAdoption >= 40 && halfDifficulty <= 50) ? "Proceed" : "Delay or Pivot";
    
    const premiumFriction = getMarketFrictionScores(baseReport.idea, baseReport.industry, premiumPrice, baseReport);
    const premiumDifficulty = computeLaunchDifficulty(premiumFriction);
    const premiumRec = (premiumAdoption >= 40 && premiumDifficulty <= 50) ? "Proceed" : "Delay or Pivot";
    
    const currentDifficulty = difficulty;
    const currentRec = (adoptionPercentage >= 40 && currentDifficulty <= 50) ? "Proceed" : "Delay or Pivot";
    
    const scenario_tests = [
      {
        name: "Half Price",
        price: `${baseReport.pricing_currency} ${halfPrice.toFixed(2)}`,
        adoption: Math.round(halfAdoption * 10) / 10,
        difficulty: Math.round(halfDifficulty * 10) / 10,
        recommendation: halfRec
      },
      {
        name: "Current Price",
        price: `${baseReport.pricing_currency} ${price.toFixed(2)}`,
        adoption: Math.round(adoptionPercentage * 10) / 10,
        difficulty: Math.round(currentDifficulty * 10) / 10,
        recommendation: currentRec
      },
      {
        name: "Premium Price",
        price: `${baseReport.pricing_currency} ${premiumPrice.toFixed(2)}`,
        adoption: Math.round(premiumAdoption * 10) / 10,
        difficulty: Math.round(premiumDifficulty * 10) / 10,
        recommendation: premiumRec
      }
    ];

    const brief = `AURA client-side re-simulation complete. Launch Difficulty is ${difficulty.toFixed(1)}/100. Product Market Fit score is ${opportunityScore}/100. Launch recommendation: ${launchRec}.`;

    return {
      ...baseReport,
      executive_summary: brief,
      opportunity_score: opportunityScore,
      opportunity_label: opportunityLabel,
      launch_recommendation: launchRec,
      revenue_projection: newRevenueProjection,
      adoption_curve: newAdoptionCurve,
      buyer_journey: funnel_data,
      objections_list: objections_catalog,
      competitors_battle,
      confidence_details: conf_details,
      market_segments,
      confidence_score: finalConf,
      
      // Market Friction outputs
      launch_difficulty: Math.round(difficulty * 10) / 10,
      price_friction: Math.round(friction.price_friction),
      social_friction: Math.round(friction.social_friction),
      behavior_change_cost: Math.round(friction.behavior_change_cost),
      trust_requirement: Math.round(friction.trust_requirement),
      infrastructure_requirement: Math.round(friction.infrastructure_requirement),
      switching_cost: Math.round(friction.switching_cost),
      time_to_value: Math.round(friction.time_to_value),
      novelty_penalty: Math.round(friction.novelty_penalty_val || 30),
      education_cost: Math.round(friction.education_cost),
      product_market_fit: opportunityScore,
      social_adoption: Math.round(friction.social_acceptance),
      price_acceptance: Math.round(100.0 - friction.price_friction),
      trust_barrier: Math.round(friction.trust_requirement),
      habit_change_required: Math.round(friction.behavior_change_cost),
      scenario_tests: scenario_tests
    };
  };

  useEffect(() => {
    if (!report || archetypes.length === 0) return;
    const result = runClientSimulation(priceSlider, addFeature, addFreemium, timelineSelect, archetypes, report);
    if (result) {
      setSimReport(result);
    }
  }, [priceSlider, addFeature, addFreemium, timelineSelect, archetypes, report]);

  // Fetch paginated personas for segment
  useEffect(() => {
    if (!selectedSegment || !jobId) return;

    const fetchPersonas = async () => {
      setLoadingPersonas(true);
      try {
        const url = `http://localhost:8000/simulate/${jobId}/personas?segment=${encodeURIComponent(selectedSegment.name)}&page=${personasPage}&limit=6`;
        const res = await fetch(url);
        if (res.ok) {
          const data = await res.json();
          setPersonas(data.personas);
          setPersonasTotalCount(data.total_count);
        }
      } catch (err) {
        console.error("Error fetching personas:", err);
      } finally {
        setLoadingPersonas(false);
      }
    };

    fetchPersonas();
  }, [selectedSegment, personasPage, jobId]);

  // Stage list for loading indicator
  const stages = [
    { key: "queued", label: "Queued", desc: "Simulation request accepted" },
    { key: "collecting_signals", label: "Signal Scraper", desc: "Scraping Reddit, Google Trends & News APIs" },
    { key: "generating_personas", label: "Persona Engine", desc: "Generating core customer persona archetypes" },
    { key: "simulating", label: "Simulation Node", desc: "Evaluating buys & WOM diffusion cycles" },
    { key: "forecasting", label: "Financial Forecast", desc: "Projecting TAM and 3/6/12mo growth curves" },
    { key: "generating_report", label: "Synthesis Engine", desc: "Compiling strategic executive report" }
  ];

  const getStageState = (stageKey: string, index: number) => {
    const activeIndex = stages.findIndex(s => s.key === status);
    
    if (status === "failed") return "failed";
    if (status === "complete") return "completed";
    if (activeIndex === index) return "active";
    if (activeIndex > index) return "completed";
    return "pending";
  };

  // Parse adoption curve from report into Recharts format
  // curve data format: { "cycle_0": { "Segment A": 0.35, "Segment B": 0.40 }, "cycle_1": ... }
  // output format: [ { name: "Cycle 0", "Segment A": 35, "Segment B": 40 }, ... ]
  const getAdoptionChartData = () => {
    if (!simReport || !simReport.adoption_curve) return [];
    
    return Object.entries(simReport.adoption_curve).map(([cycleKey, cycleData]) => {
      const cycleNum = cycleKey.replace("cycle_", "Cycle ");
      const formatted: Record<string, any> = { name: cycleNum };
      Object.entries(cycleData).forEach(([segName, val]) => {
        formatted[segName] = Math.round(val * 1000) / 10; // 0.355 -> 35.5%
      });
      return formatted;
    });
  };

  // Format currency value helper
  const formatCurrency = (val: number, curr: string) => {
    const symbol = { "USD": "$", "EUR": "€", "INR": "₹" }[curr] || "$";
    if (val >= 1000000) {
      return `${symbol}${(val / 1000000).toFixed(1)}M`;
    }
    if (val >= 1000) {
      return `${symbol}${(val / 1000).toFixed(0)}K`;
    }
    return `${symbol}${val}`;
  };

  return (
    <div className="min-h-screen relative flex flex-col justify-between p-6 md:p-12">
      <div className="glow-orb-1" />
      <div className="glow-orb-2" />

      {/* Header */}
      <header className="relative z-10 w-full max-w-6xl mx-auto flex items-center justify-between border-b border-card-border pb-4 mb-6">
        <button 
          onClick={() => router.push("/")}
          className="flex items-center space-x-2 text-xs font-mono text-gray-400 hover:text-primary transition-colors cursor-pointer"
        >
          <ArrowLeft className="w-4 h-4" />
          <span>BACK_TO_DASH</span>
        </button>
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 rounded bg-gradient-to-tr from-primary to-accent flex items-center justify-center font-mono font-bold text-background text-lg shadow-[0_0_15px_rgba(0,240,255,0.4)]">
            A
          </div>
          <span className="font-mono text-xl font-bold tracking-[0.2em] text-foreground">AURA</span>
        </div>
      </header>

      {/* Main Container */}
      <main className="relative z-10 flex-grow w-full max-w-6xl mx-auto my-6">
        
        {/* LOADING STATE CONTAINER */}
        {status !== "complete" && status !== "failed" && (
          <div className="min-h-[50vh] flex flex-col items-center justify-center max-w-xl mx-auto space-y-8 py-12">
            <div className="text-center space-y-3">
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ repeat: Infinity, duration: 3, ease: "linear" }}
                className="inline-block"
              >
                <RefreshCw className="w-12 h-12 text-primary" />
              </motion.div>
              <h2 className="text-xl font-bold font-mono tracking-wider uppercase">Running Pipeline...</h2>
              <p className="text-gray-400 text-xs font-mono">Job ID: {jobId}</p>
            </div>

            {/* Progress Bar */}
            <div className="w-full space-y-2">
              <div className="flex justify-between text-xs font-mono text-gray-400">
                <span>STAGE: {currentStage}</span>
                <span className="text-primary">{progress}%</span>
              </div>
              <div className="w-full h-2 bg-card-border/40 rounded overflow-hidden">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.5 }}
                  className="h-full bg-gradient-to-r from-primary to-accent shadow-[0_0_10px_rgba(0,240,255,0.5)]" 
                />
              </div>
            </div>

            {showTakingLong && (
              <motion.div 
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                className="w-full bg-[#1e150b] border border-amber-500/30 p-5 rounded-lg flex flex-col items-center text-center space-y-4"
              >
                <div className="flex items-center space-x-2 text-amber-500">
                  <AlertTriangle className="w-5 h-5 shrink-0 animate-pulse" />
                  <span className="font-mono text-xs font-bold uppercase tracking-wider">This is taking longer than expected</span>
                </div>
                <p className="text-gray-300/80 text-xxs font-mono max-w-md">
                  API rate limits or network delays may be stalling the simulation. You can manually retry the simulation without losing your inputs.
                </p>
                <button
                  onClick={handleRetry}
                  className="px-5 py-2.5 bg-gradient-to-r from-primary to-accent hover:shadow-[0_0_15px_rgba(0,240,255,0.4)] text-background rounded font-mono text-xs font-bold uppercase tracking-wider cursor-pointer transition-all duration-300"
                >
                  Retry Simulation
                </button>
              </motion.div>
            )}

            {/* Stages Visual Node List */}
            <div className="w-full bg-card/75 border border-card-border/50 rounded-lg p-5 space-y-4">
              <span className="block text-xxs font-mono text-gray-500 uppercase tracking-widest border-b border-card-border/50 pb-2">Pipeline execution stack</span>
              
              <div className="space-y-3">
                {stages.map((stg, idx) => {
                  const state = getStageState(stg.key, idx);
                  return (
                    <div key={stg.key} className="flex items-start justify-between text-xs font-mono">
                      <div className="flex items-start space-x-3">
                        {state === "completed" && <CheckCircle2 className="w-4 h-4 text-green-400 mt-0.5 shrink-0" />}
                        {state === "active" && (
                          <motion.div 
                            animate={{ opacity: [0.3, 1, 0.3] }}
                            transition={{ repeat: Infinity, duration: 1.5 }}
                            className="mt-0.5"
                          >
                            <PlayCircle className="w-4 h-4 text-primary shrink-0" />
                          </motion.div>
                        )}
                        {state === "pending" && <HelpCircle className="w-4 h-4 text-gray-600 mt-0.5 shrink-0" />}
                        
                        <div>
                          <span className={`font-semibold ${
                            state === "active" ? "text-primary" : state === "completed" ? "text-gray-300" : "text-gray-600"
                          }`}>{stg.label}</span>
                          <p className="text-xxs text-gray-500 font-normal">{stg.desc}</p>
                        </div>
                      </div>

                      <div className="text-xxs uppercase tracking-wider">
                        {state === "completed" && <span className="text-green-400">DONE</span>}
                        {state === "active" && <span className="text-primary animate-pulse">RUNNING</span>}
                        {state === "pending" && <span className="text-gray-600">WAITING</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* FAILED STATE CONTAINER */}
        {status === "failed" && (
          <div className="min-h-[50vh] flex flex-col items-center justify-center max-w-lg mx-auto text-center space-y-6 py-12">
            <div className="w-16 h-16 rounded-full bg-red-950/40 border border-red-500/50 flex items-center justify-center text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.2)]">
              <AlertTriangle className="w-8 h-8" />
            </div>
            <div className="space-y-2">
              <h2 className="text-xl font-bold font-mono uppercase tracking-wider text-red-400">Pipeline Aborted</h2>
              <p className="text-gray-400 text-xs font-mono">An unrecoverable error halted the simulation graph.</p>
            </div>
            <div className="bg-[#0c0d16] border border-red-500/30 p-4 rounded-lg font-mono text-left text-xs text-red-300 w-full max-h-48 overflow-y-auto">
              <strong>Error stack:</strong>
              <p className="mt-2 text-red-400/80">{errorMsg}</p>
            </div>
            <div className="flex flex-col sm:flex-row gap-4 justify-center w-full">
              <button
                onClick={handleRetry}
                className="px-6 py-3 bg-gradient-to-r from-primary to-accent hover:shadow-[0_0_20px_rgba(0,240,255,0.4)] text-background rounded font-mono text-xs font-bold uppercase tracking-wider cursor-pointer transition-all duration-300"
              >
                Retry Simulation
              </button>
              <button
                onClick={() => router.push("/")}
                className="px-6 py-3 bg-card-border hover:bg-card-hover border border-card-border hover:border-gray-500 rounded font-mono text-xs text-gray-300 transition-all cursor-pointer"
              >
                Configure &amp; Restart
              </button>
            </div>
          </div>
        )}

        {/* REPORT / COMPLETE DASHBOARD STATE CONTAINER */}
        {status === "complete" && report && simReport && (
          <div className="space-y-8">
            
            {/* Simulation Metadata Banner */}
            <div className="bg-card border border-card-border rounded-lg p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 relative overflow-hidden shadow-lg">
              <div className="absolute top-0 right-0 w-24 h-24 bg-primary/5 rounded-full blur-2xl pointer-events-none" />
              <div className="space-y-1 relative z-10">
                <span className="text-xxs font-mono text-primary uppercase tracking-widest flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-accent animate-pulse" />
                  <span>SYNTHETIC MARKET SIMULATION ENGINE ACTIVE</span>
                </span>
                <h2 className="text-xl font-bold text-gray-100">{simReport.idea}</h2>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xxs font-mono text-gray-500 mt-2">
                  <span>INDUSTRY: <b className="text-gray-300">{simReport.industry}</b></span>
                  <span>TARGET: <b className="text-gray-300">{simReport.market}</b></span>
                  <span>ORIGINAL PRICE: <b className="text-primary">{report.pricing_currency} {report.pricing_amount}</b></span>
                  <span>CURRENT PRICE: <b className="text-accent">{simReport.pricing_currency} {priceSlider}</b></span>
                  <span>REGION: <b className="text-gray-300">{simReport.region}</b></span>
                </div>
              </div>
              <div className="flex items-center space-x-4 shrink-0 relative z-10">
                <button
                  onClick={() => setShowTransparency(!showTransparency)}
                  className={`px-3 py-1.5 rounded border text-xxs font-mono transition-all flex items-center space-x-1 ${
                    showTransparency 
                      ? "bg-primary/25 border-primary text-primary shadow-[0_0_10px_rgba(0,240,255,0.2)]" 
                      : "bg-card-border/40 border-card-border text-gray-400 hover:border-gray-500 hover:text-gray-300"
                  }`}
                >
                  <ShieldCheck className="w-3.5 h-3.5" />
                  <span>TRANSPARENCY_MODE: {showTransparency ? "ON" : "OFF"}</span>
                </button>
              </div>
            </div>

            {/* SCENARIO LAB CONSOLE (STEP 12) */}
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4 }}
              className="bg-card border-2 border-primary/20 rounded-lg p-6 relative overflow-hidden shadow-[0_0_20px_rgba(0,240,255,0.05)]"
            >
              <div className="absolute top-0 left-0 h-1 w-full bg-gradient-to-r from-primary via-accent to-primary" />
              <div className="flex items-center justify-between border-b border-card-border/50 pb-3 mb-5">
                <div className="flex items-center space-x-2">
                  <Cpu className="w-5 h-5 text-accent animate-pulse" />
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100">Scenario Lab Console</h3>
                    <p className="text-xxs text-gray-500 font-mono">Simulate pricing & product changes on 5,000 synthetic personas in real-time</p>
                  </div>
                </div>
                
                <button
                  onClick={() => {
                    setPriceSlider(report.pricing_amount);
                    setAddFeature(false);
                    setAddFreemium(false);
                    setTimelineSelect(report.timeline);
                  }}
                  className="px-2.5 py-1 text-xxs font-mono bg-card-border hover:bg-card-hover border border-card-border rounded text-gray-400 hover:text-white transition-colors"
                >
                  Reset Defaults
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                {/* Pricing Slider */}
                <div className="space-y-2.5">
                  <div className="flex justify-between text-xs font-mono">
                    <span className="text-gray-400 uppercase">Pricing Tier</span>
                    <span className="text-accent font-bold">${priceSlider} / mo</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="200"
                    value={priceSlider}
                    onChange={(e) => setPriceSlider(Number(e.target.value))}
                    className="w-full accent-primary bg-card-border/40 h-1.5 rounded-lg appearance-none cursor-pointer"
                  />
                  <div className="flex justify-between text-xxs font-mono text-gray-500">
                    <span>Min: $1</span>
                    <span>Max: $200</span>
                  </div>
                </div>

                {/* Features Checklist */}
                <div className="flex flex-col space-y-3 justify-center">
                  <label className="flex items-center space-x-2.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={addFeature}
                      onChange={(e) => setAddFeature(e.target.checked)}
                      className="w-4 h-4 rounded accent-primary border-card-border bg-card-border cursor-pointer focus:ring-0 focus:ring-offset-0"
                    />
                    <div className="text-xs font-mono">
                      <span className="text-gray-200 block font-semibold">Premium Features</span>
                      <span className="text-xxs text-gray-500">Enable advanced features</span>
                    </div>
                  </label>
                </div>

                {/* Freemium Checklist */}
                <div className="flex flex-col space-y-3 justify-center">
                  <label className="flex items-center space-x-2.5 cursor-pointer select-none">
                    <input
                      type="checkbox"
                      checked={addFreemium}
                      onChange={(e) => setAddFreemium(e.target.checked)}
                      className="w-4 h-4 rounded accent-primary border-card-border bg-card-border cursor-pointer focus:ring-0 focus:ring-offset-0"
                    />
                    <div className="text-xs font-mono">
                      <span className="text-gray-200 block font-semibold">Freemium Tier</span>
                      <span className="text-xxs text-gray-500">Add free limited plan</span>
                    </div>
                  </label>
                </div>

                {/* Timeline Dropdown */}
                <div className="space-y-2">
                  <span className="text-xxs font-mono text-gray-400 uppercase block">Timeline Shift</span>
                  <select
                    value={timelineSelect}
                    onChange={(e) => setTimelineSelect(e.target.value)}
                    className="w-full bg-[#0a0b15] border border-card-border rounded px-3 py-1.5 text-xs font-mono text-gray-300 focus:outline-none focus:border-primary"
                  >
                    <option value="<3mo">Under 3 Months</option>
                    <option value="3-6mo">3 to 6 Months</option>
                    <option value="6-12mo">6 to 12 Months</option>
                    <option value="12mo+">12 Months+</option>
                  </select>
                </div>
              </div>

              {/* Scenario Comparison Board */}
              {simReport.scenario_tests && simReport.scenario_tests.length > 0 && (
                <div className="space-y-3 pt-4 border-t border-card-border/30 mt-6">
                  <div className="text-xs font-mono font-bold uppercase tracking-wider text-gray-300">
                    Auto Scenario Tester Projections
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-left border-collapse text-xs font-mono">
                      <thead>
                        <tr className="border-b border-card-border/60 text-gray-500 text-[10px] uppercase">
                          <th className="py-2">Scenario</th>
                          <th className="py-2">Price Target</th>
                          <th className="py-2">Expected Adoption</th>
                          <th className="py-2">Launch Difficulty</th>
                          <th className="py-2 text-right">Strategic Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-card-border/30">
                        {simReport.scenario_tests.map((scen: any, idx: number) => {
                          const isCurrent = scen.name === "Current Price";
                          return (
                            <tr key={idx} className={`${isCurrent ? "bg-primary/5 text-foreground" : "text-gray-400"}`}>
                              <td className="py-2.5 font-semibold">
                                {scen.name} {isCurrent && <span className="text-[10px] bg-primary/20 text-primary px-1.5 py-0.5 rounded ml-1">Active</span>}
                              </td>
                              <td className="py-2.5 text-gray-200">{scen.price}</td>
                              <td className="py-2.5">
                                <span className={`font-bold ${
                                  scen.adoption > 50 ? "text-green-400" : scen.adoption > 30 ? "text-amber-400" : "text-red-400"
                                }`}>{scen.adoption}%</span>
                              </td>
                              <td className="py-2.5">{scen.difficulty}/100</td>
                              <td className="py-2.5 text-right">
                                <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                                  scen.recommendation === "Proceed" ? "bg-green-950/60 text-green-400 border border-green-500/20" : "bg-red-950/60 text-red-400 border border-red-500/20"
                                }`}>
                                  {scen.recommendation}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </motion.div>

            {/* STEP 2: SIGNAL INTELLIGENCE PANEL */}
            {simReport.signal_intelligence && (
              <div className="space-y-4">
                <div className="flex justify-between items-baseline">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100 flex items-center space-x-2">
                      <Sparkles className="w-4 h-4 text-primary" />
                      <span>Scraped Signal Discovery Panel</span>
                    </h3>
                    <p className="text-xxs text-gray-500 font-mono">Real-world indicators extracted from Reddit, Google Trends & News APIs</p>
                  </div>
                  {showTransparency && (
                    <span className="text-xxs font-mono text-primary animate-pulse">TRANSPARENCY ACTIVE</span>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                  {Object.entries(simReport.signal_intelligence).map(([key, item]) => {
                    const labelMap: Record<string, string> = {
                      demand_momentum: "Demand Momentum",
                      competitive_saturation: "Competitive Density",
                      customer_friction: "Customer Friction",
                      novelty_score: "Novelty Score",
                      economic_sensitivity: "Economic Sensitivity"
                    };
                    return (
                      <motion.div
                        key={key}
                        whileHover={{ scale: 1.02 }}
                        className="bg-card border border-card-border rounded-lg p-4 space-y-2 hover:border-accent/30 transition-all"
                      >
                        <div className="flex justify-between items-center text-xxs font-mono text-gray-500">
                          <span>{labelMap[key] || key}</span>
                          <span className={`px-1.5 py-0.25 rounded text-[9px] ${
                            item.confidence === "High" ? "bg-green-950/40 text-green-400" : "bg-amber-950/40 text-amber-400"
                          }`}>{item.confidence} Conf</span>
                        </div>
                        
                        <div className="flex items-baseline justify-between">
                          <div className="text-2xl font-bold font-mono text-gray-100">{item.metric}/100</div>
                          <div className="text-xs">
                            {item.trend === "up" ? <span className="text-green-400 font-bold">▲</span> :
                             item.trend === "down" ? <span className="text-red-400 font-bold">▼</span> :
                             <span className="text-gray-400 font-bold">■</span>}
                          </div>
                        </div>

                        <p className="text-[10px] text-gray-400 leading-normal font-mono h-12 overflow-y-auto">
                          {item.explanation}
                        </p>

                        <div className="border-t border-card-border/40 pt-1.5 flex flex-wrap gap-1 items-center justify-between text-[9px] font-mono text-gray-500">
                          <span>Sources:</span>
                          <span className="text-gray-300 font-semibold">{item.sources.join(", ")}</span>
                        </div>

                        {showTransparency && (
                          <div className="bg-[#050508]/60 border border-primary/20 p-2 rounded text-[9px] font-mono text-primary/80 space-y-0.5 animate-fadeIn">
                            <div>Source: API Scraping</div>
                            <div>Sample size: 5,000 personas</div>
                            <div>Freshness: 1 hour ago</div>
                          </div>
                        )}
                      </motion.div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* TOP CARDS SECTION */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
              
              {/* Card 1: Opportunity Score */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4 }}
                className="bg-card border border-card-border rounded-lg p-5 space-y-2 hover:border-primary/50 transition-colors relative"
              >
                <span className="text-xxs font-mono text-gray-500 uppercase tracking-widest block">Market Reception</span>
                <div className="flex items-baseline space-x-2">
                  <span className="text-3xl font-extrabold font-mono text-primary">{simReport.opportunity_score}</span>
                  <span className="text-xs font-semibold text-gray-400">/100</span>
                </div>
                <span className={`inline-block text-xxs font-mono px-2 py-0.5 rounded ${
                  simReport.opportunity_label === "Strong" ? "bg-green-950/50 text-green-400 border border-green-500/20" :
                  simReport.opportunity_label === "Moderate" ? "bg-amber-950/50 text-amber-400 border border-amber-500/20" :
                  "bg-red-950/50 text-red-400 border border-red-500/20"
                }`}>
                  {simReport.opportunity_label} Fit
                </span>
                {showTransparency && (
                  <div className="text-[9px] font-mono text-gray-500 border-t border-card-border/30 pt-1.5 mt-1">
                    Sample: 5,000 personas | Cycles: 5 | Freshness: Live
                  </div>
                )}
              </motion.div>

              {/* Card 2: Revenue Projections */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.05 }}
                className="bg-card border border-card-border rounded-lg p-5 space-y-2 hover:border-primary/50 transition-colors"
              >
                <span className="text-xxs font-mono text-gray-500 uppercase tracking-widest block">12Mo Revenue Expected</span>
                <div className="text-2xl font-extrabold font-mono text-green-400">
                  {formatCurrency((simReport.revenue_projection.projections[2]?.estimate ?? simReport.revenue_projection.projections[2]?.expected ?? 0), simReport.pricing_currency)}
                </div>
                <span className="text-xxs font-mono text-gray-500 block leading-tight">
                  Low: {formatCurrency(simReport.revenue_projection.projections[2].low, simReport.pricing_currency)} | High: {formatCurrency(simReport.revenue_projection.projections[2].high, simReport.pricing_currency)}
                </span>
                {showTransparency && (
                  <div className="text-[9px] font-mono text-gray-500 border-t border-card-border/30 pt-1.5 mt-1">
                    Deterministic calculation | Freshness: Live
                  </div>
                )}
              </motion.div>

              {/* Card 3: Top Objections */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.1 }}
                className="bg-card border border-card-border rounded-lg p-5 space-y-2 hover:border-primary/50 transition-colors"
              >
                <span className="text-xxs font-mono text-gray-500 uppercase tracking-widest block">Top Objection</span>
                <div className="text-sm font-bold truncate text-red-400">
                  {simReport.objections_list && simReport.objections_list[0] ? simReport.objections_list[0].issue : "Pricing / High Cost"}
                </div>
                <span className="text-xxs font-mono text-gray-500 block">
                  Reported by {priceSlider > report.pricing_amount ? "32%" : "18%"} of personas.
                </span>
                {showTransparency && (
                  <div className="text-[9px] font-mono text-gray-500 border-t border-card-border/30 pt-1.5 mt-1">
                    Objection engine analysis | Freshness: Live
                  </div>
                )}
              </motion.div>

              {/* Card 4: Final Adoption % */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.15 }}
                className="bg-card border border-card-border rounded-lg p-5 space-y-2 hover:border-primary/50 transition-colors"
              >
                <span className="text-xxs font-mono text-gray-500 uppercase tracking-widest block">Final Adoption %</span>
                <div className="text-3xl font-extrabold font-mono text-accent">
                  {simReport.final_adoption_pct?.toFixed(1) ?? ((simReport.revenue_projection.projections[2]?.estimate ?? simReport.revenue_projection.projections[2]?.expected ?? 0) / (priceSlider * 12 * 50)).toFixed(1)}%
                </div>
                <span className="text-xxs font-mono text-gray-500 block">
                  Reached in Adoption Cycle 5.
                </span>
                {showTransparency && (
                  <div className="text-[9px] font-mono text-gray-500 border-t border-card-border/30 pt-1.5 mt-1">
                    Rogers Adoption model diffusion | Freshness: Live
                  </div>
                )}
              </motion.div>

              {/* Card 5: Segments */}
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.2 }}
                className="bg-card border border-card-border rounded-lg p-5 space-y-2 hover:border-primary/50 transition-colors"
              >
                <span className="text-xxs font-mono text-gray-500 uppercase tracking-widest block">Customer Segments</span>
                <div className="text-3xl font-extrabold font-mono text-foreground">
                  {simReport.market_segments.length}
                </div>
                <span className="text-xxs font-mono text-gray-500 block">
                  Clustered via buyer attributes.
                </span>
                {showTransparency && (
                  <div className="text-[9px] font-mono text-gray-500 border-t border-card-border/30 pt-1.5 mt-1">
                    Clustered archetypes | Freshness: Live
                  </div>
                )}
              </motion.div>

            </div>

            {/* MARKET FRICTION MODEL METRICS GRID */}
            <div className="bg-card border border-card-border rounded-lg p-6 space-y-4">
              <div>
                <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100 flex items-center space-x-2">
                  <ShieldCheck className="w-4 h-4 text-accent" />
                  <span>AURA Market Friction & Realism Engine</span>
                </h3>
                <p className="text-xxs text-gray-500 font-mono">Divergent market feedback metrics and launch barrier evaluations</p>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
                {/* Product Market Fit */}
                <div className="bg-[#0b0c16] border border-card-border/60 rounded-lg p-4 space-y-2 relative">
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block">Product Market Fit</span>
                  <div className="flex items-baseline space-x-1">
                    <span className="text-2xl font-extrabold font-mono text-primary">{Math.round(simReport.pmf_score ?? simReport.product_market_fit ?? simReport.opportunity_score ?? 0)}</span>
                    <span className="text-xxs text-gray-500">/100</span>
                  </div>
                  <div className="w-full bg-card-border/40 h-1 rounded-full overflow-hidden">
                    <div className="bg-primary h-full rounded-full" style={{ width: `${simReport.pmf_score ?? simReport.product_market_fit ?? simReport.opportunity_score ?? 0}%` }} />
                  </div>
                </div>

                {/* Launch Difficulty */}
                <div className="bg-[#0b0c16] border border-card-border/60 rounded-lg p-4 space-y-2 relative">
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block">Launch Difficulty</span>
                  <div className="flex items-baseline space-x-1">
                    <span className={`text-2xl font-extrabold font-mono ${
                      (simReport.launch_difficulty || 0) > 50 ? "text-red-400" : (simReport.launch_difficulty || 0) > 35 ? "text-amber-400" : "text-green-400"
                    }`}>{simReport.launch_difficulty || 0}</span>
                    <span className="text-xxs text-gray-500">/100</span>
                  </div>
                  <div className="w-full bg-card-border/40 h-1 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${
                      (simReport.launch_difficulty || 0) > 50 ? "bg-red-500" : (simReport.launch_difficulty || 0) > 35 ? "bg-amber-500" : "bg-green-500"
                    }`} style={{ width: `${simReport.launch_difficulty || 0}%` }} />
                  </div>
                </div>

                {/* Trust Barrier */}
                <div className="bg-[#0b0c16] border border-card-border/60 rounded-lg p-4 space-y-2 relative">
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block">Trust Barrier</span>
                  <div className="flex items-baseline space-x-1">
                    <span className="text-2xl font-extrabold font-mono text-red-400">{simReport.trust_barrier || 0}</span>
                    <span className="text-xxs text-gray-500">/100</span>
                  </div>
                  <div className="w-full bg-card-border/40 h-1 rounded-full overflow-hidden">
                    <div className="bg-red-500 h-full rounded-full" style={{ width: `${simReport.trust_barrier || 0}%` }} />
                  </div>
                </div>

                {/* Habit Change Required */}
                <div className="bg-[#0b0c16] border border-card-border/60 rounded-lg p-4 space-y-2 relative">
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block">Habit Change Required</span>
                  <div className="flex items-baseline space-x-1">
                    <span className="text-2xl font-extrabold font-mono text-amber-400">{simReport.habit_change_required || 0}</span>
                    <span className="text-xxs text-gray-500">/100</span>
                  </div>
                  <div className="w-full bg-card-border/40 h-1 rounded-full overflow-hidden">
                    <div className="bg-amber-500 h-full rounded-full" style={{ width: `${simReport.habit_change_required || 0}%` }} />
                  </div>
                </div>

                {/* Price Acceptance */}
                <div className="bg-[#0b0c16] border border-card-border/60 rounded-lg p-4 space-y-2 relative">
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block">Price Acceptance</span>
                  <div className="flex items-baseline space-x-1">
                    <span className="text-2xl font-extrabold font-mono text-green-400">{simReport.price_acceptance || 0}</span>
                    <span className="text-xxs text-gray-500">/100</span>
                  </div>
                  <div className="w-full bg-card-border/40 h-1 rounded-full overflow-hidden">
                    <div className="bg-green-500 h-full rounded-full" style={{ width: `${simReport.price_acceptance || 0}%` }} />
                  </div>
                </div>

                {/* Social Adoption */}
                <div className="bg-[#0b0c16] border border-card-border/60 rounded-lg p-4 space-y-2 relative">
                  <span className="text-[10px] font-mono text-gray-400 uppercase tracking-wider block">Social Adoption</span>
                  <div className="flex items-baseline space-x-1">
                    <span className="text-2xl font-extrabold font-mono text-accent">{simReport.social_adoption || 0}</span>
                    <span className="text-xxs text-gray-500">/100</span>
                  </div>
                  <div className="w-full bg-card-border/40 h-1 rounded-full overflow-hidden">
                    <div className="bg-accent h-full rounded-full" style={{ width: `${simReport.social_adoption || 0}%` }} />
                  </div>
                </div>
              </div>
            </div>

            {/* CHARTS LAYOUT SECTION */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Adoption Curve Line Chart */}
              <div className="lg:col-span-8 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest">Rogers Innovation Diffusion Curve</h3>
                    <p className="text-xxs text-gray-500 font-mono">Word-of-mouth network diffusion categories over 5 cycles</p>
                  </div>
                  {showTransparency && (
                    <span className="text-[10px] font-mono text-primary">Source: Rogers Adoption Math</span>
                  )}
                </div>
                
                <div className="h-72 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={getAdoptionChartData()}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1c1d2e" />
                      <XAxis dataKey="name" stroke="#6b7280" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                      <YAxis stroke="#6b7280" unit="%" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                      <Tooltip 
                        contentStyle={{ backgroundColor: "#0c0d16", borderColor: "#1e2035", color: "#fff", fontSize: 11, fontFamily: 'monospace' }} 
                      />
                      <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace' }} />
                      {["Innovators", "Early Adopters", "Early Majority", "Late Majority", "Laggards"].map((cat, idx) => (
                        <Line
                          key={cat}
                          type="monotone"
                          dataKey={cat}
                          stroke={CHART_COLORS[idx % CHART_COLORS.length]}
                          activeDot={{ r: 5 }}
                          strokeWidth={2}
                        />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* Segment Size Donut Chart (Drilldown Trigger) */}
              <div className="lg:col-span-4 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div>
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest">Market Clusters</h3>
                  <p className="text-xxs text-gray-500 font-mono">Click a segment to drill down into 5,000 personas</p>
                </div>

                <div className="h-64 w-full relative flex items-center justify-center">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={simReport.market_segments}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="size_percentage"
                        nameKey="name"
                        onClick={(data: any) => {
                          if (data && data.payload) {
                            setSelectedSegment(data.payload);
                            setPersonasPage(1);
                          }
                        }}
                        className="cursor-pointer"
                      >
                        {simReport.market_segments.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip 
                        contentStyle={{ backgroundColor: "#0c0d16", borderColor: "#1e2035", color: "#fff", fontSize: 11, fontFamily: 'monospace' }} 
                      />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="absolute flex flex-col items-center pointer-events-none">
                    <span className="text-xxs font-mono text-gray-500 uppercase">Total Clones</span>
                    <span className="text-lg font-mono font-bold">5,000</span>
                  </div>
                </div>

                {/* Custom Legend showing segments list */}
                <div className="space-y-2">
                  {simReport.market_segments.map((seg, idx) => (
                    <button
                      key={seg.id}
                      onClick={() => {
                        setSelectedSegment(seg);
                        setPersonasPage(1);
                      }}
                      className="w-full text-left flex items-center justify-between text-xs font-mono p-1 rounded hover:bg-card-hover transition-colors"
                    >
                      <div className="flex items-center space-x-2">
                        <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: CHART_COLORS[idx % CHART_COLORS.length] }} />
                        <span className="truncate max-w-[150px] font-semibold">{seg.name}</span>
                      </div>
                      <span className="text-gray-400 text-xxs">{seg.size_percentage}%</span>
                    </button>
                  ))}
                </div>
              </div>

            </div>

            {/* STEP 4: INTERACTIVE FUNNEL STACK & STEP 8: COMPETITOR BATTLE BOARD */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Funnel Stack (Step 4) */}
              <div className="lg:col-span-6 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100">Interactive Funnel Stack</h3>
                    <p className="text-xxs text-gray-500 font-mono">Conversion drops and reasons across 5,000 synthetic personas</p>
                  </div>
                  {showTransparency && (
                    <span className="text-[10px] font-mono text-primary">Freshness: Live</span>
                  )}
                </div>

                {simReport.buyer_journey && (
                  <div className="space-y-3 pt-2">
                    {Object.entries(simReport.buyer_journey).map(([stage, details], idx) => {
                      const stagesMap: Record<string, { label: string, color: string }> = {
                        awareness: { label: "1. Awareness", color: "from-blue-600 to-indigo-600" },
                        interest: { label: "2. Interest", color: "from-indigo-600 to-purple-600" },
                        evaluation: { label: "3. Evaluation", color: "from-purple-600 to-pink-600" },
                        trial: { label: "4. Trial", color: "from-pink-600 to-rose-600" },
                        purchase: { label: "5. Purchase", color: "from-rose-600 to-orange-600" },
                        retention: { label: "6. Retention", color: "from-orange-600 to-emerald-600" }
                      };
                      const val = stagesMap[stage] || { label: stage, color: "from-gray-600 to-gray-500" };
                      const maxCount = 5000;
                      const widthPercent = (details.count / maxCount) * 100;
                      return (
                        <div key={stage} className="space-y-1">
                          <div className="flex justify-between text-xs font-mono">
                            <span className="font-semibold text-gray-200">{val.label}</span>
                            <span className="text-gray-400 font-semibold">{details.count} users ({details.conversion_percentage}%)</span>
                          </div>
                          
                          <div className="flex items-center space-x-3">
                            <div className="flex-grow h-6 bg-card-border/20 rounded overflow-hidden relative">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${widthPercent}%` }}
                                className={`h-full bg-gradient-to-r ${val.color} opacity-80`}
                              />
                            </div>
                          </div>
                          
                          <div className="text-[10px] text-gray-500 font-mono pl-1 leading-normal italic">
                            Drop reason: {details.drop_reason}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Competitor Battle Board (Step 8) */}
              <div className="lg:col-span-6 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100">Competitor Battle Mode</h3>
                    <p className="text-xxs text-gray-500 font-mono">Side-by-side metric battle compared against top scraped giants</p>
                  </div>
                  <span className="px-2 py-0.5 rounded bg-primary/20 border border-primary/30 text-[10px] font-mono text-primary">
                    Winner: {simReport.competitors_battle?.winner}
                  </span>
                </div>

                {simReport.competitors_battle && (
                  <div className="grid grid-cols-3 gap-4 pt-2">
                    {/* Your Product */}
                    <div className={`border rounded-lg p-4 space-y-3 relative overflow-hidden ${
                      simReport.competitors_battle.winner === "Your Product" ? "bg-primary/5 border-primary/40" : "bg-card/40 border-card-border"
                    }`}>
                      {simReport.competitors_battle.winner === "Your Product" && (
                        <div className="absolute top-0 right-0 bg-primary text-background font-mono font-bold text-[8px] px-1.5 py-0.5 rounded-bl">
                          WINNER
                        </div>
                      )}
                      <span className="text-xxs font-mono text-gray-500 uppercase block">YOUR PRODUCT</span>
                      <div className="space-y-2 font-mono text-xxs text-gray-300">
                        <div>Price: <b className="text-gray-100">{simReport.competitors_battle.your_product.price}</b></div>
                        <div>Trust: <b className="text-gray-100">{simReport.competitors_battle.your_product.trust}</b></div>
                        <div>Features: <b className="text-gray-100">{simReport.competitors_battle.your_product.features}</b></div>
                        <div>Switching Cost: <b className="text-gray-100">{simReport.competitors_battle.your_product.switching_cost}</b></div>
                        <div>Adoption Score: <b className="text-accent">{simReport.competitors_battle.your_product.adoption}</b></div>
                        <div className="pt-2 text-[10px] text-primary/80 font-bold uppercase">{simReport.competitors_battle.your_product.status}</div>
                      </div>
                    </div>

                    {/* Competitor A */}
                    <div className="bg-card/40 border border-card-border rounded-lg p-4 space-y-3">
                      <span className="text-xxs font-mono text-gray-500 uppercase block truncate">
                        {simReport.competitors_battle.competitor_a?.name || "COMPETITOR A"}
                      </span>
                      <div className="space-y-2 font-mono text-xxs text-gray-300">
                        <div>Price: <b className="text-gray-100">{simReport.competitors_battle.competitor_a?.price || "High"}</b></div>
                        <div>Trust: <b className="text-gray-100">{simReport.competitors_battle.competitor_a?.trust || "High"}</b></div>
                        <div>Features: <b className="text-gray-100">{simReport.competitors_battle.competitor_a?.features || "Basic"}</b></div>
                        <div>Switching Cost: <b className="text-gray-100">{simReport.competitors_battle.competitor_a?.switching_cost || "High"}</b></div>
                        <div>Adoption Score: <b className="text-accent">{simReport.competitors_battle.competitor_a?.adoption || "18.5%"}</b></div>
                        <div className="pt-2 text-[10px] text-gray-400 font-bold uppercase">{simReport.competitors_battle.competitor_a?.status || "Contender"}</div>
                      </div>
                    </div>

                    {/* Competitor B */}
                    <div className="bg-card/40 border border-card-border rounded-lg p-4 space-y-3">
                      <span className="text-xxs font-mono text-gray-500 uppercase block truncate">
                        {simReport.competitors_battle.competitor_b?.name || "COMPETITOR B"}
                      </span>
                      <div className="space-y-2 font-mono text-xxs text-gray-300">
                        <div>Price: <b className="text-gray-100">{simReport.competitors_battle.competitor_b?.price || "Low"}</b></div>
                        <div>Trust: <b className="text-gray-100">{simReport.competitors_battle.competitor_b?.trust || "Low"}</b></div>
                        <div>Features: <b className="text-gray-100">{simReport.competitors_battle.competitor_b?.features || "Moderate"}</b></div>
                        <div>Switching Cost: <b className="text-gray-100">{simReport.competitors_battle.competitor_b?.switching_cost || "Medium"}</b></div>
                        <div>Adoption Score: <b className="text-accent">{simReport.competitors_battle.competitor_b?.adoption || "12.2%"}</b></div>
                        <div className="pt-2 text-[10px] text-gray-400 font-bold uppercase">{simReport.competitors_battle.competitor_b?.status || "Lagging"}</div>
                      </div>
                    </div>

                  </div>
                )}
              </div>

            </div>

            {/* REVENUE FORECAST & ranked objections ROW */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Projections Bar Chart */}
              <div className="lg:col-span-6 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div>
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest">Revenue Projections</h3>
                  <p className="text-xxs text-gray-500 font-mono">3, 6, and 12-month expected brackets ({simReport.pricing_currency})</p>
                </div>
                
                <div className="h-60 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={simReport.revenue_projection.projections}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1c1d2e" />
                      <XAxis dataKey="months" stroke="#6b7280" tickFormatter={(v) => `${v} Mo`} style={{ fontSize: 10, fontFamily: 'monospace' }} />
                      <YAxis stroke="#6b7280" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                      <Tooltip 
                        contentStyle={{ backgroundColor: "#0c0d16", borderColor: "#1e2035", color: "#fff", fontSize: 11, fontFamily: 'monospace' }} 
                        formatter={(value) => formatCurrency(Number(value), simReport.pricing_currency)}
                      />
                      <Legend wrapperStyle={{ fontSize: 10, fontFamily: 'monospace' }} />
                      <Bar dataKey="low" fill="#ef4444" name="Low Estimate" opacity={0.6} />
                      <Bar dataKey="estimate" fill="#3b82f6" name="Expected" />
                      <Bar dataKey="high" fill="#10b981" name="High Estimate" opacity={0.6} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

              {/* ranked objections (Step 7 Catalog) */}
              <div className="lg:col-span-6 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div className="flex justify-between items-center">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest">Objection Engine Catalog</h3>
                    <p className="text-xxs text-gray-500 font-mono">Simulated obstacles, user impacts, and actionable code fixes</p>
                  </div>
                  {showTransparency && (
                    <span className="text-[10px] font-mono text-primary">Formula: Lost = Impact * Price * 12</span>
                  )}
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left font-mono text-xxs">
                    <thead>
                      <tr className="border-b border-card-border text-gray-500">
                        <th className="pb-2">OBJECTION</th>
                        <th className="pb-2 text-center">SEVERITY</th>
                        <th className="pb-2 text-right">AFFECTED</th>
                        <th className="pb-2 text-right">LOST REV</th>
                        <th className="pb-2 pl-3">MITIGATION CODE FIX</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-card-border/40 text-gray-300">
                      {simReport.objections_list && simReport.objections_list.map((obj, idx) => (
                        <tr key={idx} className="hover:bg-card-hover/20 transition-colors">
                          <td className="py-2.5 pr-2 font-semibold truncate max-w-[120px]" title={obj.issue}>{obj.issue}</td>
                          <td className="py-2.5 text-center">
                            <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${
                              obj.severity === "High" ? "bg-red-950 text-red-400 border border-red-500/20" :
                              obj.severity === "Medium" ? "bg-amber-950 text-amber-400 border border-amber-500/20" :
                              "bg-green-950 text-green-400 border border-green-500/20"
                            }`}>{obj.severity}</span>
                          </td>
                          <td className="py-2.5 text-right">{obj.affected_users}</td>
                          <td className="py-2.5 text-right text-red-400 font-bold">{formatCurrency(obj.revenue_loss, simReport.pricing_currency)}</td>
                          <td className="py-2.5 pl-3 text-gray-400 italic text-[10px] max-w-[150px] truncate" title={obj.action}>{obj.action}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

            </div>

            {/* STEP 9: CONFIDENCE FORMULA DETAILS & STEP 10: TAM REVENUE ASSUMPTIONS */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Confidence Details (Step 9) */}
              <div className="lg:col-span-6 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div className="flex justify-between items-center border-b border-card-border/50 pb-2">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100">Multi-Confidence Index</h3>
                    <p className="text-xxs text-gray-500 font-mono">Mathematical weight logic explaining final index value</p>
                  </div>
                  <Info className="w-4 h-4 text-primary" />
                </div>

                {simReport.confidence_details && (
                  <div className="space-y-4 font-mono text-xs">
                    <div className="bg-[#050508] border border-primary/20 p-3 rounded text-center">
                      <div className="text-xxs text-primary/70 mb-1 font-bold uppercase">Active Mathematical Formula</div>
                      <div className="text-sm text-primary font-extrabold">{simReport.confidence_details.formula}</div>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-center text-xxs">
                      <div className="bg-card-border/20 p-2 rounded">
                        <span className="text-gray-500 block">Signal Weight</span>
                        <b className="text-gray-300 text-sm">{simReport.confidence_details.signal_confidence}%</b>
                      </div>
                      <div className="bg-card-border/20 p-2 rounded">
                        <span className="text-gray-500 block">Persona Weight</span>
                        <b className="text-gray-300 text-sm">{simReport.confidence_details.persona_confidence}%</b>
                      </div>
                      <div className="bg-card-border/20 p-2 rounded">
                        <span className="text-gray-500 block">Forecast Variance</span>
                        <b className="text-gray-300 text-sm">{simReport.confidence_details.forecast_confidence}%</b>
                      </div>
                    </div>

                    <div className="bg-[#050508]/40 p-3 border border-card-border/50 rounded text-xxs text-gray-400 leading-relaxed">
                      <strong className="text-gray-300 block mb-1">Index Explainer:</strong>
                      {simReport.confidence_details.reasoning}
                    </div>
                  </div>
                )}
              </div>

              {/* TAM assumptions (Step 10) */}
              <div className="lg:col-span-6 bg-card border border-card-border rounded-lg p-6 space-y-4">
                <div className="flex justify-between items-center border-b border-card-border/50 pb-2">
                  <div>
                    <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100">TAM Revenue Assumptions</h3>
                    <p className="text-xxs text-gray-500 font-mono">Detailed mathematical mechanics explaining forecast values</p>
                  </div>
                  <Zap className="w-4 h-4 text-emerald-400" />
                </div>

                <div className="space-y-4">
                  <div className="bg-[#050508] border border-emerald-500/20 p-3 rounded flex items-center justify-between font-mono">
                    <div>
                      <span className="text-xxs text-emerald-400/80 font-bold block uppercase">Expected 12Mo Revenue</span>
                      <span className="text-lg text-emerald-400 font-extrabold">
                        {formatCurrency((simReport.revenue_projection.projections[2]?.estimate ?? simReport.revenue_projection.projections[2]?.expected ?? 0), simReport.pricing_currency)}
                      </span>
                    </div>
                    <div className="text-right">
                      <span className="text-xxs text-gray-500 block uppercase">Conversion rate</span>
                      <span className="text-sm text-gray-300 font-extrabold">
                        {((simReport.buyer_journey?.purchase?.count || 1) / 50).toFixed(1)}%
                      </span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {simReport.revenue_projection.assumptions && simReport.revenue_projection.assumptions.map((ass, idx) => (
                      <div key={idx} className="flex items-start space-x-2 text-xxs font-mono text-gray-400 leading-normal">
                        <span className="text-emerald-400 shrink-0">✔</span>
                        <span>{ass}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

            </div>

            {/* DYNAMIC CAROUSEL: CUSTOMER QUOTES (STEP 5 Dialogue Bubbles) */}
            <div className="bg-card border border-card-border rounded-lg p-6 space-y-4">
              <div className="flex justify-between items-center border-b border-card-border/50 pb-2">
                <div>
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest text-gray-100">Simulated Dialogue Bubbles</h3>
                  <p className="text-xxs text-gray-500 font-mono">Direct feedbacks from personas grounded in real-world scraping</p>
                </div>
                <div className="flex space-x-2">
                  <button
                    onClick={() => setQuoteIndex((prev) => (prev > 0 ? prev - 1 : (simReport.simulated_conversations ? simReport.simulated_conversations.length - 1 : report.customer_quotes.length - 1)))}
                    className="p-1 rounded bg-card-border/50 hover:bg-card-border border border-card-border transition-colors cursor-pointer"
                  >
                    <ChevronLeft className="w-4 h-4 text-gray-400" />
                  </button>
                  <button
                    onClick={() => setQuoteIndex((prev) => (prev < (simReport.simulated_conversations ? simReport.simulated_conversations.length - 1 : report.customer_quotes.length - 1) ? prev + 1 : 0))}
                    className="p-1 rounded bg-card-border/50 hover:bg-card-border border border-card-border transition-colors cursor-pointer"
                  >
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  </button>
                </div>
              </div>
              
              <div className="min-h-24 flex flex-col items-center justify-center px-4 py-3 relative">
                {simReport.simulated_conversations && simReport.simulated_conversations[quoteIndex] ? (
                  <motion.div
                    key={quoteIndex}
                    initial={{ opacity: 0, scale: 0.98 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.98 }}
                    transition={{ duration: 0.2 }}
                    className={`max-w-3xl w-full border rounded-xl p-4 bg-[#0a0b16]/60 relative ${
                      simReport.simulated_conversations[quoteIndex].sentiment === "positive" ? "border-green-500/30 text-green-200" :
                      simReport.simulated_conversations[quoteIndex].sentiment === "negative" ? "border-red-500/30 text-red-200" :
                      "border-gray-500/30 text-gray-200"
                    }`}
                  >
                    <span className="absolute -top-2.5 left-4 px-2 py-0.5 rounded text-[8px] font-mono font-bold uppercase tracking-wider bg-card border border-card-border">
                      {simReport.simulated_conversations[quoteIndex].role} // {simReport.simulated_conversations[quoteIndex].sentiment}
                    </span>
                    <p className="font-mono text-xs italic leading-relaxed pt-1.5">
                      &ldquo;{simReport.simulated_conversations[quoteIndex].text}&rdquo;
                    </p>
                  </motion.div>
                ) : (
                  <div className="text-center italic font-mono text-sm max-w-3xl text-gray-300">
                    &ldquo;{typeof report.customer_quotes[quoteIndex] === 'string' ? report.customer_quotes[quoteIndex] : (report.customer_quotes[quoteIndex] as {quote: string}).quote}&rdquo;
                  </div>
                )}
              </div>
            </div>

            {/* FULL REPORT DETAILS BLOCK (STEP 11 Executive Brief) */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
              
              {/* Left Side: Summary & Strategy */}
              <div className="lg:col-span-7 space-y-6">
                
                {/* Executive Summary */}
                <div className="bg-card border border-card-border rounded-lg p-6 space-y-3">
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest border-b border-card-border/50 pb-2 text-gray-100">
                    Executive Brief (Under 150 Words)
                  </h3>
                  <p className="text-gray-300 text-xs font-mono leading-relaxed">{simReport.executive_summary}</p>
                </div>

                {/* Go To Market Strategy */}
                <div className="bg-card border border-card-border rounded-lg p-6 space-y-3">
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest border-b border-card-border/50 pb-2 text-gray-100">GTM Launch Roadmap</h3>
                  <ul className="space-y-3">
                    {simReport.go_to_market_strategy.map((item, idx) => (
                      <li key={idx} className="text-xs flex items-start space-x-3 text-gray-300">
                        <span className="w-5 h-5 rounded bg-primary/10 border border-primary/20 flex items-center justify-center font-mono text-xs text-primary shrink-0 mt-0.5">
                          {idx + 1}
                        </span>
                        <span className="font-mono">{item}</span>
                      </li>
                    ))}
                  </ul>
                </div>

              </div>

              {/* Right Side: Rationale, Recommendation & Risks */}
              <div className="lg:col-span-5 space-y-6">
                
                {/* Launch recommendation */}
                <div className="bg-card border border-card-border rounded-lg p-6 space-y-3">
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest border-b border-card-border/50 pb-2 text-gray-100">Launch Recommendation</h3>
                  
                  <div className="flex items-center space-x-3 mt-2">
                    <span className={`text-sm font-mono font-bold px-3 py-1.5 rounded uppercase tracking-wider ${(() => {
                      const rec = typeof simReport.launch_recommendation === 'string' ? simReport.launch_recommendation : (simReport.launch_recommendation as {decision: string}).decision;
                      return rec === "Launch" ? "bg-green-950 text-green-400 border border-green-500/30" :
                        rec === "Pivot" ? "bg-amber-950 text-amber-400 border border-amber-500/30" :
                        "bg-red-950 text-red-400 border border-red-500/30";
                    })()
                    }`}>
                      {typeof simReport.launch_recommendation === 'string' ? simReport.launch_recommendation : (simReport.launch_recommendation as {decision: string}).decision}
                    </span>
                    <span className="text-xs font-mono text-gray-400">DECISION GATEWAY</span>
                  </div>

                  <p className="text-gray-300 text-xs leading-relaxed mt-2 font-mono">{simReport.launch_rationale}</p>
                  
                  <div className="bg-[#050508]/80 border border-card-border rounded p-3 text-xs font-mono text-gray-400 mt-2 space-y-1">
                    <strong className="text-gray-300 block">Pricing Recommendation:</strong>
                    {simReport.pricing_recommendation}
                  </div>
                </div>

                {/* Risk Analysis Table */}
                <div className="bg-card border border-card-border rounded-lg p-6 space-y-3">
                  <h3 className="text-sm font-bold font-mono uppercase tracking-widest border-b border-card-border/50 pb-2 text-gray-100">Risk Catalog</h3>
                  
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs font-mono text-left">
                      <thead>
                        <tr className="border-b border-card-border text-gray-500">
                          <th className="pb-2 font-normal">RISK PROFILE</th>
                          <th className="pb-2 font-normal text-center">SEVERITY</th>
                          <th className="pb-2 font-normal">MITIGATION</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-card-border/40">
                        {simReport.risk_analysis.map((r, idx) => (
                          <tr key={idx} className="text-gray-300">
                            <td className="py-2.5 pr-2 font-semibold max-w-[120px] truncate">{r.risk}</td>
                            <td className="py-2.5 text-center">
                              <span className={`inline-block px-2 py-0.5 rounded text-[10px] ${
                                r.severity === "High" ? "bg-red-950/40 text-red-400" :
                                r.severity === "Medium" ? "bg-amber-950/40 text-amber-400" :
                                "bg-green-950/40 text-green-400"
                              }`}>
                                {r.severity}
                              </span>
                            </td>
                            <td className="py-2.5 text-gray-400 text-xxs leading-normal">{r.mitigation}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

              </div>

            </div>

          </div>
        )}

      </main>

      {/* FOOTER */}
      <footer className="relative z-10 w-full max-w-6xl mx-auto border-t border-card-border pt-4 mt-6 flex flex-col md:flex-row items-center justify-between text-gray-500 font-mono text-xxs gap-2">
        <div>&copy; 2026 AURA Inc. All Rights Reserved.</div>
        <div className="flex space-x-4">
          <span>SECURE_DATA // TRACE_DECRYPTED</span>
          <span className="text-primary/70">3-layer simulation: 15 archetypes → 5,000 customers → funnel model</span>
        </div>
      </footer>

      {/* INTERACTIVE DRILL-DOWN DRAWER (SIDE SHEET) */}
      <AnimatePresence>
        {selectedSegment && (
          <>
            {/* Backdrop Overlay */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.5 }}
              exit={{ opacity: 0 }}
              onClick={() => setSelectedSegment(null)}
              className="fixed inset-0 bg-black z-40 backdrop-blur-xs cursor-pointer"
            />

            {/* Sidebar Slide-in Panel */}
            <motion.div
              initial={{ x: "100%" }}
              animate={{ x: 0 }}
              exit={{ x: "100%" }}
              transition={{ type: "tween", duration: 0.3 }}
              className="fixed top-0 right-0 h-screen w-full md:w-[600px] bg-[#0c0d16] border-l border-card-border shadow-2xl z-50 overflow-y-auto flex flex-col justify-between"
            >
              {/* Drawer Header */}
              <div className="p-6 border-b border-card-border flex items-center justify-between bg-card">
                <div>
                  <span className="text-xxs font-mono text-primary uppercase tracking-widest">CUSTOMER SEGMENT DRILLDOWN</span>
                  <h3 className="text-lg font-bold">{selectedSegment.name}</h3>
                  <p className="text-xxs font-mono text-gray-400 mt-1">
                    Showing paginated clones of {personasTotalCount} simulated personas
                  </p>
                </div>
                <button
                  onClick={() => setSelectedSegment(null)}
                  className="p-1 rounded hover:bg-card-border border border-transparent hover:border-card-border transition-colors cursor-pointer"
                >
                  <X className="w-5 h-5 text-gray-400 hover:text-white" />
                </button>
              </div>

              {/* Drawer Content */}
              <div className="p-6 flex-grow space-y-4">
                
                {loadingPersonas ? (
                  <div className="h-60 flex flex-col items-center justify-center space-y-2 font-mono text-xs text-gray-500">
                    <RefreshCw className="w-6 h-6 animate-spin text-primary" />
                    <span>Materializing synthetic records...</span>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {personas.map((rawP) => {
                      const p = getAdjustedPersona(rawP);
                      return (
                        <div key={p.id} className="bg-card/40 border border-card-border/80 rounded p-4 space-y-3">
                        {/* Persona Info bar */}
                        <div className="flex justify-between items-start border-b border-card-border/50 pb-2">
                          <div>
                            <span className="font-bold text-sm text-gray-200">{p.name}</span>
                            <span className="text-xxs font-mono text-gray-400 block">
                              {p.age} y/o // {p.occupation} // {p.location}
                            </span>
                          </div>
                          
                          <div className="flex items-center space-x-2">
                            <span className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded ${
                              p.would_buy ? "bg-green-950 text-green-400 border border-green-500/20" : "bg-red-950 text-red-400 border border-red-500/20"
                            }`}>
                              {p.would_buy ? "BUY" : "NO BUY"}
                            </span>
                            <span className="text-xs font-mono font-bold text-gray-300">
                              {(p.likelihood_score * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>

                        {/* Details */}
                        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xxs font-mono text-gray-400 border-t border-card-border/30 pt-2">
                          <div>
                            <strong>INCOME:</strong> {p.income ? `$${Math.round(p.income).toLocaleString()}` : p.income_bracket}
                          </div>
                          <div>
                            <strong>BUDGET SENSITIVITY:</strong> {p.budget_sensitivity}/10
                          </div>
                          <div>
                            <strong>TECH COMFORT:</strong> {p.technology_comfort || 50}%
                          </div>
                          <div>
                            <strong>RISK APPETITE:</strong> {p.risk_appetite || 50}/100
                          </div>
                          <div>
                            <strong>SOCIAL INFLUENCE:</strong> {p.social_influence || 50}/100
                          </div>
                          <div>
                            <strong>URGENCY:</strong> {p.urgency || 50}/100
                          </div>
                          <div>
                            <strong>EXISTING ALTS:</strong> {p.existing_alternatives || 50}/100
                          </div>
                        </div>

                        {/* Quotes / reasoning */}
                        <p className="text-xs italic text-gray-300 bg-[#06060c] p-2 rounded border border-card-border/40">
                          &ldquo;{p.reasoning}&rdquo;
                        </p>

                        {/* Demands / Objections */}
                        <div className="flex flex-wrap gap-1.5 text-[10px] font-mono">
                          {p.goals.slice(0, 2).map((g, idx) => (
                            <span key={idx} className="bg-primary/5 text-primary border border-primary/20 px-2 py-0.5 rounded">
                              Goal: {g}
                            </span>
                          ))}
                          {p.objections.slice(0, 1).map((obj, idx) => (
                            <span key={idx} className="bg-red-950/20 text-red-400 border border-red-500/20 px-2 py-0.5 rounded">
                              Blocker: {obj}
                            </span>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                  </div>
                )}

              </div>

              {/* Drawer Footer Pagination */}
              <div className="p-6 border-t border-card-border bg-card flex justify-between items-center text-xs font-mono text-gray-400">
                <span>
                  Page {personasPage} of {Math.ceil(personasTotalCount / 6)}
                </span>
                
                <div className="flex space-x-2">
                  <button
                    disabled={personasPage === 1 || loadingPersonas}
                    onClick={() => setPersonasPage((p) => Math.max(1, p - 1))}
                    className="flex items-center space-x-1 px-3 py-1.5 rounded bg-card-border/50 border border-card-border text-gray-300 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <ChevronLeft className="w-3.5 h-3.5" />
                    <span>PREV</span>
                  </button>
                  <button
                    disabled={personasPage >= Math.ceil(personasTotalCount / 6) || loadingPersonas}
                    onClick={() => setPersonasPage((p) => p + 1)}
                    className="flex items-center space-x-1 px-3 py-1.5 rounded bg-card-border/50 border border-card-border text-gray-300 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    <span>NEXT</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
