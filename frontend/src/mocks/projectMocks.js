/**
 * Mock data for learning projects — daily intelligence packages.
 *
 * Format: each project has 2 pre-baked daily packages.
 * Each package has 5 insight cards: 3 news + 2 educational.
 * Used when VITE_USE_MOCK=true — zero Tavily/Groq calls.
 *
 * Schema per card:
 *   { id, content_type, category, title, summary,
 *     educational_explanation, why_it_matters,
 *     source_links, difficulty, estimated_read_time }
 */

// ─────────────────────────────────────────────────────────────────────────────
// Project metadata
// ─────────────────────────────────────────────────────────────────────────────

export const MOCK_PROJECTS = [
  {
    project_id:      "proj-ai-manufacturing",
    name:            "AI in Manufacturing",
    description:     "Track the application of AI, computer vision, and industrial LLMs across production lines, predictive maintenance, and quality control.",
    keywords:        ["predictive maintenance", "industrial AI", "computer vision", "digital twin", "quality control", "edge inference"],
    difficulty:      "intermediate",
    focus_areas:     ["Predictive Maintenance", "Quality Inspection", "Process Optimization"],
    color:           "blue",
    insight_count:   2,
    last_insight_at: "2026-05-16T07:00:00Z",
    created_at:      "2026-05-01T00:00:00Z",
    updated_at:      "2026-05-16T07:00:00Z",
  },
  {
    project_id:      "proj-indian-pharma",
    name:            "Indian Pharma Exports",
    description:     "Follow regulatory changes, market dynamics, and competitive positioning of Indian pharmaceutical exports to the US, EU, and emerging markets.",
    keywords:        ["USFDA", "generics", "API manufacturing", "export data", "regulatory compliance", "formulation"],
    difficulty:      "intermediate",
    focus_areas:     ["USFDA Compliance", "Generic Drug Markets", "API Supply Chain"],
    color:           "emerald",
    insight_count:   2,
    last_insight_at: "2026-05-15T07:00:00Z",
    created_at:      "2026-05-01T00:00:00Z",
    updated_at:      "2026-05-15T07:00:00Z",
  },
  {
    project_id:      "proj-quant-finance",
    name:            "Quantitative Finance",
    description:     "Build systematic understanding of algorithmic trading, risk modeling, derivatives pricing, and the application of ML to financial markets.",
    keywords:        ["algorithmic trading", "risk modeling", "derivatives", "factor models", "portfolio optimization", "ML in finance"],
    difficulty:      "advanced",
    focus_areas:     ["Factor Models", "Options Pricing", "ML Trading Strategies"],
    color:           "violet",
    insight_count:   2,
    last_insight_at: "2026-05-14T07:00:00Z",
    created_at:      "2026-05-01T00:00:00Z",
    updated_at:      "2026-05-14T07:00:00Z",
  },
  {
    project_id:      "proj-supply-chain",
    name:            "Supply Chain Intelligence",
    description:     "Understand how AI, real-time data, and geopolitical shifts are reshaping global supply chain management, logistics, and trade finance.",
    keywords:        ["supply chain disruption", "logistics AI", "trade finance", "nearshoring", "demand forecasting", "inventory optimization"],
    difficulty:      "intermediate",
    focus_areas:     ["Demand Forecasting", "Disruption Risk", "AI Logistics Platforms"],
    color:           "amber",
    insight_count:   2,
    last_insight_at: "2026-05-13T07:00:00Z",
    created_at:      "2026-05-01T00:00:00Z",
    updated_at:      "2026-05-13T07:00:00Z",
  },
]

// ─────────────────────────────────────────────────────────────────────────────
// AI in Manufacturing — Day 2 (latest)
// ─────────────────────────────────────────────────────────────────────────────

const AIM_DAY2 = {
  id: "pkg-aim-2",
  project_id: "proj-ai-manufacturing",
  day_number: 2,
  generated_at: "2026-05-16T07:00:00Z",
  package_headline: "BMW Scales LLM-Digital Twin Fusion; Edge AI Clears IEC 61508",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 established time-series anomaly detection for predictive maintenance. Today's package connects real-time inference to digital twins and introduces the computer vision pipeline — the second major AI use case in manufacturing.",
  action_item: "Set up an OPC-UA simulator (open62541 library) and stream mock temperature/vibration data. Write a simple anomaly threshold rule, then sketch how you'd replace it with an LSTM autoencoder.",
  insights: [
    {
      id: "card-aim-2-1",
      content_type: "news",
      category: "Digital Twin",
      title: "BMW Deploys LLM-Augmented Digital Twins Across 40 European Plants",
      summary: "BMW has committed to full deployment of an LLM reasoning layer fused with process digital twins across all European assembly facilities by Q3 2026. Engineers query fault-causation chains in plain language; diagnostic accuracy matches senior process engineers in trials at 12 plants. Edge inference latency is under 80ms.",
      educational_explanation: "A digital twin is a real-time virtual model of a physical asset, continuously updated from sensor streams via protocols like OPC-UA. When you add an LLM reasoning layer, the model ingests the twin's structured state — temperatures, pressures, cycle times — alongside unstructured maintenance logs and surfaces root-cause explanations in natural language. The key engineering challenge is latency: the LLM must respond in milliseconds to be useful in a production environment, which requires quantized models running on-edge rather than cloud inference. BMW's architecture pairs a lightweight 7B parameter fine-tuned model with a graph-based fault ontology so the LLM's outputs are always grounded in domain-validated causal paths, not hallucinated sequences.",
      why_it_matters: "This is the reference architecture for industrial LLM deployment. Understanding how LLMs integrate with digital twins via OPC-UA and historian databases is now a core competency for anyone building AI systems for manufacturing.",
      source_links: [
        { title: "BMW Group Press — AI & Manufacturing Roadmap 2026", url: "https://www.bmwgroup.com/en/news/general/2026/ai-manufacturing.html" },
        { title: "Siemens Industrial AI White Paper", url: "https://www.siemens.com/global/en/products/automation/topic-areas/artificial-intelligence/industrial-ai.html" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-aim-2-2",
      content_type: "news",
      category: "Edge AI",
      title: "Arm + Siemens Joint Runtime Achieves IEC 61508 SIL-2 Certification for On-Device Inference",
      summary: "Arm and Siemens jointly released a validated inference runtime for Cortex-M55/M85 achieving 99.999% uptime SLA in IEC 61508 SIL-2 certified industrial environments. Power draw is under 200mW — enabling always-on defect detection directly on programmable logic controllers without cloud dependency.",
      educational_explanation: "IEC 61508 is the international standard for functional safety of electrical and electronic systems used in safety-critical applications. SIL (Safety Integrity Level) 2 corresponds to a probability of dangerous failure per hour between 10⁻⁷ and 10⁻⁶ — roughly equivalent to one dangerous failure per 100,000–1,000,000 operating hours. For AI models, achieving SIL-2 certification requires formal verification of the inference runtime, deterministic execution guarantees, watchdog monitoring, and redundancy mechanisms. This certification unlocks AI deployment in domains that were previously blocked — safety-rated machinery, pressure systems, and lifting equipment — which represent a huge portion of brownfield industrial AI opportunity.",
      why_it_matters: "On-device inference eliminates the cloud-dependency that blocked AI adoption in air-gapped plants. Knowing the SIL framework and how AI certifications are pursued is essential for anyone pitching industrial AI solutions to plant safety managers.",
      source_links: [
        { title: "IEC 61508 Overview — Functional Safety Portal", url: "https://www.functional-safety-expert.com/iec-61508" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "3 min",
    },
    {
      id: "card-aim-2-3",
      content_type: "news",
      category: "Quality Inspection",
      title: "AI Vision Inspection Hits 99.97% Defect Detection in 28nm Semiconductor Fabs",
      summary: "Computer vision models trained on domain-randomized synthetic data have reached near-human defect detection rates at 10× the throughput of manual inspection in 28nm and below process nodes. TSMC and Samsung have committed to full-line deployment by end of 2026, with Samsung reporting zero critical escapes in a 3-month pilot.",
      educational_explanation: "Domain randomization is a synthetic-data technique where CAD models of parts are rendered with randomized lighting, texture, camera angles, and surface imperfections to create training datasets without needing real defect examples. This solves the cold-start problem: in high-yield fabs, defective parts are rare by design, making it nearly impossible to accumulate the thousands of labeled defect images that traditional supervised learning requires. Randomization teaches the model to focus on shape anomalies rather than texture artifacts from specific camera conditions. Combined with contrastive learning and anomaly scoring, these models set a lower bound threshold of 'what normal looks like' and flag deviations — making them robust to new defect types not seen during training.",
      why_it_matters: "Synthetic data + domain randomization is the canonical approach for any low-defect-rate manufacturing inspection problem. Understanding this pipeline — CAD → randomized render → anomaly model → edge deployment — directly applies to quality inspection in any industry sector.",
      source_links: [
        { title: "TSMC 2026 Technology Symposium — AI Quality", url: "https://www.tsmc.com/english/dedicatedFoundry/technology/logic/l_2nm.htm" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "3 min",
    },
    {
      id: "card-aim-2-4",
      content_type: "educational",
      category: "Predictive Maintenance",
      title: "Concept: Remaining Useful Life (RUL) — Predicting When Equipment Will Fail",
      summary: "Remaining Useful Life (RUL) estimation is the task of predicting how many operating cycles or hours a piece of equipment has left before it needs maintenance or replacement. It is the core output of a predictive maintenance system.",
      educational_explanation: "RUL models take time-series sensor readings — vibration amplitude, bearing temperature, acoustic emission — as input and output a scalar estimate of remaining operating time. The most common approach uses a sliding window of recent sensor readings fed into an LSTM or Temporal Convolutional Network (TCN) that regresses to a normalized RUL value (1.0 = new, 0.0 = failure). Training requires run-to-failure datasets — historical sensor recordings that continue until the equipment actually failed — which is why the NASA CMAPSS (C-MAPSS Turbofan) and PHM Challenge datasets are so widely used. In production, the model scores new sensor streams in real time; when RUL drops below a threshold (e.g., 0.2), a maintenance work order is automatically created in the CMMS. The engineering challenge is false-positive management: triggering unnecessary maintenance is costly, so calibration of the confidence interval around the RUL estimate is as important as the point estimate.",
      why_it_matters: "RUL prediction is the core KPI that justifies predictive maintenance investment — a precise RUL model quantifies ROI in dollar terms (avoided emergency repair costs, reduced unplanned downtime). Building one from scratch on the NASA CMAPSS dataset is the standard portfolio project for anyone entering industrial AI.",
      source_links: [
        { title: "NASA CMAPSS Turbofan Dataset — Prognostics Center", url: "https://www.nasa.gov/content/prognostics-center-of-excellence-data-set-repository" },
        { title: "Temporal Convolutional Networks for RUL Estimation — arXiv", url: "https://arxiv.org/abs/1803.01271" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
    {
      id: "card-aim-2-5",
      content_type: "educational",
      category: "Process Optimization",
      title: "Concept: OPC-UA — The Universal Language of Industrial Data",
      summary: "OPC Unified Architecture (OPC-UA) is the standard communication protocol for industrial automation systems. It is how sensors, PLCs, SCADA systems, and AI models exchange data in a manufacturing plant.",
      educational_explanation: "OPC-UA (IEC 62541) is a platform-independent, service-oriented architecture that provides secure, reliable communication between industrial devices and software. Unlike its predecessor OPC Classic (DCOM-based, Windows-only), OPC-UA works across any OS and hardware, supports encryption and authentication natively, and defines a semantic information model — meaning devices expose not just raw values but typed data with defined relationships. From an AI engineering perspective, OPC-UA is the data collection layer: a Python client (using the opcua or asyncua library) subscribes to node changes and writes arriving values into a time-series database like InfluxDB or OSIsoft PI. The historian database is what AI models are trained on. Understanding OPC-UA address spaces, node IDs, and subscription patterns is the prerequisite for building any industrial AI data pipeline — you cannot build a predictive maintenance model without first being able to reliably collect the sensor data.",
      why_it_matters: "Every industrial AI project starts with a data collection problem. OPC-UA is the protocol you will encounter at almost every manufacturing site. Understanding how to connect a Python OPC-UA client to a PLC simulator is the first practical step in this project's learning path.",
      source_links: [
        { title: "OPC Foundation — OPC-UA Specification Overview", url: "https://opcfoundation.org/about/opc-technologies/opc-ua/" },
        { title: "asyncua Python Library Documentation", url: "https://github.com/FreeOpcUa/opcua-asyncio" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// AI in Manufacturing — Day 1
// ─────────────────────────────────────────────────────────────────────────────

const AIM_DAY1 = {
  id: "pkg-aim-1",
  project_id: "proj-ai-manufacturing",
  day_number: 1,
  generated_at: "2026-05-10T07:00:00Z",
  package_headline: "Industrial LLMs Cut Downtime 34%; EU AI Act Classifies Safety AI as High-Risk",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 establishes the two foundational pillars of industrial AI: predictive maintenance (time-series domain) and the regulatory environment that governs deployment.",
  action_item: "Download the NASA CMAPSS Turbofan dataset and implement a baseline LSTM autoencoder. Plot the reconstruction error for normal vs. near-failure windows and observe the anomaly signal.",
  insights: [
    {
      id: "card-aim-1-1",
      content_type: "news",
      category: "Predictive Maintenance",
      title: "Domain-Specific LLMs on Maintenance Logs Beat GPT-4 Class Models by 38%",
      summary: "A Stanford-Siemens study benchmarked domain-specific fine-tuned 7B parameter models against GPT-4o on maintenance log analysis tasks. Fine-tuned models outperformed on fault prediction F1 by 38% at 1/10th the inference cost. Siemens and ABB report 34% reduction in unplanned downtime after deploying these models at 200+ sites.",
      educational_explanation: "Fine-tuning adapts a pre-trained language model to a specific domain by continuing training on domain-specific data — in this case, 10+ years of equipment maintenance logs. The key insight is that general-purpose models lack the semantic context to correctly interpret domain-specific failure modes: a 'bearing knock' in a maintenance log has a precise causal meaning that GPT-4o cannot reliably decode without industrial context. Fine-tuned models also benefit from exposure to the specific abbreviation and shorthand conventions of maintenance technicians (e.g., 'VFD trip on OC' = Variable Frequency Drive tripped on overcurrent). At 50ms inference latency on edge hardware, these models can process sensor + log data in the control loop — enabling autonomous maintenance scheduling rather than human-reviewed alerts.",
      why_it_matters: "This definitively answers the 'build vs. buy' question for industrial AI: fine-tuned small models outperform large general models for domain-specific manufacturing tasks. This has direct implications for how you architect any industrial AI system.",
      source_links: [
        { title: "Siemens Industrial AI — Predictive Maintenance Results 2025", url: "https://press.siemens.com/global/en/pressrelease/siemens-industrial-ai" },
        { title: "Stanford HAI — Domain Adaptation in Manufacturing LLMs", url: "https://hai.stanford.edu/research/domain-llms-manufacturing" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-aim-1-2",
      content_type: "news",
      category: "Regulatory",
      title: "EU AI Act Classifies Predictive Maintenance on Safety-Critical Equipment as High-Risk",
      summary: "The European Commission's guidance clarifies that AI used for predictive maintenance on Category 3 and 4 safety-critical equipment (pressure vessels, electrical systems, lifting equipment) falls under high-risk classification, requiring conformity assessment, audit logs, and human oversight mechanisms before Q3 2026 enforcement.",
      educational_explanation: "The EU AI Act creates four risk tiers for AI systems. High-risk AI (Annex III) requires: a conformity assessment demonstrating accuracy and robustness, a technical documentation file with model cards, post-market monitoring with incident logging, and a human-in-the-loop oversight mechanism for any automated decision that could cause physical harm. For a predictive maintenance system that can trigger equipment shutdowns, this means: (1) logging every prediction with confidence scores, (2) maintaining a model registry with versioned artifacts, (3) requiring human authorization before any automated shutdown command in the first 6 months of deployment, and (4) quarterly performance audits with hold-out test sets. The compliance cost is non-trivial: most estimates put it at €50,000–€200,000 per system for documentation and assessment, plus ongoing monitoring overhead.",
      why_it_matters: "Any industrial AI system you build for EU deployment must be designed with compliance in mind from day one. Retrofitting governance infrastructure after model development is 3–5× more expensive. Knowing what the EU AI Act requires shapes your data logging strategy, model card format, and human oversight architecture.",
      source_links: [
        { title: "European Commission — EU AI Act Guidance Document", url: "https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-aim-1-3",
      content_type: "news",
      category: "CMMS Integration",
      title: "CMMS Data Fragmentation Is the #1 Barrier to Industrial AI Deployment — Gartner 2026",
      summary: "Gartner's 2026 Industrial AI adoption survey identifies legacy Computerized Maintenance Management System (CMMS) data quality as the single largest barrier to predictive maintenance deployment — cited by 67% of industrial companies. Most CMMS systems contain 10–30% duplicate records, inconsistent equipment hierarchies, and unstructured free-text failure descriptions that require extensive NLP preprocessing.",
      educational_explanation: "A CMMS (Computerized Maintenance Management System) is the system of record for all maintenance activities at a plant — work orders, parts inventories, equipment hierarchies, and historical failure records. It is the primary source of labeled training data for supervised predictive maintenance models: the failure timestamp in the CMMS becomes the ground-truth label that tells you when the preceding sensor readings represented a degraded state. The data quality problem is severe: technicians use inconsistent terminology, work orders are often written after the fact, and equipment IDs rarely match between the CMMS and the sensor historian. Building a robust CMMS data pipeline — entity matching between systems, failure mode taxonomy extraction via NLP, and label propagation from work order timestamps to sensor windows — is typically 60–70% of the engineering effort in a real predictive maintenance project.",
      why_it_matters: "Before you can train any predictive maintenance model, you must understand where the labeled data comes from and how to extract it. CMMS integration is not a secondary concern — it is the foundational data engineering challenge of every industrial AI project.",
      source_links: [
        { title: "Gartner — Industrial AI Adoption Survey 2026", url: "https://www.gartner.com/en/documents/industrial-ai-adoption-2026" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-aim-1-4",
      content_type: "educational",
      category: "Predictive Maintenance",
      title: "Concept: Time-Series Anomaly Detection — The Foundation of Predictive Maintenance",
      summary: "Anomaly detection on multivariate sensor streams is the core technical problem underlying predictive maintenance. Understanding the available approaches — statistical, distance-based, and deep learning — and when to apply each is the foundational skill for this project.",
      educational_explanation: "Anomaly detection identifies data points that deviate significantly from the expected pattern. In manufacturing, sensor streams (vibration, temperature, current draw) exhibit complex multivariate patterns during normal operation; deviations from this pattern signal degradation. Three main approaches: (1) Statistical methods — CUSUM (Cumulative Sum) and EWMA (Exponentially Weighted Moving Average) are computationally cheap and interpretable but miss nonlinear interactions between sensors. (2) Isolation Forest randomly partitions the feature space; anomalies are isolated in fewer splits than normal points — works well on tabular snapshots but loses temporal structure. (3) LSTM Autoencoders learn to reconstruct normal operation windows; the reconstruction error is the anomaly score — high error = the pattern doesn't match what the model learned as 'normal'. The autoencoder approach is most powerful for multivariate temporal data but requires a substantial run-to-failure dataset for calibration. A practical deployment uses a staged approach: CUSUM for immediate alerting (low latency), LSTM autoencoder for trend analysis (medium latency), and a random forest on engineered features for interpretable root-cause attribution.",
      why_it_matters: "Anomaly detection is the first model you build in any predictive maintenance system. Understanding the tradeoffs between these approaches — latency, interpretability, data requirements — enables you to select the right tool for each part of the monitoring stack.",
      source_links: [
        { title: "Time Series Anomaly Detection Survey — arXiv 2021", url: "https://arxiv.org/abs/2105.15127" },
        { title: "PyOD — Python Outlier Detection Library", url: "https://pyod.readthedocs.io/en/latest/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "6 min",
    },
    {
      id: "card-aim-1-5",
      content_type: "educational",
      category: "Process Optimization",
      title: "Concept: The ISA-95 Standard — How Manufacturing Data Is Hierarchically Organised",
      summary: "ISA-95 (ANSI/ISA-95) defines the information models and interface specifications between enterprise systems (ERP) and plant-floor control systems. It is the conceptual framework behind every industrial data architecture.",
      educational_explanation: "ISA-95 defines a five-level hierarchy: Level 0 (physical process sensors), Level 1 (PLCs/sensors — direct control), Level 2 (SCADA/DCS — supervisory control), Level 3 (MES — Manufacturing Execution System, production scheduling), Level 4 (ERP — business planning). AI models in manufacturing almost always sit at Level 3, consuming data from Levels 0–2 via the historian and outputting decisions back to Levels 3–4. Understanding this hierarchy tells you: where your data originates (Level 0–1 sensor streams), what systems you need to integrate with (Level 2 SCADA for real-time data, Level 3 MES for production context, Level 4 SAP/Oracle for maintenance cost data), and where your AI outputs need to land (work orders in the CMMS, alerts in the SCADA HMI, KPIs in the ERP). Almost every industrial AI project stalls because the data engineer didn't understand ISA-95 and tried to connect to the wrong system at the wrong level.",
      why_it_matters: "ISA-95 is the map of the industrial data landscape. Before writing a single line of code for any manufacturing AI project, you need to understand which level of this hierarchy holds the data you need and how to extract it. This prevents wasted weeks connecting to the wrong system.",
      source_links: [
        { title: "ISA-95 Standard Overview — ISA.org", url: "https://www.isa.org/standards-and-publications/isa-standards/isa-standards-committees/isa95" },
        { title: "Understanding ISA-95 for Industrial AI — LinkedIn Engineering", url: "https://engineering.linkedin.com/blog/industrial-isa95" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Indian Pharma Exports — Day 2 (latest)
// ─────────────────────────────────────────────────────────────────────────────

const IP_DAY2 = {
  id: "pkg-ip-2",
  project_id: "proj-indian-pharma",
  day_number: 2,
  generated_at: "2026-05-15T07:00:00Z",
  package_headline: "EU GMP Mutual Recognition Advances; Biosimilar Exports Hit $1.2B",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 established USFDA approval pathways and the quality turnaround story. Today shifts to the EU market and biosimilar opportunity — completing the picture of where Indian pharma growth is coming from.",
  action_item: "Look up EMA's list of centrally approved generic medicines and identify 3 where Indian manufacturers hold the marketing authorisation. Note which approval pathway (centralised vs. decentralised) each used.",
  insights: [
    {
      id: "card-ip-2-1",
      content_type: "news",
      category: "EU Market Access",
      title: "Draft India-EU GMP MRA Covers 34 Major API Sites — Ratification Expected 2027",
      summary: "India-EU trade negotiations have produced a draft GMP Mutual Recognition Agreement covering 34 active pharmaceutical ingredient manufacturers. If ratified, CDSCO inspection reports would be accepted by EMA for covered facilities, eliminating duplicate inspections and cutting market entry timelines by 12–18 months.",
      educational_explanation: "A GMP Mutual Recognition Agreement (MRA) allows one regulatory authority to accept the manufacturing site inspection findings of another, eliminating the need for duplicate inspections. Currently, Indian manufacturers exporting APIs to the EU must pass both CDSCO (India) and EMA (EU) inspections — a process that can take 18–24 months and cost €500,000+ per site. Under an MRA, a clean CDSCO inspection report is accepted as equivalent to an EMA inspection, unlocking faster market entry. MRAs are negotiated bilaterally and require both regulators to demonstrate equivalent inspection standards — the EU has existing MRAs with Switzerland, Australia, Canada, Japan, and the US (FDA). For India to qualify, CDSCO had to demonstrate that its inspection methodology, inspector training, and follow-up processes meet EU standards — a significant institutional development that signals the maturation of Indian pharmaceutical regulation.",
      why_it_matters: "MRA status is a structural market access advantage. Indian API manufacturers covered by the agreement can launch EU products 12–18 months faster than non-covered competitors. Understanding MRA qualification criteria helps you assess which Indian manufacturers are best positioned for EU growth.",
      source_links: [
        { title: "EMA — Mutual Recognition Agreements Overview", url: "https://www.ema.europa.eu/en/human-regulatory/research-development/compliance/good-manufacturing-practice/mutual-recognition-agreements" },
        { title: "India EU Trade Negotiations — Ministry of Commerce", url: "https://commerce.gov.in/trade-agreements/bilateral-agreements/india-eu-fta/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-ip-2-2",
      content_type: "news",
      category: "Biosimilars",
      title: "Indian Biosimilar Exports to EU Reach $1.2B — 3× Growth in 3 Years",
      summary: "Indian biosimilar manufacturers (Biocon, Dr. Reddy's, Lupin) collectively crossed $1.2B in EU biosimilar revenues in FY2026, up from $400M in FY2023. Trastuzumab, bevacizumab, and adalimumab biosimilars dominate, with insulin glargine launches planned for 2027.",
      educational_explanation: "Biosimilars are biological medicines that are highly similar to an already-approved reference biologic (the originator) but not identical — because biological molecules are large and complex, exact replication is impossible, and manufacturers must instead demonstrate 'high similarity' through comparative analytical, non-clinical, and clinical studies. The regulatory pathway is more demanding than for chemical generics (which only need bioequivalence studies): biosimilar applicants must provide extensive analytical comparability data, and typically one pivotal clinical study is still required. The competitive advantage for Indian biosimilar manufacturers is cost structure: Indian biologics manufacturers (particularly Biocon's Bengaluru facility) operate at 40–60% lower cost than European originators, enabling aggressive pricing on the reference product while maintaining profitable margins. The EU biosimilar market is particularly attractive because NHS and national health systems actively drive substitution through tendering processes that reward price.",
      why_it_matters: "Biosimilars are the highest-value, fastest-growing segment of Indian pharma exports. Understanding the regulatory pathway difference between biosimilars and chemical generics helps you assess which Indian companies have the manufacturing and regulatory capabilities to compete in this market.",
      source_links: [
        { title: "Biocon Biologics — FY2026 Annual Report", url: "https://www.biocon.com/investors/annual-reports/" },
        { title: "EMA — Biosimilar Medicines Guidelines", url: "https://www.ema.europa.eu/en/human-regulatory/marketing-authorisation/biosimilar-medicines" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-ip-2-3",
      content_type: "news",
      category: "API Supply Chain",
      title: "Bulk Drug Park PLI Phase II Attracts ₹24,000 Crore as China+1 Sourcing Accelerates",
      summary: "India's three Bulk Drug Parks (Hyderabad, Visakhapatnam, J&K) have attracted ₹24,000 crore in committed investment driven by US Biosecure Act provisions restricting Chinese CDMO sourcing. Five major US branded pharma companies have disclosed active China-to-India API sourcing transitions expected to add $800M in annual procurement by 2028.",
      educational_explanation: "The US BIOSECURE Act restricts US government agencies — and companies receiving US federal funding — from contracting with specific Chinese biotechnology companies (BGISEQ, MGI, BGI Genomics, WuXi AppTec, WuXi Biologics) for genomics or biotech services. While the direct restriction targets genomics, the bill has created broader anxiety among US pharma companies about supply chain exposure to Chinese entities generally, accelerating China+1 diversification strategies. India's Production-Linked Incentive (PLI) scheme for bulk drugs provides 10–20% financial incentives on incremental sales for 6 years, making Indian API manufacturing economically attractive for companies replacing Chinese sources. The Bulk Drug Parks provide additional subsidies: free land, common utilities, and shared effluent treatment infrastructure. Together these incentives create a cost structure that is competitive with Zhejiang-based Chinese API clusters for the first time in a decade.",
      why_it_matters: "The China+1 API sourcing shift is a multi-year structural tailwind for Indian pharma exports. Understanding which API categories benefit (fermentation-based, oncology, contrast media) versus those still challenged (commodity generics with overcapacity) helps you distinguish durable from cyclical winners.",
      source_links: [
        { title: "PLI Scheme for Bulk Drugs — Ministry of Chemicals", url: "https://pharmaceuticals.gov.in/sites/default/files/PLI%20scheme%20for%20Bulk%20Drugs.pdf" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-ip-2-4",
      content_type: "educational",
      category: "EU Market Access",
      title: "Concept: EMA Approval Pathways — Centralised, Decentralised, and Mutual Recognition",
      summary: "The European Medicines Agency operates multiple approval pathways for pharmaceuticals. Understanding which pathway applies to which product type determines the timeline, cost, and strategic approach for Indian exporters entering the EU market.",
      educational_explanation: "EMA offers three main pathways: (1) Centralised Procedure (CP) — mandatory for biologics, oncology drugs, orphan medicines, and medicines for HIV, diabetes, and neurodegenerative diseases. A single application submitted to EMA yields a marketing authorisation valid in all 27 EU member states plus Iceland, Liechtenstein, and Norway. Timeline: 210 active review days (typically 12–15 months elapsed). (2) Decentralised Procedure (DCP) — a reference member state (RMS) leads the review; the applicant simultaneously applies in multiple 'concerned member states'. Used for generics, biosimilars where CP is not mandatory, and non-prescription medicines. (3) Mutual Recognition Procedure (MRP) — the applicant already has a national authorisation in one member state and requests recognition in others. For Indian generic manufacturers, the typical route is DCP with Germany, France, or Netherlands as RMS (these countries have the largest and most experienced generic review divisions). Annex 1 to Directive 2001/83/EC governs the data requirements; Module 3 of the Common Technical Document must demonstrate pharmaceutical equivalence and bioequivalence.",
      why_it_matters: "Knowing which EMA pathway applies to a given product — and which reference member state to choose — directly affects the market entry timeline and cost. This is the strategic regulatory knowledge that separates a well-positioned Indian exporter from one that spends 2 extra years on regulatory rework.",
      source_links: [
        { title: "EMA — Centralised Procedure Overview", url: "https://www.ema.europa.eu/en/human-regulatory/marketing-authorisation/centralised-procedure" },
        { title: "EMA — Decentralised Procedure for Generics", url: "https://www.ema.europa.eu/en/human-regulatory/marketing-authorisation/decentralised-procedure" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
    {
      id: "card-ip-2-5",
      content_type: "educational",
      category: "USFDA Compliance",
      title: "Concept: Data Integrity in Pharma — 21 CFR Part 11 and the ALCOA+ Framework",
      summary: "Data integrity is the #1 cause of FDA warning letters to Indian manufacturers. Understanding the regulatory framework — 21 CFR Part 11 and the ALCOA+ principles — is foundational for any practitioner working in or analysing pharma manufacturing.",
      educational_explanation: "21 CFR Part 11 is the FDA regulation governing electronic records and electronic signatures in pharmaceutical manufacturing. It requires that electronic systems used to create, modify, or transmit regulated records produce audit trails, prevent backdating, support access controls, and generate records in non-editable formats. ALCOA+ is the mnemonic framework FDA and WHO use to define data integrity requirements: Attributable (who recorded it, who modified it), Legible (readable, indelible), Contemporaneous (recorded at the time it happened), Original (the primary record), Accurate (error-free) — plus Consistent, Enduring, and Available (the '+' additions). Most FDA warning letters to Indian manufacturers cite failures of the 'A' (attributable — audit trails deleted or not configured) and 'C' (contemporaneous — test results recorded after review of prior failed results, then repassing). Electronic Batch Record (eBR) systems and Laboratory Information Management Systems (LIMS) with 21 CFR Part 11-compliant configurations are the standard remediation approach.",
      why_it_matters: "Data integrity compliance is now table stakes, not a differentiator. Every analysis of Indian pharma export competitiveness must account for which manufacturers have completed their eBR/LIMS transformation and which are still operating under paper or non-compliant electronic systems.",
      source_links: [
        { title: "FDA — 21 CFR Part 11 Electronic Records Guidance", url: "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/part-11-electronic-records-electronic-signatures-scope-and-application" },
        { title: "WHO — Data Integrity and Good Manufacturing Practice", url: "https://www.who.int/publications/m/item/WHO-TRS-1010-annex-04" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Indian Pharma Exports — Day 1
// ─────────────────────────────────────────────────────────────────────────────

const IP_DAY1 = {
  id: "pkg-ip-1",
  project_id: "proj-indian-pharma",
  day_number: 1,
  generated_at: "2026-05-08T07:00:00Z",
  package_headline: "USFDA Warning Letters Fall 40%; GDUFA III Speeds ANDA Reviews",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 establishes the USFDA regulatory foundation — approval pathways, inspection outcomes, and the quality turnaround — that underpins all subsequent analysis of Indian pharma export competitiveness.",
  action_item: "Search the FDA Orange Book for atorvastatin 20mg and count the number of approved ANDA holders. Identify which are Indian manufacturers and note when each received approval.",
  insights: [
    {
      id: "card-ip-1-1",
      content_type: "news",
      category: "USFDA Compliance",
      title: "FDA Warning Letters to Indian Plants Fall 40% — Data Integrity Investments Paying Off",
      summary: "FDA import alerts and warning letters to Indian pharmaceutical manufacturers fell 40% in 2025 vs. 2023. Sun Pharma, Cipla, and Lupin all remediated major sites that had been on import alert. The improvement reflects sustained investment in electronic batch record systems and LIMS with 21 CFR Part 11-compliant configurations.",
      educational_explanation: "A Warning Letter is the most serious regulatory action short of a consent decree or injunction. It signals that FDA believes violations are of regulatory significance and that the company has not corrected them following a Form 483 (inspection observations). For Indian plants, being on import alert (automatically detained at the border without physical examination) effectively excludes the facility from the US market — products manufactured there cannot be sold in the US until the alert is lifted. The alert lifting process requires: (1) a comprehensive CAPA (Corrective and Preventive Action) plan submitted to FDA, (2) a successful re-inspection with no repeat observations, and (3) in some cases, a third-party audit. The typical time from warning letter to cleared import alert is 18–36 months, which is why data integrity failures have such severe commercial consequences for Indian manufacturers.",
      why_it_matters: "A company's FDA compliance history is a leading indicator of its US market access trajectory. Tracking which facilities are under import alert, which have recently cleared, and which are at risk is essential intelligence for any analysis of Indian pharma competitive positioning.",
      source_links: [
        { title: "FDA — Warning Letters Database", url: "https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters" },
        { title: "FDA — Import Alert 66-40 (Indian API Manufacturers)", url: "https://www.accessdata.fda.gov/cms_ia/importalert_190.html" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-ip-1-2",
      content_type: "news",
      category: "Generic Drug Markets",
      title: "GDUFA III Commitments Achieve 90% ANDA Review in 10 Months — Indian Pipelines Accelerate",
      summary: "Generic Drug User Fee Agreement III commitments took effect in FY2026, targeting 90% of standard ANDA reviews completed within 10 months. As of Q1 2026, FDA is meeting the target. Indian companies with large pending ANDA portfolios are positioned to significantly accelerate US revenue recognition.",
      educational_explanation: "GDUFA (Generic Drug User Fee Act) is the legislative framework under which generic drug manufacturers pay user fees to FDA in exchange for performance commitments on review timelines. Under GDUFA I (2012–2017), FDA faced a backlog of 4,000+ pending ANDAs with no timeline commitments. GDUFA II (2017–2022) set the first review goals; GDUFA III (2022–2027) tightened them to 90% of complete standard applications reviewed in 10 months. For Indian manufacturers, faster ANDA approvals directly accelerate revenue recognition: a company with 150 pending ANDAs that gets approvals in 10 months instead of 24 months realizes an 18-month pull-forward of market entry and the associated first-to-market pricing premium. The Indian companies with the largest pending ANDA pipelines (Sun Pharma ~200, Cipla ~180, Dr. Reddy's ~160) stand to benefit the most from sustained GDUFA III performance.",
      why_it_matters: "ANDA pipeline depth is a leading indicator of future US revenue for Indian generics companies. GDUFA III performance determines how quickly that pipeline converts to revenue. This is a direct input to financial analysis of Indian pharma sector growth.",
      source_links: [
        { title: "FDA — GDUFA III Performance Goals and Procedures", url: "https://www.fda.gov/industry/prescription-drug-user-fee-amendments/gdufa-iii" },
        { title: "FDA — Generic Drug Program Progress Report 2026", url: "https://www.fda.gov/drugs/generic-drugs/generic-drug-program-annual-reports" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "3 min",
    },
    {
      id: "card-ip-1-3",
      content_type: "news",
      category: "Generic Drug Markets",
      title: "US Generic Price Erosion Moderates to 3–5% as Market Consolidation Reduces Buyer Leverage",
      summary: "After 5 years of 8–15% annual price erosion in US generic drugs, market consolidation has moderated erosion to 3–5% annually. Rite Aid and Supervalu bankruptcy exits reduced buying leverage. Companies with established market share in late-cycle generics are seeing improved pricing stability.",
      educational_explanation: "Generic drug price erosion is driven by the dynamics of market entry over the product lifecycle. When a generic first launches (Day 1 of patent expiry), typically 1–3 players enter and prices drop to 60–80% of the branded price. As additional manufacturers enter over the following 24 months, prices compress further. By the time a generic has 5+ approved manufacturers, average selling prices are often 15–25% of the original branded price. The rate of erosion depends on: number of approved ANDAs (more = faster erosion), number of actually marketed products (not all approved manufacturers launch), and the concentration of purchasing power on the buyer side (wholesaler and PBM consolidation increases their negotiating leverage). The Rite Aid bankruptcy (2023) and subsequent restructuring removed a major purchasing entity from the market, shifting leverage marginally back to manufacturers — a small but real structural improvement in the pricing environment.",
      why_it_matters: "Generic price erosion dynamics directly affect the revenue sustainability of Indian pharma export models. Understanding why erosion happens — and what structural factors moderate it — is essential for projecting revenue trajectories for specific product portfolios.",
      source_links: [
        { title: "IQVIA — US Generics Market Report 2025", url: "https://www.iqvia.com/insights/the-iqvia-institute/reports/the-use-of-medicines-in-the-us-2025" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "3 min",
    },
    {
      id: "card-ip-1-4",
      content_type: "educational",
      category: "USFDA Compliance",
      title: "Concept: ANDA Approval Process — How Indian Generics Enter the US Market",
      summary: "An Abbreviated New Drug Application (ANDA) is the regulatory pathway for generic drug approval in the US. Understanding how it works — and what makes it 'abbreviated' — is the foundational knowledge for analysing Indian pharma export competitiveness.",
      educational_explanation: "An ANDA is 'abbreviated' because generic applicants do not need to repeat the safety and efficacy clinical trials conducted by the original drug manufacturer — instead, they demonstrate that their product is pharmaceutically equivalent (same active ingredient, strength, dosage form, route of administration) and bioequivalent (same rate and extent of absorption) to the reference listed drug (RLD). The ANDA consists of four main modules: Module 1 (administrative), Module 2 (summaries), Module 3 (pharmaceutical/chemistry data, manufacturing information, specifications), and Module 5 (bioequivalence study data). The key strategic battlegrounds for Indian manufacturers are Para IV certifications (challenging a brand's patent as invalid or not infringed — the first approved Para IV challenger gets 180 days of marketing exclusivity, often the most profitable window of the product lifecycle) and ANDAs for complex generics (peptides, inhalation products, topical formulations) where the technical barriers reduce competitive intensity.",
      why_it_matters: "The ANDA process is the mechanism through which Indian manufacturers access the $130B US generics market. Understanding Para IV challenges, exclusivity periods, and first-to-file strategies directly informs analysis of which Indian pharma companies have the most valuable near-term growth catalysts.",
      source_links: [
        { title: "FDA — Abbreviated New Drug Application Process", url: "https://www.fda.gov/drugs/types-applications/abbreviated-new-drug-application-anda" },
        { title: "FDA Orange Book — Approved Drug Products", url: "https://www.accessdata.fda.gov/scripts/cder/ob/index.cfm" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
    {
      id: "card-ip-1-5",
      content_type: "educational",
      category: "API Supply Chain",
      title: "Concept: Drug Master File (DMF) — The API Export Infrastructure",
      summary: "A Drug Master File (DMF) is a confidential submission to FDA containing detailed information about the manufacturing process, facilities, and quality controls for an API or drug product component. It is the regulatory infrastructure that enables Indian API manufacturers to supply US drug producers.",
      educational_explanation: "A Type II DMF covers starting materials, intermediates, and APIs. Indian API manufacturers file DMFs to allow US finished-dose manufacturers to reference their manufacturing data in ANDAs and NDAs without publicly disclosing proprietary process information. The Indian company (DMF holder) authorizes specific US companies to 'reference' the DMF in their drug applications — this is the commercial relationship that underpins the API supply contract. As of 2026, Indian manufacturers hold approximately 2,800 active Type II DMFs with FDA — the largest base of any country outside the US. The DMF update cycle is a compliance burden: if the manufacturing process changes, the DMF must be amended and FDA notified; and if the API supplier fails an FDA inspection, any application referencing that DMF is affected. Understanding DMF status for a given API is essential intelligence for supply chain risk analysis.",
      why_it_matters: "DMF holdings are a direct measure of an Indian API manufacturer's US market access infrastructure. Companies with large, clean DMF portfolios are structurally advantaged to capture the China+1 sourcing shift. Tracking active DMF counts by company is a quantifiable proxy for market position.",
      source_links: [
        { title: "FDA — Drug Master File Guidance", url: "https://www.fda.gov/drugs/forms-submission-requirements/drug-master-files-dmfs" },
        { title: "FDA — DMF Database (searchable)", url: "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=DMFSearch.process" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Quantitative Finance — Day 2 (latest)
// ─────────────────────────────────────────────────────────────────────────────

const QF_DAY2 = {
  id: "pkg-qf-2",
  project_id: "proj-quant-finance",
  day_number: 2,
  generated_at: "2026-05-14T07:00:00Z",
  package_headline: "SEC Mandates XBRL Climate Data; LLM Alpha Signals Validate at AQR",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 built the factor model foundation. Day 2 introduces the options pricing framework and alternative data signals — the two extensions of the linear factor model that define advanced systematic investing.",
  action_item: "Price a European call using BSM for S=100, K=105, r=0.05, σ=0.20, T=0.5. Then compute delta analytically and verify it numerically via finite difference (shift S by ±0.01). The agreement should be within 0.0001.",
  insights: [
    {
      id: "card-qf-2-1",
      content_type: "news",
      category: "Alternative Data",
      title: "SEC Mandates Machine-Readable XBRL Climate Risk Disclosures — Structured Dataset for 6,000 Companies",
      summary: "The SEC's climate disclosure rules now require XBRL-tagged climate risk metrics in annual filings, creating a structured dataset of physical and transition risk exposure across all ~6,000 US public companies. The first full cohort of tagged filings will be available Q3 2026, enabling systematic factor construction for climate-aware quant strategies.",
      educational_explanation: "XBRL (eXtensible Business Reporting Language) is a structured data format that tags financial and now climate information with machine-readable identifiers, allowing automated ingestion and comparison across companies. The SEC EDGAR system already uses XBRL for financial statements; extending it to climate disclosures means structured data on Scope 1/2/3 emissions, physical risk assessments (flood, heat, water stress), and transition risk exposures (stranded assets, carbon pricing sensitivity) will be available through the same API infrastructure quants already use. For systematic strategies, this unlocks two factor construction approaches: (1) cross-sectional sorts on carbon intensity or climate transition risk exposure as risk factors in a multi-factor model, (2) long-short strategies that exploit systematic mispricing of physical climate risk — research shows markets consistently underprice tail physical risk exposure in asset prices, which creates factor premia. The 6,000-company coverage matches the Russell 3000 universe, making the dataset usable for broad equity strategies.",
      why_it_matters: "Structured climate risk data closes the gap between ESG investing aspiration and quantitative implementation. Building an ingestion pipeline for XBRL climate data and constructing the first cross-sectional sorts is a differentiated portfolio project that signals awareness of regulatory-driven data infrastructure development.",
      source_links: [
        { title: "SEC — Climate Disclosure Final Rule", url: "https://www.sec.gov/rules/final/2024/33-11275.pdf" },
        { title: "SEC EDGAR XBRL API Documentation", url: "https://data.sec.gov/api/xbrl/companyfacts/" },
      ],
      difficulty: "advanced",
      estimated_read_time: "4 min",
    },
    {
      id: "card-qf-2-2",
      content_type: "news",
      category: "ML Trading Strategies",
      title: "Stanford-AQR Study Validates Transcript NLP Signals as Orthogonal Alpha Source",
      summary: "A Stanford-AQR paper demonstrates that uncertainty and sentiment signals extracted from earnings call Q&A sections generate statistically significant alpha over a 12-month horizon and are orthogonal to traditional earnings surprise and momentum factors. Two top-10 systematic hedge funds have integrated LLMs into signal generation pipelines with 0.3–0.5 Sharpe improvement on equity long-short strategies.",
      educational_explanation: "Factor orthogonality is the statistical property that one factor's returns are uncorrelated with another's, meaning each factor provides genuinely independent information. A new signal with positive expected return AND low correlation to existing factors improves a multi-factor portfolio by increasing the information ratio without proportional increase in variance — mathematically equivalent to adding diversifying assets to a portfolio. NLP-derived signals from earnings call transcripts achieve orthogonality with traditional factors because they capture behavioral and informational signals (CEO tone uncertainty, hedging language density, question evasion patterns) that are not captured by price momentum, earnings revisions, or valuation multiples. The key technical challenge is text processing at scale: 6,000 companies × 4 quarters × multiple years of transcripts requires a chunking and embedding strategy that preserves temporal structure while fitting within LLM context windows. AQR's published methodology uses a domain-fine-tuned BERT model rather than a general LLM to reduce inference cost on the large historical corpus.",
      why_it_matters: "Alternative data signal construction from SEC filings and earnings transcripts is now an institutionally validated alpha source. Building the end-to-end pipeline — EDGAR ingestion → transcript parsing → NLP signal → factor model integration → backtest — is the most differentiated project a quant researcher can demonstrate.",
      source_links: [
        { title: "AQR — Alternative Data in Systematic Equity Strategies", url: "https://www.aqr.com/Insights/Research/Working-Paper/Alternative-Data-Systematic-Equity" },
      ],
      difficulty: "advanced",
      estimated_read_time: "4 min",
    },
    {
      id: "card-qf-2-3",
      content_type: "news",
      category: "Options Pricing",
      title: "Rough Volatility Models Replace SABR at Two Top-5 Options Market Makers",
      summary: "Two top-5 options market makers have moved rough volatility (rough Bergomi) models into production pricing, replacing SABR parameterization for short-expiry equity options. The rough Heston model captures the empirical steepness of short-term implied vol skew — a feature SABR systematically underfits.",
      educational_explanation: "Rough volatility models parameterize instantaneous volatility as a fractional Brownian motion with Hurst parameter H ≈ 0.1 (much lower than the standard H = 0.5 of classical Brownian motion). This captures the empirical observation that implied volatility is rougher (more jagged, mean-reverting faster) than standard models predict. The key practical difference: for short-dated options (1-week to 1-month expiry), SABR fits the ATM smile well but systematically underfits the wings and the skew term structure — rough volatility models fit both. For a market maker pricing thousands of options daily, this mistfit translates directly into mispriced inventory and adverse selection by sophisticated counterparties who know the model error. Neural SDE approaches (neural network-parameterized stochastic differential equations) take this further by learning the volatility surface shape from data rather than specifying a functional form — at the cost of model interpretability and calibration stability.",
      why_it_matters: "Understanding the limitations of standard vol models (BSM, SABR) and knowing why rough vol models are replacing them prepares you for conversations about model risk at derivatives desks. This is advanced knowledge that distinguishes quant researchers from quant developers.",
      source_links: [
        { title: "Rough Volatility — Bayer, Friz, Gatheral (2016)", url: "https://arxiv.org/abs/1609.02108" },
        { title: "Neural SDE for Implied Volatility Surfaces — arXiv 2021", url: "https://arxiv.org/abs/2102.01962" },
      ],
      difficulty: "advanced",
      estimated_read_time: "5 min",
    },
    {
      id: "card-qf-2-4",
      content_type: "educational",
      category: "Options Pricing",
      title: "Concept: The Greeks — Delta, Gamma, Vega, Theta, and Why They Matter for Risk Management",
      summary: "The Greeks measure the sensitivity of an option's price to changes in underlying variables. They are the primary language of options risk management and the foundation of hedging strategies used by market makers, hedge funds, and corporate treasury teams.",
      educational_explanation: "Delta (∂V/∂S) measures how much the option price changes per $1 move in the underlying — a call with delta 0.5 gains $0.50 for every $1 increase in the stock. Delta-neutral hedging means holding a short position in delta units of the underlying to eliminate first-order price exposure. Gamma (∂²V/∂S²) measures how fast delta changes — high gamma means the delta hedge rebalances frequently (costly) but also means the option profits more from large moves. Vega (∂V/∂σ) measures sensitivity to implied volatility changes — the most important Greek for volatility traders who have no view on direction. Theta (∂V/∂t) measures time decay — long options lose value as expiry approaches (negative theta), which is why option buyers must be right about direction and timing. The higher-order Greeks (vanna = ∂²V/∂S∂σ, volga = ∂²V/∂σ²) matter for large portfolios because delta and vega hedges drift as the market moves — vanna and volga corrections allow more accurate hedge ratios across a range of market scenarios.",
      why_it_matters: "You cannot have an intelligent conversation about options pricing, hedging, or trading strategies without fluency in the Greeks. Every options risk system, every market maker quote, and every derivatives research paper uses this vocabulary. Mastery of the Greeks is the price of entry to quant derivatives work.",
      source_links: [
        { title: "Options, Futures, and Other Derivatives — Hull (10th Ed.)", url: "https://www.pearson.com/en-us/subject-catalog/p/options-futures-and-other-derivatives/P200000005938" },
        { title: "Interactive Brokers — Options Greeks Calculator", url: "https://www.interactivebrokers.com/en/trading/options-calculator.php" },
      ],
      difficulty: "advanced",
      estimated_read_time: "6 min",
    },
    {
      id: "card-qf-2-5",
      content_type: "educational",
      category: "Factor Models",
      title: "Concept: Information Ratio and the Fundamental Law of Active Management",
      summary: "The Information Ratio (IR) is the primary performance metric for systematic investment strategies. Grinold's Fundamental Law of Active Management provides the mathematical relationship between signal quality, trading breadth, and strategy performance — the foundation of multi-factor portfolio construction.",
      educational_explanation: "The Information Ratio is defined as IR = IC × √BR, where IC (Information Coefficient) is the correlation between predicted and actual returns (signal quality, 0 to 1), and BR (Breadth) is the number of independent bets per year. This deceptively simple formula has profound implications: a strategy with IC = 0.05 (low signal quality) applied to 1,000 independent bets per year achieves IR = 0.05 × √1000 = 1.58 — an excellent result. The same IC applied to only 10 bets achieves IR = 0.16 — barely investable. This is why systematic quant strategies favour high-breadth implementations: many positions, frequent rebalancing, diverse uncorrelated signals. The IC of most equity signals is remarkably low — typically 0.02 to 0.10 — which means breadth (achieved through diversification across many stocks and signal combinations) is the primary lever for improving strategy performance. This insight explains why quant funds run portfolios of 500–2,000 positions rather than concentrated portfolios: they are optimising breadth to extract value from low-IC signals.",
      why_it_matters: "The Fundamental Law explains why diversification is not just risk management — it is alpha generation in systematic investing. Understanding IR and breadth allows you to evaluate any systematic strategy's scalability and performance ceiling from first principles.",
      source_links: [
        { title: "The Fundamental Law of Active Management — Grinold (1989)", url: "https://jpm.pm-research.com/content/15/3/30" },
        { title: "Active Portfolio Management — Grinold & Kahn (2nd Ed.)", url: "https://www.amazon.com/Active-Portfolio-Management-Quantitative-Exceptional/dp/0070248826" },
      ],
      difficulty: "advanced",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Quantitative Finance — Day 1
// ─────────────────────────────────────────────────────────────────────────────

const QF_DAY1 = {
  id: "pkg-qf-1",
  project_id: "proj-quant-finance",
  day_number: 1,
  generated_at: "2026-05-08T07:00:00Z",
  package_headline: "Barra USE5 Adds AI Factor; SEC T+1 Options Settlement Proposed",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 establishes risk factor theory — the conceptual framework that underpins all systematic equity investing. Subsequent days will build on this into derivatives, alternative data, and ML strategies.",
  action_item: "Download the Fama-French 5-factor monthly returns from Kenneth French's data library. Regress a 10-stock portfolio of your choice against FF5. Which factor has the largest loading? What is the adjusted R²?",
  insights: [
    {
      id: "card-qf-1-1",
      content_type: "news",
      category: "Factor Models",
      title: "MSCI Barra USE5 Model Updated with Explicit AI Exposure Factor",
      summary: "MSCI's Barra USE5 commercial risk model received a major update in Q1 2026, adding an explicit 'AI Exposure' factor derived from analyst estimate revisions, patent filings, and capex patterns. The factor adds statistically significant explanatory power for cross-sectional returns in the US large-cap universe and reduces residual variance in AI-adjacent portfolios by 23%.",
      educational_explanation: "Commercial risk models like Barra USE5 decompose stock returns into common factors (market, industry, style) plus idiosyncratic residuals. Adding a new factor is a significant decision: it must explain cross-sectional return variance not already captured by existing factors (orthogonal contribution), be stable over time, and be investable (portfolios can be constructed with meaningful exposure). The AI Exposure factor was constructed using a blend of alternative data: patent filing rates in AI-related technology classes, R&D capex classified as AI-related via NLP, analyst forecast revision patterns correlated with AI commentary in earnings calls, and workforce composition data (AI engineer headcount growth from LinkedIn). Factor construction from multiple heterogeneous signals requires a combining methodology — Barra uses a weighted average of normalized exposures, with weights estimated from a cross-sectional regression on returns. Understanding this construction process separates practitioners who consume Barra outputs from those who can build their own factor models.",
      why_it_matters: "Barra factor model updates reflect where institutional risk attribution is heading. Understanding how the AI factor was constructed — and being able to replicate it with alternative data — is directly applicable to quant research roles at asset managers using Barra as a baseline.",
      source_links: [
        { title: "MSCI Barra Factor Model Research — USE5 Update", url: "https://www.msci.com/analytics/analytics/risk-models" },
      ],
      difficulty: "advanced",
      estimated_read_time: "4 min",
    },
    {
      id: "card-qf-1-2",
      content_type: "news",
      category: "Regulatory",
      title: "SEC Proposes T+1 Settlement Extension to Options — Margin Calculation Impact",
      summary: "Following the 2024 US equity T+1 settlement success, the SEC has proposed extending T+1 to options contracts by Q4 2026. The change would reduce tail margin requirements under SPAN but create new operational challenges for portfolio margining accounts. Industry comment period runs through July 2026.",
      educational_explanation: "SPAN (Standard Portfolio Analysis of Risk) is the margin methodology used by CME and most options exchanges to calculate required collateral for options positions. It evaluates a portfolio across a grid of price and volatility scenarios — typically 16 scenarios covering ±3 standard deviations and ±2 implied volatility moves — and sets margin equal to the worst-case loss across that scenario grid. Moving options settlement from T+2 to T+1 reduces the exposure window by one day, theoretically allowing SPAN to use a shorter lookback for volatility estimation, reducing tail margin requirements. However, the operational challenge is significant: T+1 for options requires same-day exercise notification, assignment, and delivery of the underlying (for physically settled options), which compresses the clearing and settlement workflow substantially. For quant strategies, the relevant impact is on capacity calculations: tighter margin requirements improve leverage ratio, allowing more capital efficiency in options strategies.",
      why_it_matters: "Settlement timeline changes cascade through margin calculations and strategy capacity. Quant strategies running near leverage limits need to model T+1 impacts on SPAN requirements. Understanding how SPAN works and how settlement affects it separates quant engineers from pure signal researchers.",
      source_links: [
        { title: "DTCC — T+1 Settlement Transition Overview", url: "https://www.dtcc.com/settlement-and-asset-services/settlement/t1-settlement" },
        { title: "CME Group — SPAN Methodology", url: "https://www.cmegroup.com/clearing/margins/span-overview.html" },
      ],
      difficulty: "advanced",
      estimated_read_time: "3 min",
    },
    {
      id: "card-qf-1-3",
      content_type: "news",
      category: "ML Trading Strategies",
      title: "AI Equity Rotation Exposes Fama-French Five-Factor Model Gaps — Digital Infrastructure as Missing Factor",
      summary: "Analysis of the 2025 AI-driven equity rotation shows FF5 left 40% of cross-sectional variance unexplained. A custom 'digital infrastructure density' factor (server/network capex as % of assets) explains significant residual return — suggesting institutional risk models need updating for the AI investment supercycle.",
      educational_explanation: "The Fama-French Five-Factor model was calibrated on returns data from 1963–2013. The factors (market, size, value, profitability, investment) captured the dominant sources of cross-sectional return variation in that era. The AI investment supercycle creates a new structural return driver not present in the model's calibration period: companies making concentrated capital investments in digital infrastructure (data centers, networking, AI accelerators) are experiencing return dynamics uncorrelated with traditional investment (the CMA factor measures conservative vs. aggressive total investment, not the quality-adjusted return on AI-specific investments). The practical implication is model specification error: using FF5 for risk attribution on an AI-tilted portfolio will systematically mislabel AI exposure as idiosyncratic risk when it is actually systematic. This inflates tracking error estimates and causes the optimizer to undersize AI exposures relative to their information ratio.",
      why_it_matters: "Factor model gaps are directly exploitable: if the market is not pricing AI infrastructure density as a systematic factor, cross-sectional differences in AI investment intensity generate alpha. Identifying and exploiting factor model gaps is the core quant research skill.",
      source_links: [
        { title: "Kenneth French Data Library — Fama-French Five Factors", url: "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html" },
      ],
      difficulty: "advanced",
      estimated_read_time: "4 min",
    },
    {
      id: "card-qf-1-4",
      content_type: "educational",
      category: "Factor Models",
      title: "Concept: Fama-French Five-Factor Model — From CAPM to Multi-Factor Risk Attribution",
      summary: "The Fama-French Five-Factor model is the standard framework for decomposing equity returns into systematic risk exposures. Understanding how it evolved from CAPM, what each factor captures, and how to use it for portfolio attribution is foundational knowledge for quantitative equity investing.",
      educational_explanation: "CAPM explains stock returns as a single factor (market beta) plus idiosyncratic noise. Fama and French (1993) showed that two additional factors — size (small minus big market cap, SMB) and value (high minus low book-to-market, HML) — significantly improved return explanation, reducing unexplained variance for diversified portfolios from ~60% to ~30%. The 2015 Five-Factor model adds profitability (robust minus weak operating profitability, RMW) and investment (conservative minus aggressive investment rate, CMA), bringing explained variance to ~50–60% for most portfolios. Each factor captures a specific investor behavior or firm characteristic: value reflects the distress premium (value firms are riskier in bad times), size reflects liquidity and information asymmetry, profitability reflects the market's slow updating of profit sustainability, and investment reflects the market's tendency to overprice firms aggressively investing (overconfidence in growth). In practice, factors are implemented as long-short portfolios sorted on the relevant characteristics; the factor return is the performance difference between the long and short legs.",
      why_it_matters: "Factor model literacy is the price of entry to systematic equity investing. Every quant research paper, risk system, and portfolio attribution report uses this framework. Being able to run a factor regression from scratch — and interpret the loadings — is a baseline competency.",
      source_links: [
        { title: "Fama & French (2015) — A Five-Factor Asset Pricing Model", url: "https://www.sciencedirect.com/science/article/abs/pii/S0304405X14002323" },
        { title: "Kenneth French Data Library — Five-Factor Daily Returns", url: "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html" },
      ],
      difficulty: "advanced",
      estimated_read_time: "6 min",
    },
    {
      id: "card-qf-1-5",
      content_type: "educational",
      category: "ML Trading Strategies",
      title: "Concept: Backtesting Pitfalls — Overfitting, Lookahead Bias, and the Multiple Comparison Problem",
      summary: "Backtesting is the process of evaluating a trading strategy on historical data. Understanding its failure modes — overfitting, lookahead bias, survivorship bias, and the multiple comparison problem — is as important as understanding the strategies themselves.",
      educational_explanation: "Lookahead bias occurs when a backtest uses information that would not have been available at the time of the trade — for example, using a company's quarterly earnings reported on March 31 to make a trade on March 28. This is subtle in practice: point-in-time data providers (Compustat Point-in-Time, Bloomberg BICS) solve this; naive data downloads do not. Survivorship bias occurs when a backtest is run on the current universe of stocks (which survived to the present) rather than the historical universe (which included companies that were delisted, went bankrupt, or were acquired) — this systematically overstates performance because you are testing on winners. Overfitting occurs when a strategy is parameterized with enough degrees of freedom to fit historical noise — a strategy with 20 parameters optimized on 5 years of monthly data has more parameters than observations per degree of freedom, almost guaranteeing in-sample fit that does not generalize. The multiple comparison problem (Harvey et al. 2016) shows that with the volume of strategy testing done in academic and industry research, a Sharpe ratio of 3.0 is the minimum threshold for statistical significance after applying a Bonferroni-style multiple testing correction — most published strategies with Sharpe ~1 are likely noise.",
      why_it_matters: "Backtesting failure modes are the primary reason systematic strategies fail in live trading. A strategy that looks excellent in backtest but fails live is worse than no strategy — it consumes capital and confidence. Developing the instinct to identify these biases before running code is one of the most valuable skills in quantitative finance.",
      source_links: [
        { title: "Harvey, Liu & Zhu (2016) — …and the Cross-Section of Expected Returns", url: "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2249314" },
        { title: "Marcos Lopez de Prado — Advances in Financial Machine Learning", url: "https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086" },
      ],
      difficulty: "advanced",
      estimated_read_time: "6 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Supply Chain Intelligence — Day 2 (latest)
// ─────────────────────────────────────────────────────────────────────────────

const SC_DAY2 = {
  id: "pkg-sc-2",
  project_id: "proj-supply-chain",
  day_number: 2,
  generated_at: "2026-05-13T07:00:00Z",
  package_headline: "AI Trade Finance Cuts SME Costs 35%; MLETR Digital Trade Documents Go Live",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 covered demand forecasting as the supply chain's planning engine. Day 2 shifts to the financial and geopolitical layers — how supply chains are funded, how risk is quantified, and how nearshoring decisions are made quantitatively.",
  action_item: "Build a simple supplier risk scoring model in Python. Use publicly available data (company age, geographic location, industry sector) as inputs. Score 10 hypothetical suppliers on a 0–100 scale and rank them by combined risk.",
  insights: [
    {
      id: "card-sc-2-1",
      content_type: "news",
      category: "Trade Finance",
      title: "ML Credit Scoring on Logistics Data Unlocks $450B in Previously Excluded Trade Flows",
      summary: "ML-based creditworthiness scoring drawing on logistics consistency, customs compliance scores, and buyer payment patterns approves 2.4× more SME suppliers at equivalent default rates. Three major platforms report SME borrowing cost reductions of 30–40% for approved suppliers, unlocking access to working capital for $450B in previously excluded global trade flows.",
      educational_explanation: "Traditional bank credit models for supply chain finance rely on financial statement history — balance sheets, income statements, collateral valuations. SME suppliers often have thin documentation, making them uncreditworthy under traditional models despite strong operational performance. ML models trained on alternative signals overcome this: shipment consistency (on-time delivery rate, damage frequency) correlates with operational discipline; customs compliance scores reflect documentation quality and reduce border delay risk; buyer payment velocity reflects the quality of the supplier's commercial relationships. These signals are available from freight forwarders, customs brokers, and trade finance platforms' own transaction histories. The key modelling challenge is class imbalance: defaults are rare events (1–3% of trade transactions), requiring oversampling techniques (SMOTE) and precision-recall optimization rather than accuracy maximization.",
      why_it_matters: "AI-enabled trade finance is restructuring access to working capital — a $18T annual market. Understanding how logistics data translates into credit signals is directly applicable to building or evaluating supply chain finance technology platforms, and to understanding the credit risk dimensions of supplier relationships.",
      source_links: [
        { title: "ICC — Global Trade Finance Survey 2026", url: "https://iccwbo.org/news-publications/policies-reports/icc-global-trade-finance-survey-2026/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-sc-2-2",
      content_type: "news",
      category: "Disruption Risk",
      title: "Resilinc Expands Supplier Risk Scoring to 75K Nodes with 4-Week Lead Time on Disruptions",
      summary: "Resilinc and Everstream Analytics have expanded supplier risk scoring to cover 75,000 Tier-1 and Tier-2 supplier nodes globally, combining satellite imagery, news sentiment, regulatory databases, and financial distress indicators. Average risk detection lead time has increased from 2 days to 4 weeks.",
      educational_explanation: "Supply chain risk intelligence platforms operate by continuously monitoring signals across multiple data categories and correlating them against known disruption patterns. Satellite imagery analysis detects changes in factory activity (parking lot occupancy, truck flow, thermal signatures) before news is published — a significant information lead. NLP on news feeds in 40+ languages provides real-time event detection for labour disputes, natural disasters, and regulatory actions. Financial distress scoring (Altman Z-score variants calibrated to private companies using payment behaviour data) provides early warning of supplier solvency risk. The 4-week detection lead time means procurement teams can begin qualifying alternate sources before a disruption materialises — the critical difference between managed transitions and emergency sourcing. The challenge is noise: a global monitoring network generates thousands of alerts daily, and the signal-to-noise ratio requires continuous model calibration against actual disruption outcomes.",
      why_it_matters: "Supply chain risk intelligence is shifting from reactive (disruption management) to predictive (disruption prevention). Understanding how these monitoring systems work — and what signals are most predictive — is essential for evaluating platform vendors and designing your own risk monitoring architecture.",
      source_links: [
        { title: "Resilinc — Supply Chain Risk Intelligence Platform", url: "https://www.resilinc.com/platform/supply-chain-risk-monitoring/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "3 min",
    },
    {
      id: "card-sc-2-3",
      content_type: "news",
      category: "Trade Policy",
      title: "MLETR Adoption by 10 Nations Enables Legally Binding Electronic Bills of Lading",
      summary: "Ten major trading nations have adopted UNCITRAL's Model Law on Electronic Transferable Records (MLETR), enabling legally binding electronic bills of lading, warehouse receipts, and promissory notes. DBS, HSBC, and Standard Chartered have launched tokenized trade document platforms, reducing document transit time from 5–7 days to minutes.",
      educational_explanation: "A bill of lading (B/L) is the master document in international trade: it serves as (1) a receipt of goods from the carrier, (2) a contract of carriage, and (3) a document of title — meaning whoever holds the B/L owns the cargo. Under traditional practice, B/Ls are paper documents that must be physically couriered between trading parties — creating a 5–7 day transit lag that blocks working capital release from trade finance banks. MLETR creates a legal framework for 'functional equivalence': an electronic record that meets the criteria of uniqueness, identifiability, control, and integrity is legally equivalent to a paper original. Blockchain platforms provide uniqueness (one canonical version) and immutability (no retroactive modification). The working capital implication is significant: releasing payment against an electronic B/L minutes after shipment confirmation rather than waiting for paper documents to arrive reduces the cash conversion cycle for exporters by 5–7 days — worth hundreds of millions in working capital for large commodity traders.",
      why_it_matters: "Digital trade documents are transforming the economics of trade finance. Understanding MLETR and electronic B/L mechanics is essential for evaluating supply chain fintech platforms and understanding the cash conversion cycle improvements available to digitally-enabled trade participants.",
      source_links: [
        { title: "ICC — Electronic Trade Documents Act Implementation Guide", url: "https://iccwbo.org/publication/electronic-trade-documents-act/" },
        { title: "UNCITRAL — Model Law on Electronic Transferable Records", url: "https://uncitral.un.org/en/texts/ecommerce/modellaw/electronic_transferable_records" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-sc-2-4",
      content_type: "educational",
      category: "Disruption Risk",
      title: "Concept: Supply Chain Network Analysis — Graph Theory for Vulnerability Mapping",
      summary: "Supply chain networks are graphs: suppliers and facilities are nodes, material flows are edges. Graph theory provides the analytical tools to identify critical vulnerabilities, single points of failure, and optimal dual-sourcing investments in these networks.",
      educational_explanation: "In network graph theory, betweenness centrality measures how often a node appears on the shortest path between other nodes — high betweenness nodes are 'hubs' through which information or material flows disproportionately. In a supply chain context, a node with high betweenness centrality is a single-point-of-failure risk: if it is disrupted, many supply paths are simultaneously affected. A simple four-step analysis: (1) Model the supply chain as a directed graph with nodes (suppliers, facilities, distribution centers) and edges weighted by flow volume. (2) Compute betweenness centrality for all nodes using NetworkX (Python). (3) Rank nodes by centrality — top 10% are your critical suppliers. (4) For each critical node, calculate the cost of dual-sourcing vs. the expected loss from a disruption (frequency × duration × volume × margin). This framework turns an intuitive concern about supply chain concentration into a quantifiable risk management decision. The Resilinc and Everstream platforms automate steps 1–3 across multi-tier networks; steps 4–5 remain a judgment call requiring internal data.",
      why_it_matters: "Graph-based supply chain analysis is the quantitative framework behind every major supply chain resilience initiative. Being able to implement a basic version in NetworkX and interpret the centrality results is a directly demonstrable skill for supply chain analytics roles.",
      source_links: [
        { title: "NetworkX — Supply Chain Network Analysis Tutorial", url: "https://networkx.org/documentation/stable/tutorial.html" },
        { title: "Sheffi (2005) — The Resilient Enterprise (MIT Press)", url: "https://mitpress.mit.edu/9780262693493/the-resilient-enterprise/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
    {
      id: "card-sc-2-5",
      content_type: "educational",
      category: "Trade Finance",
      title: "Concept: Letters of Credit — How International Trade Finance Works",
      summary: "A Letter of Credit (LC) is the foundational instrument of international trade finance — a bank's guarantee to pay the seller upon presentation of compliant shipping documents. Understanding LC mechanics is essential for analysing supply chain financial risk and working capital optimization.",
      educational_explanation: "In a documentary Letter of Credit: (1) the buyer (importer) instructs their bank (issuing bank) to issue a LC in favour of the seller (exporter). (2) The issuing bank sends the LC to the seller's bank (advising/confirming bank). (3) The seller ships the goods and presents the required documents (commercial invoice, bill of lading, packing list, certificate of origin) to the advising bank. (4) The advising bank checks document compliance against the LC terms and, if compliant, pays the seller (sight LC) or accepts a time draft (usance LC). (5) The advising bank forwards documents to the issuing bank for reimbursement. The LC substitutes the credit of a bank for the credit of the buyer — the seller accepts payment risk from a bank (typically investment grade) rather than an unfamiliar foreign buyer. The working capital tension: usance (deferred payment) LCs allow the buyer to receive goods 30–180 days before paying, extending the buyer's payables period. Supply chain finance programs built on top of the LC structure (discounting, forfaiting) convert the buyer's payable into the seller's immediate liquidity at lower cost than unsecured credit.",
      why_it_matters: "LCs underpin a large portion of global trade finance, particularly for cross-border transactions where buyer credit risk is unknown. Understanding the mechanics tells you why LC discounting and supply chain finance programs create working capital value — and where the risk and cost are in the chain.",
      source_links: [
        { title: "ICC — Uniform Customs and Practice for Documentary Credits (UCP 600)", url: "https://iccwbo.org/publication/ucp-600-uniform-customs-and-practice-for-documentary-credits/" },
        { title: "Trade Finance Global — Letter of Credit Explained", url: "https://www.tradefinanceglobal.com/letters-of-credit/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Supply Chain Intelligence — Day 1
// ─────────────────────────────────────────────────────────────────────────────

const SC_DAY1 = {
  id: "pkg-sc-1",
  project_id: "proj-supply-chain",
  day_number: 1,
  generated_at: "2026-05-07T07:00:00Z",
  package_headline: "AI Demand Forecasting Cuts Inventory Costs 22%; CSRD Scope 3 Data Collection Begins",
  content_mix: "3 news · 2 educational",
  learning_thread: "Day 1 establishes demand forecasting as the supply chain's planning foundation — the model that drives every downstream decision from inventory policy to procurement timing.",
  action_item: "Download the M5 Forecasting Challenge dataset from Kaggle. Implement a naive seasonal baseline (same day last year) and compare its WRMSSE score to a Facebook Prophet model. This 2-model comparison is the standard starting point for demand forecasting benchmarks.",
  insights: [
    {
      id: "card-sc-1-1",
      content_type: "news",
      category: "Demand Forecasting",
      title: "Probabilistic AI Forecasting Reduces Inventory Holding Costs 22% Across Retail and CPG",
      summary: "Enterprise AI demand forecasting platforms report consistent 20–25% reductions in inventory holding costs across large retail and CPG deployments. The key enabler is probabilistic forecasting — models outputting full demand distributions (P10/P50/P90) rather than single point estimates — which enables smarter safety stock calculation.",
      educational_explanation: "Traditional inventory systems use a simple safety stock formula: SS = z × σ_d × √LT, where z is the service level z-score, σ_d is demand standard deviation, and LT is lead time. This formula assumes demand and lead time are independent and normally distributed — assumptions that often fail in practice (demand is skewed, lead times are correlated). Probabilistic forecasting models output the full demand distribution at each future horizon, allowing safety stock to be computed from the actual predicted distribution rather than a normal approximation. For a P10/P50/P90 forecast: the P90 quantity is stocked if the service level target is 90%; the P50 is the base order; the P10 informs the minimum acceptable inventory. The accuracy improvement comes from models that capture promotions, seasonality, event effects, and cross-product correlations — all of which are poorly handled by parametric distributions assumed by classic safety stock formulas.",
      why_it_matters: "Safety stock optimization from probabilistic forecasts is the highest-ROI application of ML in supply chain. Understanding the connection between forecast distributional output and safety stock calculation is the bridge between data science and supply chain operations that most practitioners miss.",
      source_links: [
        { title: "o9 Solutions — AI Demand Sensing White Paper", url: "https://o9solutions.com/resources/white-papers/ai-demand-sensing/" },
        { title: "Kaggle — M5 Forecasting Competition", url: "https://www.kaggle.com/competitions/m5-forecasting-accuracy" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-sc-1-2",
      content_type: "news",
      category: "Regulatory",
      title: "CSRD Scope 3 Disclosures Force Supply Chain Emissions Mapping at 50,000 EU Companies",
      summary: "EU Corporate Sustainability Reporting Directive requires all large EU companies to disclose Scope 3 (supply chain) emissions from FY2025. First mandatory disclosures are due 2026. Companies are discovering they lack the granular supplier-level emissions data needed — triggering emergency supplier data collection projects.",
      educational_explanation: "Scope 3 emissions are indirect greenhouse gas emissions that occur in a company's value chain — both upstream (from suppliers: raw material extraction, manufacturing, transportation to the company) and downstream (customer use of products, end-of-life processing). For most consumer products companies, Scope 3 represents 70–90% of total emissions — making it the most impactful but also most difficult category to measure. The measurement challenge is data: a medium-sized manufacturer might have 500–2,000 Tier-1 suppliers, each with their own supply chains. CSRD requires emissions data for Scope 3 Categories 1 (purchased goods and services), 4 (upstream transportation), 11 (use of sold products), and 12 (end-of-life treatment). The standard methodology — spend-based allocation using EEIO (Environmentally Extended Input-Output) factors — is inaccurate but available. Activity-based measurement (supplier-specific emissions factors for each category) is more accurate but requires supplier data collection programs that most companies have never operated.",
      why_it_matters: "Scope 3 measurement is forcing supply chain teams to build supplier data collection infrastructure. This intersection of sustainability and supply chain data is creating significant demand for professionals who understand both the emissions accounting methodology and the supplier relationship management required to collect the data.",
      source_links: [
        { title: "European Commission — CSRD Implementation Overview", url: "https://finance.ec.europa.eu/capital-markets-union-and-financial-markets/company-reporting-and-auditing/company-reporting/corporate-sustainability-reporting_en" },
        { title: "GHG Protocol — Corporate Value Chain (Scope 3) Standard", url: "https://ghgprotocol.org/scope-3-standard" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "4 min",
    },
    {
      id: "card-sc-1-3",
      content_type: "news",
      category: "AI Logistics Platforms",
      title: "Maersk AI Customs Platform Cuts Cross-Border Clearance from 4.2 to 1.4 Days",
      summary: "ML document classification and risk-scoring deployed across G7 trade lanes reduced customs broker workload 70% and average clearance time 67%. The system classifies HS codes, flags compliance anomalies, and pre-files entries — turning customs from a reactive to a predictive process.",
      educational_explanation: "Customs clearance involves three main tasks that AI is automating: (1) HS code classification — the Harmonized System is a 6-digit international product nomenclature with 5,000+ codes; mapping product descriptions to HS codes is a text classification problem that ML solves with ~95% accuracy vs. ~80% for human classifiers on complex products. (2) Document verification — comparing declared values, weights, and quantities across multiple documents (commercial invoice, packing list, certificate of origin) for consistency; rule-based systems miss ~15% of discrepancies that ML catches. (3) Risk scoring — identifying shipments likely to be stopped for physical inspection based on shipper history, trade lane, commodity type, and declared value patterns. Pre-filing (submitting entry data before the ship arrives at port) is enabled when risk scoring is confident enough to process electronically without human review. Maersk's 67% clearance time reduction is primarily from eliminating the human review queue for the 85% of shipments that are low-risk.",
      why_it_matters: "AI-assisted customs is restructuring the economics of cross-border logistics. Understanding the technical workflow — HS classification, document extraction, risk scoring — helps you evaluate logistics AI platforms and understand where competitive advantages in cross-border trade are being built.",
      source_links: [
        { title: "Maersk — Digital Trade Innovation Report 2025", url: "https://www.maersk.com/news/articles/2025/digital-trade-innovation" },
        { title: "World Customs Organization — HS Classification", url: "https://www.wcoomd.org/en/topics/nomenclature/overview/what-is-the-harmonized-system.aspx" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "3 min",
    },
    {
      id: "card-sc-1-4",
      content_type: "educational",
      category: "Demand Forecasting",
      title: "Concept: ARIMA, Seasonal Decomposition, and Choosing a Forecasting Model",
      summary: "ARIMA (AutoRegressive Integrated Moving Average) is the classical statistical model for univariate time-series forecasting. Understanding its components and assumptions is the foundation for evaluating when to use classical statistical models versus modern ML approaches.",
      educational_explanation: "ARIMA(p,d,q) is defined by three parameters: p = order of the autoregressive component (how many past values predict the current value), d = degree of differencing (how many times to difference the series to achieve stationarity), q = order of the moving average component (how many past forecast errors enter the current prediction). Seasonal ARIMA (SARIMA) adds seasonal counterparts (P,D,Q,s) for periodic patterns. The model selection process uses: (1) ADF test to determine the differencing order d (test for unit root), (2) ACF/PACF plots to identify p and q, (3) AIC/BIC model selection criteria. ARIMA's limitations for supply chain: it cannot use external regressors (promotions, holidays, price changes) without extensions (ARIMAX); it assumes linear relationships; and it requires separate models for each SKU — impractical at scale. Facebook Prophet addresses the first limitation by design; deep learning approaches (LSTM, Temporal Fusion Transformer) address all three but require substantially more data. The practical rule: ARIMA for stable, low-volume SKUs; ML models for high-volume SKUs with external drivers.",
      why_it_matters: "ARIMA literacy is required to have an informed conversation about forecast model selection — when to use classical statistical methods and when to move to ML. Understanding why ARIMA fails on promotional data is the conceptual entry point to modern demand sensing.",
      source_links: [
        { title: "Hyndman & Athanasopoulos — Forecasting: Principles and Practice (free online)", url: "https://otexts.com/fpp3/" },
        { title: "statsmodels — ARIMA Implementation in Python", url: "https://www.statsmodels.org/stable/tsa.html" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "6 min",
    },
    {
      id: "card-sc-1-5",
      content_type: "educational",
      category: "AI Logistics Platforms",
      title: "Concept: Incoterms 2020 — Who Bears Risk and Cost in International Shipments",
      summary: "Incoterms (International Commercial Terms) define the responsibilities, risks, and costs between buyers and sellers in international trade. Every supply chain practitioner needs to understand Incoterms because they determine the point at which risk transfers — which directly affects inventory valuation, insurance requirements, and financing structures.",
      educational_explanation: "Incoterms 2020 defines 11 standard trade terms. The key axis is risk transfer point: EXW (Ex Works) puts all transport cost and risk on the buyer from the moment goods leave the factory; DDP (Delivered Duty Paid) puts all transport cost, risk, import duties, and customs clearance on the seller up to the buyer's door. The most commonly used terms: FOB (Free On Board) — seller delivers to the named port; risk transfers when goods cross the ship's rail. CIF (Cost, Insurance, Freight) — seller bears cost and insurance to destination port; risk transfers at origin port. DAP (Delivered At Place) — seller bears risk and cost to named destination. The supply chain implication: the Incoterm determines where in the supply chain title and risk transfer, which affects (1) who books and pays for freight and insurance, (2) where goods are valued on each party's balance sheet, (3) what financing instruments are available (FOB basis is standard for trade finance because the bank knows exactly when it takes possession of the B/L). Misunderstanding Incoterms is one of the most common causes of supply chain disputes in international contracts.",
      why_it_matters: "Incoterms are referenced in every international purchase order and trade finance document. Not understanding them means not understanding the risk allocation and cash flow timing in any international supply chain relationship. This is foundational operational knowledge.",
      source_links: [
        { title: "ICC — Incoterms 2020 Official Guide", url: "https://iccwbo.org/publication/incoterms-2020/" },
        { title: "Trade Finance Global — Incoterms Explained", url: "https://www.tradefinanceglobal.com/freight-forwarding/incoterms/" },
      ],
      difficulty: "intermediate",
      estimated_read_time: "5 min",
    },
  ],
}

// ─────────────────────────────────────────────────────────────────────────────
// Lookup maps
// ─────────────────────────────────────────────────────────────────────────────

export const MOCK_PACKAGES_BY_PROJECT = {
  "proj-ai-manufacturing": [AIM_DAY2, AIM_DAY1],
  "proj-indian-pharma":    [IP_DAY2,  IP_DAY1],
  "proj-quant-finance":    [QF_DAY2,  QF_DAY1],
  "proj-supply-chain":     [SC_DAY2,  SC_DAY1],
}

// Legacy alias (kept for any imports that used the old name)
export const MOCK_INSIGHTS_BY_PROJECT = MOCK_PACKAGES_BY_PROJECT
