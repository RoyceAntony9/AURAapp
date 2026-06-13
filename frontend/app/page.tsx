"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { 
  Sparkles, 
  Cpu, 
  TrendingUp, 
  MapPin, 
  Clock, 
  DollarSign, 
  Zap, 
  AlertCircle 
} from "lucide-react";

export default function LandingPage() {
  const router = useRouter();
  
  // Form States
  const [idea, setIdea] = useState("");
  const [industry, setIndustry] = useState("SaaS");
  const [market, setMarket] = useState("");
  const [priceAmount, setPriceAmount] = useState("");
  const [priceCurrency, setPriceCurrency] = useState("USD");
  const [region, setRegion] = useState("Global");
  const [timeline, setTimeline] = useState("3-6mo");
  
  // Validation / Loading States
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  const validate = () => {
    const newErrors: Record<string, string> = {};
    if (!idea || idea.length < 20) {
      newErrors.idea = "Product idea description must be at least 20 characters.";
    }
    if (!market || market.trim().length === 0) {
      newErrors.market = "Target market description is required.";
    }
    if (!priceAmount || isNaN(Number(priceAmount)) || Number(priceAmount) <= 0) {
      newErrors.price = "Pricing amount must be a positive number.";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setApiError(null);
    
    if (!validate()) return;
    
    setIsSubmitting(true);
    
    const payload = {
      idea,
      industry,
      market,
      pricing: {
        amount: parseFloat(priceAmount),
        currency: priceCurrency
      },
      region,
      timeline
    };

    try {
      const response = await fetch("http://localhost:8000/simulate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
      });
      
      if (!response.ok) {
        throw new Error(`Server returned error: ${response.statusText}`);
      }
      
      const data = await response.json();
      const jobId = data.job_id;
      
      // Cache inputs for retry support on dashboard
      sessionStorage.setItem("last_simulation_request", JSON.stringify(payload));
      
      // Redirect to the dashboard
      router.push(`/dashboard/${jobId}`);
    } catch (err: any) {
      setIsSubmitting(false);
      setApiError(err.message || "Failed to connect to simulation server. Make sure the backend API is running on port 8000.");
    }
  };

  return (
    <div className="min-h-screen relative flex flex-col justify-between p-6 md:p-12">
      {/* Decorative Orbs */}
      <div className="glow-orb-1" />
      <div className="glow-orb-2" />

      {/* Header */}
      <header className="relative z-10 w-full max-w-6xl mx-auto flex items-center justify-between border-b border-card-border pb-4 mb-6">
        <div className="flex items-center space-x-2">
          <div className="w-8 h-8 rounded bg-gradient-to-tr from-primary to-accent flex items-center justify-center font-mono font-bold text-background text-lg shadow-[0_0_15px_rgba(0,240,255,0.4)]">
            A
          </div>
          <span className="font-mono text-xl font-bold tracking-[0.2em] text-foreground">AURA</span>
        </div>
        <div className="text-xs font-mono text-primary/70 bg-card-border/30 px-3 py-1 rounded border border-card-border">
          V1.0.0 // LIVE_SYSTEM
        </div>
      </header>

      {/* Hero & Form Section */}
      <main className="relative z-10 flex-grow w-full max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12 items-center my-6">
        {/* Left Side: Copy */}
        <div className="lg:col-span-5 space-y-6">
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <div className="inline-flex items-center space-x-2 bg-primary/10 border border-primary/20 rounded-full px-3 py-1 text-xs font-mono text-primary mb-4">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Personas-as-a-Service Engine</span>
            </div>
            <h1 className="text-4xl md:text-5xl font-extrabold tracking-tight leading-tight">
              AI-Unified Risk &amp; <br />
              <span className="text-transparent bg-clip-text bg-gradient-to-r from-primary to-accent drop-shadow-[0_0_20px_rgba(0,240,255,0.15)]">
                Revenue Analysis
              </span>
            </h1>
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.2, duration: 0.6 }}
            className="text-gray-400 text-sm md:text-base leading-relaxed"
          >
            Simulate your product idea instantly across a synthesized population of 
            <strong className="text-primary font-semibold"> 5,000 AI agents</strong>. Grounded in real-time signals from Reddit, Google Trends, and global news feeds, AURA models pricing sensitivity, objections, and word-of-mouth adoption curves in seconds.
          </motion.p>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.4, duration: 0.6 }}
            className="grid grid-cols-2 gap-4 border-t border-card-border pt-6 font-mono text-xs text-gray-400"
          >
            <div className="flex items-center space-x-2">
              <Cpu className="w-4 h-4 text-primary" />
              <span>60-100 Seed Archetypes</span>
            </div>
            <div className="flex items-center space-x-2">
              <TrendingUp className="w-4 h-4 text-accent" />
              <span>5-Cycle WOM Diffusion</span>
            </div>
          </motion.div>
        </div>

        {/* Right Side: Interactive Form */}
        <div className="lg:col-span-7">
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            className="bg-card/90 cyber-border rounded-lg p-6 md:p-8 relative overflow-hidden backdrop-blur-md"
          >
            {/* Top grid line */}
            <div className="absolute top-0 left-0 w-full h-[1px] bg-gradient-to-r from-transparent via-primary/30 to-transparent" />
            
            <form onSubmit={handleSubmit} className="space-y-6">
              {apiError && (
                <div className="bg-red-950/40 border border-red-500/30 rounded p-3 text-red-400 text-xs flex items-start space-x-2 font-mono">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{apiError}</span>
                </div>
              )}

              {/* Product Idea Textarea */}
              <div className="space-y-1">
                <label className="block text-xs font-mono text-gray-300 uppercase tracking-widest">
                  1. Product Idea
                </label>
                <textarea
                  value={idea}
                  onChange={(e) => setIdea(e.target.value)}
                  placeholder="Describe your product. E.g., 'An AI code reviewer hook that integrates into Github to automate PR validation and security checkups...'"
                  rows={4}
                  className={`w-full bg-[#050508]/80 text-sm p-3 border rounded font-mono placeholder:text-gray-600 focus:outline-none focus:border-primary transition-colors ${
                    errors.idea ? "border-red-500/50" : "border-card-border"
                  }`}
                />
                {errors.idea ? (
                  <p className="text-red-400 text-xxs font-mono">{errors.idea}</p>
                ) : (
                  <p className="text-gray-500 text-xxs font-mono">Minimum 20 characters. Detail key features and value.</p>
                )}
              </div>

              {/* Row 2: Industry & Target Market */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="block text-xs font-mono text-gray-300 uppercase tracking-widest">
                    2. Industry Sector
                  </label>
                  <select
                    value={industry}
                    onChange={(e) => setIndustry(e.target.value)}
                    className="w-full bg-[#050508]/80 text-sm p-3 border border-card-border rounded font-mono focus:outline-none focus:border-primary text-gray-300"
                  >
                    <option value="SaaS">SaaS (Software-as-a-Service)</option>
                    <option value="E-commerce">E-commerce / Retail</option>
                    <option value="FinTech">FinTech / Finance</option>
                    <option value="Healthtech">Healthtech / Clinical</option>
                    <option value="Consumer Hardware">Consumer Hardware</option>
                    <option value="Other">Other / General</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="block text-xs font-mono text-gray-300 uppercase tracking-widest">
                    3. Target Market
                  </label>
                  <input
                    type="text"
                    value={market}
                    onChange={(e) => setMarket(e.target.value)}
                    placeholder="E.g., Indie hackers & remote developers"
                    className={`w-full bg-[#050508]/80 text-sm p-3 border rounded font-mono placeholder:text-gray-600 focus:outline-none focus:border-primary transition-colors ${
                      errors.market ? "border-red-500/50" : "border-card-border"
                    }`}
                  />
                  {errors.market && <p className="text-red-400 text-xxs font-mono">{errors.market}</p>}
                </div>
              </div>

              {/* Row 3: Price & Region & Timeline */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-1">
                  <label className="block text-xs font-mono text-gray-300 uppercase tracking-widest flex items-center">
                    <DollarSign className="w-3.5 h-3.5 text-gray-400 mr-0.5" />
                    4. Pricing
                  </label>
                  <div className="flex space-x-1">
                    <input
                      type="text"
                      value={priceAmount}
                      onChange={(e) => setPriceAmount(e.target.value)}
                      placeholder="29"
                      className={`w-2/3 bg-[#050508]/80 text-sm p-3 border rounded font-mono placeholder:text-gray-600 focus:outline-none focus:border-primary transition-colors ${
                        errors.price ? "border-red-500/50" : "border-card-border"
                      }`}
                    />
                    <select
                      value={priceCurrency}
                      onChange={(e) => setPriceCurrency(e.target.value)}
                      className="w-1/3 bg-[#050508]/80 text-xs p-3 border border-card-border rounded font-mono focus:outline-none focus:border-primary text-gray-300"
                    >
                      <option value="USD">USD ($)</option>
                      <option value="EUR">EUR (€)</option>
                      <option value="INR">INR (₹)</option>
                    </select>
                  </div>
                  {errors.price && <p className="text-red-400 text-xxs font-mono">{errors.price}</p>}
                </div>

                <div className="space-y-1">
                  <label className="block text-xs font-mono text-gray-300 uppercase tracking-widest flex items-center">
                    <MapPin className="w-3.5 h-3.5 text-gray-400 mr-0.5" />
                    5. Region
                  </label>
                  <select
                    value={region}
                    onChange={(e) => setRegion(e.target.value)}
                    className="w-full bg-[#050508]/80 text-sm p-3 border border-card-border rounded font-mono focus:outline-none focus:border-primary text-gray-300"
                  >
                    <option value="Global">Global</option>
                    <option value="US">United States (US)</option>
                    <option value="EU">European Union (EU)</option>
                    <option value="India">India (IN)</option>
                    <option value="MENA">Middle East / North Africa</option>
                  </select>
                </div>

                <div className="space-y-1">
                  <label className="block text-xs font-mono text-gray-300 uppercase tracking-widest flex items-center">
                    <Clock className="w-3.5 h-3.5 text-gray-400 mr-0.5" />
                    6. Timeline
                  </label>
                  <select
                    value={timeline}
                    onChange={(e) => setTimeline(e.target.value)}
                    className="w-full bg-[#050508]/80 text-sm p-3 border border-card-border rounded font-mono focus:outline-none focus:border-primary text-gray-300"
                  >
                    <option value="<3mo">&lt; 3 Months</option>
                    <option value="3-6mo">3-6 Months</option>
                    <option value="6-12mo">6-12 Months</option>
                    <option value="12mo+">12+ Months</option>
                  </select>
                </div>
              </div>

              {/* Submit Button */}
              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full cursor-pointer relative bg-gradient-to-r from-primary to-accent hover:shadow-[0_0_20px_rgba(0,240,255,0.4)] text-background text-sm font-mono font-bold py-4 px-6 rounded transition-all duration-300 flex items-center justify-center space-x-2 uppercase tracking-wider"
              >
                {isSubmitting ? (
                  <>
                    <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-background" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Running Market Simulation Node...</span>
                  </>
                ) : (
                  <>
                    <Zap className="w-4 h-4" />
                    <span>Run Synthetic Simulation</span>
                  </>
                )}
              </button>
            </form>
          </motion.div>
        </div>
      </main>

      {/* Footer */}
      <footer className="relative z-10 w-full max-w-6xl mx-auto border-t border-card-border pt-4 mt-6 flex flex-col md:flex-row items-center justify-between text-gray-500 font-mono text-xxs gap-2">
        <div>&copy; 2026 AURA Inc. All Rights Reserved.</div>
        <div className="flex space-x-4">
          <span>SECURE_KYC // SHA_256</span>
          <span className="text-primary/70">15 archetypes → 5,000 simulated customers</span>
        </div>
      </footer>
    </div>
  );
}
