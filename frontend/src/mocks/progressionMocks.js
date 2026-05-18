/**
 * Mock progression state for each learning project.
 * Used when VITE_USE_MOCK=true — no backend calls needed.
 *
 * Reflects 2 days of accumulated learning per project:
 * explored_concepts grows from daily card categories + news titles.
 * suggested_next_topics are the next items from each domain's topic pool.
 */

export const MOCK_PROGRESSIONS = {
  "proj-ai-manufacturing": {
    project_id:            "proj-ai-manufacturing",
    current_level:         "intermediate",
    current_focus:         "Computer Vision for Quality Control",
    explored_concepts: [
      "Predictive Maintenance",
      "IoT Sensor Networks",
      "Anomaly Detection",
      "Computer Vision Basics",
      "Digital Factory Overview",
      "Quality Inspection",
      "Process Optimization",
    ],
    completed_topics: [
      "Introduction to AI in Manufacturing",
      "Sensor Data Collection and Processing",
      "Basic Predictive Maintenance Models",
    ],
    suggested_next_topics: [
      "Digital Twins in Production",
      "Edge AI Deployment",
      "Reinforcement Learning for Process Optimization",
      "Generative AI for Design Engineering",
    ],
    days_completed: 2,
    updated_at:     "2026-05-16T07:00:00Z",
  },

  "proj-indian-pharma": {
    project_id:            "proj-indian-pharma",
    current_level:         "intermediate",
    current_focus:         "API Manufacturing and Export Compliance",
    explored_concepts: [
      "FDA Regulatory Pathways",
      "EMA Guidelines",
      "API Manufacturing",
      "GMP Compliance",
      "Export Pricing Dynamics",
      "ANDA Filing Process",
      "Generic Drug Markets",
    ],
    completed_topics: [
      "India Pharma Export Overview",
      "Key Regulatory Bodies (FDA, EMA, CDSCO)",
      "API vs Formulation Exports",
    ],
    suggested_next_topics: [
      "Contract Manufacturing Organizations",
      "Post-COVID Export Realignment",
      "Specialty Chemicals Supply Chain",
      "Digital Transformation in Pharma QC",
    ],
    days_completed: 2,
    updated_at:     "2026-05-15T07:00:00Z",
  },

  "proj-quant-finance": {
    project_id:            "proj-quant-finance",
    current_level:         "advanced",
    current_focus:         "Factor Models and Risk Attribution",
    explored_concepts: [
      "Modern Portfolio Theory",
      "CAPM",
      "Multi-Factor Models",
      "Options Pricing (Black-Scholes)",
      "Risk Parity",
      "Statistical Arbitrage",
      "Derivatives Pricing",
    ],
    completed_topics: [
      "Modern Portfolio Theory",
      "CAPM and Systematic Risk",
      "Multi-Factor Models (Fama-French)",
      "Options Pricing Fundamentals",
    ],
    suggested_next_topics: [
      "Machine Learning for Alpha Generation",
      "Alternative Data in Systematic Trading",
      "High-Frequency Trading Microstructure",
      "Volatility Surface Modelling",
    ],
    days_completed: 2,
    updated_at:     "2026-05-14T07:00:00Z",
  },

  "proj-supply-chain": {
    project_id:            "proj-supply-chain",
    current_level:         "intermediate",
    current_focus:         "Supply Chain Optimization",
    explored_concepts: [
      "Demand Forecasting",
      "Supplier Risk Management",
      "Logistics Network Design",
      "Inventory Optimization",
      "Blockchain for Traceability",
      "Disruption Risk",
      "AI Logistics Platforms",
    ],
    completed_topics: [
      "Supply Chain Fundamentals",
      "Demand Sensing and Forecasting",
      "Supplier Evaluation Frameworks",
    ],
    suggested_next_topics: [
      "Digital Twins in Supply Chain",
      "AI-Driven Procurement",
      "Supply Chain Resilience Metrics",
      "Last-Mile Delivery Optimization",
    ],
    days_completed: 2,
    updated_at:     "2026-05-13T07:00:00Z",
  },
}
