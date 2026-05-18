/**
 * Mock intelligence dashboard feed.
 *
 * Shape expected by IntelligenceDashboard — the `insights` array replaces
 * the old `sections[]` shape and carries per-item category + urgency tags.
 *
 * Used when VITE_USE_MOCK=true.
 */

export const MOCK_DASHBOARD_FEED = {
  generated_at: '2026-05-15T08:00:00Z',

  intelligence_brief: {
    headline:
      'AI Deployment Enters a Second Wave Across Finance, Pharma, and Industrial Sectors — Q2 2026',
    executive_summary:
      'Enterprise AI has moved past proof-of-concept. Explainability mandates in finance, FDA clinical-AI approvals in pharma, and quantifiable ROI in manufacturing are driving synchronized adoption across sectors that were skeptical twelve months ago. Export controls on model weights and the EU AI Act enforcement timeline are the primary compliance risks to manage now.',
    key_signals: [
      'Basel IV explainability rules force 23 top-50 banks to replace black-box credit models',
      'FDA Breakthrough Therapy designation for first AI-discovered drug candidate — Pharma R&D timelines compressing',
      'Industrial LLMs on maintenance logs cut unplanned downtime 34% — ROI is now repeatable',
      'BIS model-weight export rule closes the loophole on distributing quantized AI to restricted jurisdictions',
      'EU AI Act high-risk enforcement begins Q3 2026 — 60% of Fortune 500 deployments affected',
    ],
  },

  insights: [
    // ── Important Developments (urgency: high) ────────────────────────────────
    {
      id: 'fin-dev-1',
      category: 'Finance',
      type: 'development',
      urgency: 'high',
      title: 'Basel IV Explainability Mandate Forces Black-Box Credit Model Replacements',
      insight:
        'EBA final guidance on model risk under Basel IV requires decision-level explainability for any model affecting Tier 1 capital. 23 of the top 50 global banks are running parallel replacement programs with Q4 2026 hard deadlines.',
      why_it_matters:
        'Vendors with SHAP-compliant model cards and audit-ready explainability pipelines hold a regulatory moat — a $2.3B replacement market opens this year.',
      sources: [],
    },
    {
      id: 'pharma-dev-1',
      category: 'Pharma',
      type: 'development',
      urgency: 'high',
      title: 'EMA Draft AI/GMP Guidance Requires Human Oversight in Batch Release AI Systems',
      insight:
        'European Medicines Agency draft guidance mandates version-controlled model registries, human oversight mechanisms, and quarterly performance audits for any AI system used in GMP manufacturing. Comment period closes June 2026.',
      why_it_matters:
        'Non-compliance after Q1 2027 risks facility warnings. Pharma manufacturers must implement AI governance frameworks now — the timeline for remediation is already tight.',
      sources: [],
    },
    {
      id: 'trade-dev-1',
      category: 'Export/Trade',
      type: 'development',
      urgency: 'high',
      title: 'BIS Expands Export Controls to Cover Quantized AI Model Weights',
      insight:
        'Bureau of Industry and Security closes the model-weights loophole — transferring quantized AI weights to restricted jurisdictions now requires the same export license as the underlying hardware. Rule effective 30 days after publication.',
      why_it_matters:
        'AI companies with global infrastructure must audit model distribution pipelines immediately. Executive criminal liability for violations creates urgency beyond standard compliance timelines.',
      sources: [],
    },
    {
      id: 'ai-dev-1',
      category: 'AI/Technology',
      type: 'development',
      urgency: 'high',
      title: 'EU AI Act High-Risk System Classifications Begin Enforcement — 60% of F500 Affected',
      insight:
        'Enforcement of Article 10–15 high-risk requirements begins Q3 2026. Systems used in credit decisions, employment screening, and critical infrastructure must have conformity assessments, incident logs, and human oversight by then.',
      why_it_matters:
        'The gap between current AI deployments and compliance requirements is large. Companies that begin gap assessments now have 6 months of runway; those that wait will need emergency remediation.',
      sources: [],
    },

    // ── Industry Insights ─────────────────────────────────────────────────────
    {
      id: 'pharma-news-1',
      category: 'Pharma',
      type: 'industry_news',
      urgency: 'high',
      title: 'FDA Breakthrough Designation for First AI-Discovered Small Molecule Drug',
      insight:
        'Insilico Medicine\'s AI-designed fibrosis candidate ISM001-055 receives FDA Breakthrough Therapy designation after Phase II results showing 44% improvement over standard of care. The compound was identified, designed, and optimized entirely by generative chemistry models.',
      why_it_matters:
        'AI drug discovery graduates from hypothesis to clinical validation. Pharma R&D capital allocation will shift significantly toward computational discovery — pipeline timelines are compressing.',
      sources: [],
    },
    {
      id: 'mfg-news-1',
      category: 'Manufacturing',
      type: 'industry_news',
      urgency: 'high',
      title: 'Industrial LLMs on Maintenance Logs Cut Unplanned Downtime 34% at Siemens and ABB',
      insight:
        'Domain-specific LLMs trained on 10+ years of equipment maintenance records outperform general-purpose models on fault prediction by 40%, with 50ms inference latency suitable for edge deployment. Both companies are expanding to 200+ plant sites.',
      why_it_matters:
        'Industrial AI ROI is now quantifiable, replicable, and publicly disclosed. Adoption in discrete manufacturing will accelerate sharply — this is the reference case for every plant operator pitch.',
      sources: [],
    },
    {
      id: 'ai-news-1',
      category: 'AI/Technology',
      type: 'industry_news',
      urgency: 'medium',
      title: 'Agentic Frameworks Become Primary Enterprise Procurement Filter',
      insight:
        'Gartner 2026 CIO survey: 74% of enterprises now require multi-agent orchestration demonstrations before vendor procurement approval. Single-model AI products are being filtered out of RFP shortlists at the qualification stage.',
      why_it_matters:
        'The dividing line in AI tooling has shifted from model quality to orchestration capability. Vendors without agentic architecture face systematic exclusion from enterprise sales cycles.',
      sources: [],
    },
    {
      id: 'fin-news-1',
      category: 'Finance',
      type: 'industry_news',
      urgency: 'medium',
      title: 'SEC Amends Rule 17a-4 to Permit AI-Authored Equity Research with Human Review Attestation',
      insight:
        'AI-generated equity research can now be distributed to retail investors if the firm discloses AI authorship and attests to human review. Effective Q3 2026 — major brokerages have announced AI research platforms for launch.',
      why_it_matters:
        'AI research platforms can compete directly with sell-side equity desks — a $4B annual market opens. Independent research firms face structural cost-curve pressure.',
      sources: [],
    },
    {
      id: 'trade-news-1',
      category: 'Export/Trade',
      type: 'industry_news',
      urgency: 'medium',
      title: 'Maersk AI Customs Platform Cuts Cross-Border Clearance Time from 4.2 to 1.4 Days',
      insight:
        'ML document classification and risk-scoring deployed across G7 trade lanes reduced customs broker workload 70% and average clearance time 67%. DHL and FedEx report similar results from parallel deployments.',
      why_it_matters:
        'Logistics AI creates durable competitive advantage in cross-border e-commerce. Traditional customs brokers face disintermediation; early adopters capture the margin.',
      sources: [],
    },

    // ── Market Trends ─────────────────────────────────────────────────────────
    {
      id: 'fin-trend-1',
      category: 'Finance',
      type: 'market_trends',
      urgency: 'medium',
      title: 'Real-Time Treasury AI Reduces Working Capital Requirements 12% at Mid-Market Firms',
      insight:
        'AI cash-flow forecasting and automated FX hedging — now accessible to $50M+ revenue firms via cloud treasury platforms — reduces average cash buffer requirements by 12%. CFO adoption rate doubled in 12 months.',
      why_it_matters:
        'Mid-market firms are rapidly substituting AI treasury tools for traditional bank advisory. The advisory fee model faces disintermediation from below the enterprise tier.',
      sources: [],
    },
    {
      id: 'pharma-trend-1',
      category: 'Pharma',
      type: 'market_trends',
      urgency: 'medium',
      title: 'Adaptive AI Trial Design Compresses Phase II Timelines from 3.5 to 2.1 Years',
      insight:
        'Bayesian ML adaptive designs — now standard at Pfizer, Roche, and AstraZeneca — reduce patient enrollment time and improve dose-finding efficiency, cutting average Phase II duration 40%. CROs without adaptive-design capabilities are losing contract renewals.',
      why_it_matters:
        'Every year saved in Phase II is $300–500M in patent-protected revenue. This reshapes R&D ROI across the top 20 Pharma firms and creates capability requirements for contract research.',
      sources: [],
    },
    {
      id: 'ai-trend-1',
      category: 'AI/Technology',
      type: 'market_trends',
      urgency: 'medium',
      title: 'MoE Inference Reaches Dense-Model Quality at 20% Cost — Unit Economics Shift Permanently',
      insight:
        'Mixture-of-Experts models using learned expert routing achieve GPT-4-class benchmark parity at one-fifth the serving cost. The quality-cost tradeoff that justified model tiering has collapsed for most production workloads.',
      why_it_matters:
        'AI product gross margins improve structurally. The unit economics argument for building AI-native products is now unambiguous — the barrier is GTM, not infrastructure cost.',
      sources: [],
    },
    {
      id: 'mfg-trend-1',
      category: 'Manufacturing',
      type: 'market_trends',
      urgency: 'medium',
      title: 'AI Vision Inspection Achieves 99.97% Defect Detection in Semiconductor Fab Lines',
      insight:
        'Computer vision models trained on synthetic data reach near-human inspection accuracy at 10x throughput in 28nm and below process nodes. TSMC and Samsung have committed to full-line deployment by end of 2026.',
      why_it_matters:
        'Quality inspection labor in semiconductor manufacturing is structurally at risk. AI inspection becomes table stakes for competitive fab operations — laggards face yield disadvantage.',
      sources: [],
    },
    {
      id: 'trade-trend-1',
      category: 'Export/Trade',
      type: 'market_trends',
      urgency: 'low',
      title: 'WTO AI Trade Facilitation Framework Enters Multilateral Negotiation — 47 Countries',
      insight:
        'A WTO-led framework for AI-assisted trade document standards would harmonize HS code classification, certificate-of-origin verification, and duty-drawback processing across signatory nations. Ratification expected 2027–2028.',
      why_it_matters:
        'Standardized AI trade facilitation could reduce global trade friction costs by $280B annually. Trade finance platforms and customs technology vendors should monitor negotiation texts for early-mover positioning.',
      sources: [],
    },

    // ── Research & Discoveries ────────────────────────────────────────────────
    {
      id: 'mfg-research-1',
      category: 'Manufacturing',
      type: 'technical_discovery',
      urgency: 'medium',
      title: 'Digital Twin + LLM Fusion Enables Natural Language Process Control in Automotive Plants',
      insight:
        'BMW\'s pilot connects a process digital twin to an LLM reasoning layer, allowing line engineers to query fault-causation in plain English with full root-cause tracing. Diagnostic accuracy matches senior process engineers; training time for junior staff compressed 60%.',
      why_it_matters:
        'Democratizes process engineering expertise across skill levels — and creates a replicable pattern for any capital-intensive plant with existing sensor and historian infrastructure.',
      sources: [],
    },
    {
      id: 'ai-research-1',
      category: 'AI/Technology',
      type: 'technical_discovery',
      urgency: 'low',
      title: 'Speculative Decoding Cuts LLM Latency 30–50% with No Quality Trade-off',
      insight:
        'A small draft model proposes tokens; the main model verifies batches in parallel. This achieves 3–4x token throughput on the verification step. Major inference providers have deployed it silently — users see faster responses without knowing the mechanism changed.',
      why_it_matters:
        'Both first-token latency and throughput improve simultaneously. Understanding speculative decoding separates engineers who consume AI APIs from those who can evaluate, optimize, and operate inference stacks.',
      sources: [],
    },
    {
      id: 'pharma-research-1',
      category: 'Pharma',
      type: 'technical_discovery',
      urgency: 'low',
      title: 'AlphaFold 3 Extends Protein Structure Prediction to DNA, RNA, and Small-Molecule Interactions',
      insight:
        'AlphaFold 3 predicts joint structures of proteins with DNA, RNA, and small molecules at accuracy exceeding previous specialist tools. Wet-lab validation turnaround for computational hits has dropped from weeks to days at leading discovery labs.',
      why_it_matters:
        'The bottleneck in structure-based drug design has shifted from computation to chemistry synthesis. Medicinal chemists who can interpret AlphaFold 3 outputs are the new rate-limiting resource.',
      sources: [],
    },
    {
      id: 'fin-research-1',
      category: 'Finance',
      type: 'technical_discovery',
      urgency: 'low',
      title: 'Temporal Graph Networks Achieve State-of-the-Art Fraud Detection on Real-Time Transaction Graphs',
      insight:
        'TGN models that encode transaction timing and graph topology outperform gradient-boosted trees by 18% on fraud recall at equal precision. Deployment requires streaming graph infrastructure — Kafka + graph DB — that most mid-tier banks lack.',
      why_it_matters:
        'The accuracy gap is large enough to justify infrastructure investment. Fraud teams that build or buy TGN capability gain a measurable risk reduction advantage over rule-based and tabular-ML incumbents.',
      sources: [],
    },
  ],

  learning_track: [
    {
      id: 'l-1',
      category: 'Finance',
      title: 'Explainable AI for Financial Risk Models (SHAP, LIME, Model Cards)',
      reason: 'Basel IV compliance creates immediate billable demand — this is deployable expertise in weeks.',
      difficulty: 'intermediate',
      estimated_time: '4 hours',
      chat_connection: null,
    },
    {
      id: 'l-2',
      category: 'AI/Technology',
      title: 'Multi-Agent Orchestration Patterns (LangGraph, AutoGen)',
      reason: '74% of enterprise procurement now screens for agentic capability — this is a procurement gate.',
      difficulty: 'advanced',
      estimated_time: '6 hours',
      chat_connection: 'Builds directly on the LLM fundamentals from your recent chat sessions.',
    },
    {
      id: 'l-3',
      category: 'Manufacturing',
      title: 'Industrial IoT + Digital Twin Architecture for AI Integration',
      reason: 'The BMW/Siemens pattern is replicating across manufacturing — understanding this architecture is essential for industrial AI work.',
      difficulty: 'intermediate',
      estimated_time: '3 hours',
      chat_connection: null,
    },
    {
      id: 'l-4',
      category: 'Pharma',
      title: 'AI Regulatory Compliance in GxP Environments (21 CFR Part 11, EMA AI/GMP)',
      reason: 'EMA guidance creates immediate advisory demand — firms need people who understand both AI systems and pharma regulation.',
      difficulty: 'beginner',
      estimated_time: '2 hours',
      chat_connection: null,
    },
    {
      id: 'l-5',
      category: 'Export/Trade',
      title: 'AI Export Control Compliance — BIS EAR, CCL, and Model Weight Classification',
      reason: 'The BIS model-weights rule creates criminal liability exposure — understanding the regulatory framework is immediate risk management.',
      difficulty: 'beginner',
      estimated_time: '2 hours',
      chat_connection: null,
    },
  ],

  action_items: [
    'Audit any production systems that transfer AI model artifacts or weights to international infrastructure — check against the updated BIS CCL restricted jurisdiction list.',
    'Run SHAP analysis on any ML model you own that touches a credit, risk, or compliance decision — generate and store the explanation artifacts.',
    'Review the EMA draft AI/GMP guidance (published May 2026) and identify 3 projects or clients where the governance requirements would apply — start a gap assessment template.',
    'Set up an adaptive Bayesian experiment using scipy.stats or PyMC — directly applicable to any sequential optimization problem and directly replicable to trial design patterns.',
  ],
}
