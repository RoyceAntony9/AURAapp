The app renders UI but nearly every computed number is NaN, and several 
"AI-generated" looking sections are actually hardcoded/templated, not 
derived from the actual simulation. This is a SINGLE ROOT CAUSE problem 
that cascades everywhere. Fix the root cause, then fix each symptom 
specifically listed below. No section may ship with hardcoded numbers, 
fake formulas, or static text that doesn't change per product.

═══════════════════════════════════════
ROOT CAUSE — FIND THIS FIRST
═══════════════════════════════════════
Every NaN traces back to ONE of these. Check ALL of them in this order 
before touching any UI component:

1. Open the actual API response JSON for a completed job 
   (GET /simulate/{job_id}/result) and inspect it RAW in browser devtools 
   or Postman — do NOT assume the backend is sending correct data because 
   the pipeline "completed". Print the full JSON. Find every field that is 
   `null`, `undefined`, missing entirely, or a string like "NaN".

2. For each NaN field, trace backwards:
   - Is the backend computing this field at all? (grep the forecast/report 
     engine code for the field name — if it's not computed anywhere, that's 
     the bug)
   - If computed, what is it dividing/multiplying? Print the INPUT values 
     to that calculation. A NaN almost always means one operand was 
     undefined, null, 0/0, or a string being used in arithmetic.
   - Is the frontend reading the CORRECT field name? Compare the Pydantic/
     TypeScript response model field names against what the React 
     components are destructuring — a single typo (e.g. backend sends 
     `adoption_pct`, frontend reads `adoptionPercentage`) silently 
     produces `undefined` → NaN on any arithmetic/formatting.

3. Check if persona expansion (archetypes → 5000) is actually populating 
   a real array before forecast/social-influence stages run, or if 
   forecast is running against an EMPTY array (length 0), which makes 
   every average/percentage `0/0 = NaN`.

DO NOT patch individual NaN displays with `|| 0` or `?? "N/A"` band-aids 
as the primary fix — that hides the bug rather than fixing the broken 
calculation. Fix the actual data flow. (`|| 0` masking is only acceptable 
as a LAST-RESORT defensive guard AFTER the real calculation is fixed, in 
case of genuinely unexpected edge cases.)

═══════════════════════════════════════
SPECIFIC BROKEN SECTIONS — FIX EACH
═══════════════════════════════════════

### A. "Market Reception NaN/100", "Weak Fit"
- This must be the PMF score computed from the formula already specified: 
  weighted combination of mean excitement_score, buy-intent %, objection 
  penalty, sentiment alignment — computed from the REAL expanded persona 
  array's actual values.
- "Weak Fit" label is currently hardcoded as a fallback for NaN — once the 
  score is real, the label must be dynamically derived from the score band 
  (0-39/40-69/70-100), and must DIFFER across different product ideas. 
  Test with two very different ideas and confirm the label changes.

### B. "12mo Revenue Expected: $NaN, Low: $NaN, High: $NaN"
- Confirm the TAM estimation LLM call is actually being made and its result 
  is being passed into the revenue formula — print the TAM value to logs. 
  If TAM is never fetched/stored, revenue = adoption% × undefined × price 
  = NaN.
- Confirm `adoption_%_at_period` for 12mo is reading the FINAL (cycle 5) 
  adoption value from the social influence engine's output array, not an 
  index that doesn't exist.
- low/high range formula depends on confidence_score — confirm 
  confidence_score itself isn't NaN (same root-cause check applies to it).

### C. "TOP OBJECTION: High Price / Subscription... Reported by 18% of personas"
- This one is partially working (18% is a real number) — but verify "18%" 
  isn't itself a hardcoded placeholder that happens to look plausible. 
  Trace it to the actual objection-counting code: count occurrences of each 
  objection string across all 5000 expanded personas, rank by frequency, 
  compute % = count/total. Confirm this changes per product idea.

### D. "FINAL ADOPTION %: NaN% — Reached in Adoption Cycle 5"
- This is THE core metric and must be: 
  `(personas with would_buy=true after cycle 5 adjustment) / total_personas * 100`
- If this is NaN, total_personas is almost certainly 0 or undefined at the 
  point this division happens — fix the expansion-before-forecast ordering/
  await bug.
- "Reached in Adoption Cycle 5" — confirm this isn't a hardcoded string. It 
  should reflect which cycle the adoption % stabilized/plateaued (compute 
  cycle-to-cycle delta; if delta < threshold for 2 consecutive cycles, that's 
  the "reached" cycle — or simplest: always report cycle 5 as "final" if you 
  don't want to compute plateau detection, but be HONEST that it's "final 
  cycle value" not "reached at" — relabel to "Final Adoption % (Cycle 5)" 
  if plateau detection isn't implemented).

### E. "AURA Market Friction & Realism Engine" — Product Market Fit: NaN/100, 
   but Launch Difficulty 27.4, Trust Barrier 40, Habit Change 25, Price 
   Acceptance 94, Social Adoption 75 all show numbers
- PMF here is the SAME score as section A — both must read from the same 
  computed pmf_score field, not two different (one broken) calculations. 
  Check for DUPLICATE/INCONSISTENT field names across the codebase (e.g. 
  `pmf_score` computed in one place, `product_market_fit` referenced 
  elsewhere as a different uncalculated field).
- Verify Trust Barrier, Habit Change, Price Acceptance, Social Adoption are 
  NOT hardcoded constants that happen to look reasonable — trace each to a 
  computation involving the actual signal/persona data. If ANY of these 5 
  metrics is a static number that never changes regardless of product idea, 
  that is a hardcoded placeholder and must be replaced with a real 
  calculation derived from persona/signal data (e.g. Trust Barrier could be 
  derived from sentiment_alignment + competitor trust signals; Habit Change 
  could be derived from how many personas' `buying_behavior` mentions 
  switching costs/habit).

### F. Scenario Lab Console — "Expected Adoption: NaN%" for Half Price / 
   Current Price / Premium Price, while "Launch Difficulty" shows real 
   numbers (27.3, 27.4, 27.9)
- This is a CLIENT-SIDE re-simulation feature (per "client-side re-simulation 
  complete" text seen elsewhere) — it's recomputing adoption based on price 
  changes WITHOUT calling the backend again, using some local formula.
- Find this local formula. It's referencing a field for "expected adoption" 
  that is NaN at its SOURCE — i.e., the base adoption_% from the original 
  simulation result is itself NaN (same root cause as D), so every scenario 
  variant inherits NaN. Once D is fixed, these should auto-resolve IF the 
  scenario formula correctly references the fixed field name.
- Verify the scenario formula actually produces DIFFERENT adoption % for 
  different prices (it should — lower price → higher adoption, scaled by 
  the persona population's budget_sensitivity distribution from real data), 
  not just copy the same base number to all three rows.

### G. "Conversion Funnel" — "NaN users (96%)", "NaN users (NaN%)" etc., but 
   percentages like 96%, 21%, 0%, 85% appear correctly in some rows
- The PERCENTAGES here seem to be hardcoded/templated funnel-stage defaults 
  (96%, X%, X%, 21%, 0%, 85% — classic generic funnel template numbers) — 
  verify by testing with a different product idea: if these percentages 
  DON'T change, they are hardcoded and must be replaced with real 
  calculations derived from persona likelihood_score distributions binned 
  into funnel stages (Awareness = always reachable %, Interest = % with 
  likelihood > 0.2, Evaluation = % with likelihood > 0.4, Trial = % with 
  would_buy intent, Purchase = % with likelihood > 0.7 AND would_buy=true, 
  Retention = purchase % × retention_rate_assumption).
- "NaN users" — this is `(percentage/100) * total_personas` where 
  total_personas is undefined (same root cause as D). Fix total_personas 
  availability and this resolves.
- "5. Purchase: NaN users (0%)" — 0% purchase is almost certainly itself 
  wrong/hardcoded (a real simulation should never show literal 0% purchase 
  intent across 5000 personas for ANY product) — verify this isn't a 
  default/fallback value being used because the real calculation failed 
  and fell back to 0.

### H. "Competitor Battle Mode" — Shows Salesforce/HubSpot for an "AI 
   writing/productivity assistant" product
- These names ARE plausible for this specific product (productivity SaaS), 
  so this MAY be working correctly via LLM general knowledge fallback as 
  designed. BUT verify: "Your Product — Adoption Score: NaN%" while 
  Salesforce shows 38% and HubSpot shows 21% — Your Product's score is the 
  SAME final_adoption_% from section D (NaN root cause). Fix D and confirm 
  this auto-resolves and shows a real comparable percentage.
- Test with a completely different product (e.g. a physical hardware 
  product, a healthcare app) and confirm the 3 competitors shown are 
  DOMAIN-APPROPRIATE and different — not always Salesforce/HubSpot 
  regardless of input.

### I. "Revenue Projections" chart (3/6/12 Mo) — completely empty, no bars
- Chart data array is being built from the same NaN revenue_projection 
  object (section B). Fix B; confirm the Recharts BarChart data prop 
  receives `[{period: "3mo", value: number}, ...]` with real finite numbers, 
  not NaN (Recharts silently renders nothing for NaN values — it won't 
  even throw an error, which is why the chart area is blank with no console 
  error).

### J. "Rogers Innovation Diffusion Curve" — completely empty chart, but 
   legend shows 5 categories (Early Adopters, Early Majority, Innovators, 
   Laggards, Late Majority)
- Same as I — the Social Influence Engine's per-cycle, per-segment adoption 
  data array is either empty or all-NaN. Print this array directly: it 
  should be shape `[{cycle: 0, "Early Adopters": 0.05, "Innovators": 0.02, 
  ...}, {cycle: 1, ...}, ... {cycle: 5, ...}]` with REAL increasing 
  percentages per cycle (diffusion should show growth curves, not flat 
  lines). If this array is empty, the social influence engine isn't 
  persisting per-cycle snapshots — fix it to store a snapshot after EACH 
  of the 5 cycles, not just the final result.

### K. "Market Clusters" donut — shows "5,000" total and 13 segments with 
   percentages — THIS APPEARS TO BE WORKING. Verify segment names/% are 
   actually derived from real persona clustering and not a static list of 
   13 segment names that always appears regardless of product (test with 
   a different idea — do segment names like "Regulated Industries", 
   "Frontline Workers" make sense for THAT product too, or do they look 
   copy-pasted?). If static, fix the clustering step to generate segment 
   names/counts from the actual persona archetype `segment` field 
   distribution.

### L. "TAM Revenue Assumptions" box
- "Expected 12mo Revenue: $NaN" — same as B.
- "Conversion rate modeled as NaN% of total addressable market" — this 
  sentence template references a conversion_rate field that is NaN. Find 
  where conversion_rate should be set (likely = final adoption % from D, 
  or a derived purchase-stage % from G) and wire it through.
- "CONVERSION RATE: 0.0%" displayed top-right contradicts "NaN%" in the 
  bullet below it — TWO DIFFERENT CODE PATHS are rendering this value 
  inconsistently (one shows 0.0 as a fallback, one shows NaN with no 
  fallback). Unify to ONE source field.
- "Retention rate assumed at 82% year-on-year based on peer cohorts" — 
  verify 82% isn't hardcoded. If it never changes across products, it's a 
  placeholder — either compute it from persona retention behavior data, or 
  if you're intentionally using an industry-benchmark constant, clearly 
  label it as such ("Industry benchmark: 82%") rather than implying it's 
  derived from THIS simulation's "peer cohorts" (which it currently falsely 
  implies).

### M. "Multi-Confidence Index" — "Final = (Signal * Persona * Forecast) / 
   10000", Signal Weight 85%, Persona Weight 85%, Forecast Variance 60%
- These look like STATIC PLACEHOLDER NUMBERS (85%, 85%, 60% — suspiciously 
  round, and the formula `/10000` for percentages that are already 0-100 
  scale is mathematically suspect: 85*85*60/10000 = 43.35, which conveniently 
  matches the "43%" mentioned in the explainer text below — meaning this 
  ENTIRE WIDGET might be hardcoded to always show this same example).
- Test with a different product idea: if Signal Weight, Persona Weight, 
  Forecast Variance, and the resulting "Final" % are IDENTICAL every time, 
  this entire component is fake. Fix by computing real values:
  - Signal Weight = data quality/completeness score from Signal Engine 
    (e.g. based on how many real vs synthetic-fallback sources were used)
  - Persona Weight = variance/consistency measure across archetype responses 
    (low variance = high confidence)
  - Forecast Variance = spread between low/high revenue range from section B
  - Final confidence_score = some real weighted formula using these three — 
    and THIS confidence_score must be the SAME one used in section B's 
    low/high revenue range calculation (single source of truth)
- "Confidence adjusts to 43% based on new inputs. Pricing shifts affect 
  forecast predictability." — this sentence must be templated with the 
  REAL confidence_score and must change per product/scenario, not be a 
  static sentence with a static 43%.

### N. "Simulated Dialogue Bubbles" — Shows: "As Software Engineer 
   (Innovators), my funnel: discover 90% → care 58% → try 93% → convert 
   86% → retain 87%. Price acceptance 96%, overall likelihood 65%."
- THIS IS NOT A CUSTOMER REVIEW QUOTE. This is raw simulation telemetry 
  data formatted as if it were a quote. This completely fails the previously 
  specified requirement for natural, varied, product-specific review quotes.
- REPLACE ENTIRELY: this widget must call the LLM (as specified previously) 
  to generate natural-language review quotes based on persona reasoning — 
  e.g. "As a software engineer who's tried three note-taking apps already, 
  I'm skeptical this will actually save me time, but the auto-summarization 
  feature is tempting enough that I'd try the free trial." NOT funnel 
  percentages in quote marks.
- The label "4 // POSITIVE" + persona role ("Software Engineer (Innovators)") 
  as a tag/header is fine to keep — but the quote BODY must be the natural 
  LLM-generated review text, never raw numbers/percentages.

### O. "Executive Brief (under 150 words)"
- Current text: "AURA client-side re-simulation complete. Launch Difficulty 
  is 27.4/100. Product Market Fit score is NaN/100. Launch recommendation: 
  Delay or Pivot."
- This violates the previously specified requirement TWICE: (1) it mentions 
  "AURA" and "re-simulation" (meta-commentary about the tool itself), and 
  (2) it's a templated string with raw metric numbers, not a written 
  strategic brief.
- REPLACE ENTIRELY with the LLM-generated executive summary as previously 
  specified: 2-3 paragraphs of strategic advice TO THE FOUNDER about THEIR 
  PRODUCT, zero mentions of AURA/simulation/re-simulation, written in 
  prose — not "Metric X is Y/100" sentence templates.
- Once PMF (NaN) is fixed via root-cause fix, confirm this section is 
  ACTUALLY calling the LLM report-generation function and not falling back 
  to a hardcoded template string when something upstream is missing.

### P. "Launch Recommendation: DELAY OR PIVOT" + "Based on the simulation 
   data showing 84% adoption potential and moderate launch difficulty, you 
   should proceed with a phased launch..."
- INTERNAL CONTRADICTION: the badge says "DELAY OR PIVOT" but the text 
  below it says "you should proceed with a phased launch" — these are 
  opposite recommendations generated independently and never reconciled.
- Also "84% adoption potential" here doesn't match "NaN%" final adoption 
  shown elsewhere (section D) — another inconsistent-source-of-truth bug. 
  84% appears to be a hardcoded example value in this specific text 
  template.
- FIX: launch_recommendation badge (Launch/Pivot/Delay/Kill) and its 
  rationale text MUST come from the SAME LLM call/output object, using the 
  SAME final adoption_% (section D) as input — never two separate 
  generations that can disagree. Also mentions "the simulation data" — 
  remove per the AURA-meta-commentary rule (section O).

═══════════════════════════════════════
MANDATORY CROSS-CUTTING FIXES
═══════════════════════════════════════

1. **SINGLE SOURCE OF TRUTH FOR CORE METRICS**: Create one canonical 
   `ForecastResult` object (Pydantic model) containing: `pmf_score`, 
   `final_adoption_pct`, `confidence_score`, `revenue_projection`, 
   `conversion_rate`. EVERY UI component that displays any of these 
   values reads from THIS object via the API response — never recomputes 
   or re-derives its own version. Grep the codebase for every place these 
   5 concepts are computed and consolidate to ONE computation each.

2. **HARDCODED-CONTENT AUDIT**: grep the ENTIRE codebase (frontend + 
   backend) for: literal percentage strings (`"85%"`, `"60%"`, `"82%"`, 
   `"96%"`, `"21%"`, `"38%"`, `"84%"`), hardcoded company names 
   ("Salesforce", "HubSpot" as defaults rather than LLM output), and any 
   string template containing "AURA", "simulation", "re-simulation", 
   "client-side". Every match must be either (a) deleted and replaced 
   with real computed/LLM-generated content, or (b) if it's a genuinely 
   fixed constant (like a named formula weight you're intentionally 
   choosing), clearly justified and labeled as such in the UI.

3. **NaN-PROOF TYPE LAYER**: Define a shared TypeScript type for the full 
   `/simulate/{job_id}/result` response, generated from (or matching 
   exactly) the backend Pydantic model. Frontend components must be typed 
   against this — if a field name mismatch exists, TypeScript will error 
   at compile time instead of silently producing `undefined` → NaN at 
   runtime.

4. **TWO-PRODUCT DIFFERENTIAL TEST (run this LAST, as final verification)**: 
   Run the full pipeline for: (a) "AI writing assistant for SaaS, $10/mo, 
   Global" and (b) "Smart water bottle with hydration tracking, $45 
   one-time, US". Produce a side-by-side diff of every metric, chart data 
   array, competitor list, quote set, and executive brief between the two 
   runs. EVERY SINGLE VALUE listed in sections A-P above must differ 
   between (a) and (b) in a domain-plausible way (e.g. competitors for (b) 
   should be hardware/wellness brands, not Salesforce; PMF/adoption/revenue 
   numbers should be different magnitudes appropriate to $10/mo SaaS vs $45 
   hardware). If ANY value is identical between the two runs, that value is 
   still hardcoded/broken and must be fixed before this is considered done.

NO field, chart, or text block may render NaN, "undefined", an empty chart 
with no error message, or content that is identical across different 
product inputs. Every number on every page must trace to a real 
calculation against real simulation output for THAT specific job_id.