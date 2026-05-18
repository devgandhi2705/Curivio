/**
 * Mock responses for all research API endpoints.
 * Matches the exact shape returned by the FastAPI backend.
 * Used when VITE_USE_MOCK=true.
 */

export const MOCK_TOPIC_EXPANSION = {
  topic: "RAG Pipelines",
  prerequisites: [
    "Vector Embeddings",
    "Transformer Architecture",
    "Cosine Similarity",
  ],
  related_topics: [
    "Hybrid Retrieval",
    "Knowledge Graphs",
    "Semantic Search",
    "Fine-tuning LLMs",
    "Prompt Engineering",
  ],
  advanced_follow_ups: [
    "Agentic RAG",
    "Multi-hop Reasoning",
    "GraphRAG",
    "Long-context LLMs",
  ],
  learning_progression: [
    "Vector Embeddings",
    "Semantic Search",
    "RAG Pipelines",
    "Hybrid Retrieval",
    "Agentic RAG",
    "GraphRAG",
  ],
  progression_rationale:
    "Understanding embeddings and semantic search provides the retrieval foundation. RAG combines retrieval with generation, while hybrid methods and agentic variants push into production-grade systems.",
  generated_at: "2026-05-15T10:00:00",
}

export const MOCK_DEEP_RESEARCH = {
  topic: "RAG Pipelines",
  related_concepts: [
    "Dense Passage Retrieval (DPR)",
    "FAISS vector indexing",
    "Cross-encoder re-ranking",
    "Context window management",
    "Chunking strategies",
  ],
  implementation_ideas: [
    "Build a multi-stage retrieval pipeline with bi-encoder + cross-encoder re-ranking",
    "Implement adaptive chunk sizing based on document structure",
    "Add query expansion using HyDE (Hypothetical Document Embeddings)",
    "Integrate citation tracking for source attribution",
  ],
  practical_applications: [
    "Enterprise document Q&A systems",
    "Code repository search and explanation",
    "Legal contract analysis with source grounding",
    "Medical literature review assistants",
  ],
  advanced_follow_ups: [
    "Self-RAG: LLMs that decide when to retrieve",
    "Corrective RAG (CRAG) with retrieval validation",
    "RAPTOR: recursive abstractive summarization for retrieval",
    "Speculative RAG for latency reduction",
  ],
  research_summary:
    "RAG (Retrieval-Augmented Generation) grounds LLM outputs in external knowledge by fetching relevant documents at inference time. Modern pipelines combine dense bi-encoder retrieval with cross-encoder re-ranking, chunking strategies, and metadata filtering. The key engineering challenges are retrieval precision, context length management, and latency—solved through hybrid sparse-dense retrieval, HyDE query expansion, and speculative decoding techniques.",
  sources: [
    "https://arxiv.org/abs/2005.11401",
    "https://arxiv.org/abs/2310.11511",
    "https://github.com/langchain-ai/langchain",
    "https://docs.llamaindex.ai/en/stable/",
  ],
  generated_at: "2026-05-15T10:00:00",
}

export const MOCK_LEARNING_PATH = {
  topic: "RAG Pipelines",
  learning_stage: "intermediate",
  beginner: [
    {
      concept: "What is RAG?",
      explanation:
        "RAG combines a retrieval system (vector database) with a language model. The retriever finds relevant documents; the generator synthesises an answer conditioned on those documents.",
      why_it_matters:
        "Grounds LLM responses in real, up-to-date information instead of relying solely on parametric memory—reducing hallucinations.",
      resources: [
        "Docs: https://docs.langchain.com/docs/use-cases/question-answering",
        "Video: https://www.youtube.com/watch?v=T-D1OfcDW1M",
        "Blog: https://towardsdatascience.com/retrieval-augmented-generation-rag-explained",
      ],
    },
    {
      concept: "Vector Embeddings",
      explanation:
        "Text is converted to high-dimensional float vectors using encoder models (e.g., text-embedding-3-small). Semantically similar text clusters near each other in this space.",
      why_it_matters:
        "Embeddings are the 'lookup mechanism' of RAG—they allow fuzzy semantic search instead of brittle keyword matching.",
      resources: [
        "Course: https://www.deeplearning.ai/short-courses/building-applications-vector-databases/",
        "Docs: https://platform.openai.com/docs/guides/embeddings",
      ],
    },
    {
      concept: "Vector Databases",
      explanation:
        "Specialised stores (Pinecone, Qdrant, Weaviate, FAISS) that index float vectors and support approximate nearest-neighbour (ANN) search at scale.",
      why_it_matters:
        "Without fast ANN search, retrieval latency would make RAG impractical for production workloads.",
      resources: [
        "Docs: https://docs.pinecone.io/guides/getting-started/quickstart",
        "Repo: https://github.com/facebookresearch/faiss",
      ],
    },
  ],
  intermediate: [
    {
      concept: "Chunking Strategies",
      explanation:
        "Splitting source documents into retrievable units. Fixed-size, sentence-boundary, recursive, and semantic chunking each trade off retrieval precision against chunk coherence.",
      why_it_matters:
        "Chunk quality is the single biggest driver of RAG answer quality—too large wastes context; too small loses meaning.",
      resources: [
        "Blog: https://www.pinecone.io/learn/chunking-strategies/",
        "Docs: https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/",
      ],
    },
    {
      concept: "Re-ranking with Cross-encoders",
      explanation:
        "After bi-encoder retrieval returns a candidate set, a cross-encoder jointly encodes the query+document pair to produce a more accurate relevance score. Top-k re-ranked results are passed to the LLM.",
      why_it_matters:
        "Bi-encoders trade precision for speed; cross-encoders recover precision at a small latency cost, significantly improving final answer quality.",
      resources: [
        "Paper: https://arxiv.org/abs/1910.14424",
        "Repo: https://github.com/UKPLab/sentence-transformers",
        "Docs: https://docs.cohere.com/docs/reranking",
      ],
    },
    {
      concept: "Query Expansion with HyDE",
      explanation:
        "HyDE (Hypothetical Document Embeddings) asks the LLM to generate a hypothetical answer, embeds it, and searches for real documents near that embedding rather than near the raw question.",
      why_it_matters:
        "Query and answer live in different embedding regions; HyDE bridges the gap, especially for technical or knowledge-dense questions.",
      resources: [
        "Paper: https://arxiv.org/abs/2212.10496",
        "Blog: https://medium.com/@florian_algo/hypotetical-document-embeddings-hyde",
      ],
    },
  ],
  advanced: [
    {
      concept: "Self-RAG",
      explanation:
        "The LLM learns to emit special tokens (RETRIEVE, ISREL, ISSUP, ISUSE) to decide when to retrieve, whether retrieved passages are relevant, and whether its own output is supported.",
      why_it_matters:
        "Removes the retrieval-every-time overhead and teaches the model to distinguish what it knows from what it needs to look up.",
      resources: [
        "Paper: https://arxiv.org/abs/2310.11511",
        "Repo: https://github.com/AkariAsai/self-rag",
      ],
    },
    {
      concept: "GraphRAG",
      explanation:
        "Microsoft's GraphRAG extracts a knowledge graph from the corpus and uses community summarisation so that global questions (about themes or entities spanning many documents) are answerable.",
      why_it_matters:
        "Standard RAG fails on global sensemaking questions; graph-structured retrieval provides entity-relationship context unavailable in flat chunk stores.",
      resources: [
        "Paper: https://arxiv.org/abs/2404.16130",
        "Repo: https://github.com/microsoft/graphrag",
        "Docs: https://microsoft.github.io/graphrag/",
      ],
    },
    {
      concept: "Agentic RAG",
      explanation:
        "Wraps the RAG pipeline in an agent loop: the LLM can issue multiple retrieval calls, reformulate queries on failure, synthesise across multiple retrieved batches, and decide when it has enough context.",
      why_it_matters:
        "Single-shot RAG fails on multi-hop or ambiguous questions; agentic loops enable iterative refinement similar to how a human researcher would work.",
      resources: [
        "Blog: https://towardsdatascience.com/agentic-rag-a-conceptual-overview",
        "Docs: https://docs.llamaindex.ai/en/stable/examples/agent/",
        "Repo: https://github.com/run-llama/llama_index",
      ],
    },
    {
      concept: "Evaluation: RAGAS",
      explanation:
        "RAGAS is a reference-free evaluation framework that scores RAG pipelines on faithfulness (hallucination rate), answer relevance, context precision, and context recall.",
      why_it_matters:
        "Without systematic evaluation you cannot tell whether pipeline changes actually improve quality—RAGAS provides a fast, LLM-graded signal.",
      resources: [
        "Repo: https://github.com/explodinggradients/ragas",
        "Docs: https://docs.ragas.io/",
        "Paper: https://arxiv.org/abs/2309.15217",
      ],
    },
  ],
  repositories: [
    {
      name: "langchain-ai/langchain",
      description:
        "Building applications with LLMs through composability — the de-facto RAG framework",
      stars: 92000,
      url: "https://github.com/langchain-ai/langchain",
      language: "Python",
      topics: ["rag", "llm", "agents"],
    },
    {
      name: "run-llama/llama_index",
      description:
        "LlamaIndex is a data framework for LLM-based applications focused on ingestion, structuring, and retrieval",
      stars: 36000,
      url: "https://github.com/run-llama/llama_index",
      language: "Python",
      topics: ["rag", "data-indexing", "retrieval"],
    },
    {
      name: "microsoft/graphrag",
      description:
        "A modular graph-based Retrieval-Augmented Generation (RAG) system",
      stars: 18000,
      url: "https://github.com/microsoft/graphrag",
      language: "Python",
      topics: ["graphrag", "knowledge-graph", "llm"],
    },
    {
      name: "explodinggradients/ragas",
      description: "Evaluation framework for your RAG pipelines",
      stars: 7500,
      url: "https://github.com/explodinggradients/ragas",
      language: "Python",
      topics: ["evaluation", "rag", "llm"],
    },
    {
      name: "facebookresearch/faiss",
      description:
        "A library for efficient similarity search and clustering of dense vectors",
      stars: 31000,
      url: "https://github.com/facebookresearch/faiss",
      language: "C++",
      topics: ["vector-search", "ann", "embeddings"],
    },
  ],
  generated_at: "2026-05-15T10:00:00",
}

export const MOCK_CATEGORIZED_RESOURCES = {
  results: [
    { resource: "Docs: https://docs.langchain.com/docs/use-cases/question-answering", category: "documentation", confidence: 1.0 },
    { resource: "Video: https://www.youtube.com/watch?v=T-D1OfcDW1M", category: "video", confidence: 1.0 },
    { resource: "Blog: https://towardsdatascience.com/retrieval-augmented-generation-rag-explained", category: "blog_post", confidence: 1.0 },
    { resource: "Course: https://www.deeplearning.ai/short-courses/building-applications-vector-databases/", category: "tutorial", confidence: 1.0 },
    { resource: "Docs: https://platform.openai.com/docs/guides/embeddings", category: "documentation", confidence: 1.0 },
    { resource: "Docs: https://docs.pinecone.io/guides/getting-started/quickstart", category: "documentation", confidence: 1.0 },
    { resource: "Repo: https://github.com/facebookresearch/faiss", category: "github_repository", confidence: 0.95 },
    { resource: "Blog: https://www.pinecone.io/learn/chunking-strategies/", category: "blog_post", confidence: 0.9 },
    { resource: "Docs: https://docs.llamaindex.ai/en/stable/module_guides/loading/node_parsers/", category: "documentation", confidence: 1.0 },
    { resource: "Paper: https://arxiv.org/abs/1910.14424", category: "research_paper", confidence: 1.0 },
    { resource: "Repo: https://github.com/UKPLab/sentence-transformers", category: "github_repository", confidence: 0.95 },
    { resource: "Docs: https://docs.cohere.com/docs/reranking", category: "documentation", confidence: 1.0 },
    { resource: "Paper: https://arxiv.org/abs/2212.10496", category: "research_paper", confidence: 0.95 },
    { resource: "Blog: https://medium.com/@florian_algo/hypotetical-document-embeddings-hyde", category: "blog_post", confidence: 0.9 },
    { resource: "Paper: https://arxiv.org/abs/2310.11511", category: "research_paper", confidence: 1.0 },
    { resource: "Repo: https://github.com/AkariAsai/self-rag", category: "github_repository", confidence: 0.95 },
    { resource: "Paper: https://arxiv.org/abs/2404.16130", category: "research_paper", confidence: 1.0 },
    { resource: "Repo: https://github.com/microsoft/graphrag", category: "github_repository", confidence: 0.95 },
    { resource: "Docs: https://microsoft.github.io/graphrag/", category: "documentation", confidence: 0.9 },
    { resource: "Blog: https://towardsdatascience.com/agentic-rag-a-conceptual-overview", category: "blog_post", confidence: 0.9 },
    { resource: "Docs: https://docs.llamaindex.ai/en/stable/examples/agent/", category: "documentation", confidence: 1.0 },
    { resource: "Repo: https://github.com/run-llama/llama_index", category: "github_repository", confidence: 0.95 },
    { resource: "Repo: https://github.com/explodinggradients/ragas", category: "github_repository", confidence: 0.95 },
    { resource: "Docs: https://docs.ragas.io/", category: "documentation", confidence: 1.0 },
    { resource: "Paper: https://arxiv.org/abs/2309.15217", category: "research_paper", confidence: 1.0 },
  ],
  summary: {
    documentation: 9,
    research_paper: 5,
    github_repository: 6,
    blog_post: 4,
    video: 1,
    tutorial: 1,
  },
}

export const MOCK_SESSION_CONTEXT = {
  topic: "RAG Pipelines",
  times_explored: 3,
  has_deep_research: true,
  has_learning_path: true,
  has_topic_expansion: true,
  has_github_repos: true,
  first_explored_at: "2026-05-10 09:00:00",
  last_activity_at: "2026-05-15 10:00:00",
  recommended_next: [],
}

export const MOCK_INTELLIGENCE_FEED = {
  intelligence_brief: {
    headline: "LLM Tool Calling Reshapes How Engineers Build Production AI Systems",
    executive_summary:
      "Function calling in LLMs has moved from experimental to production-critical infrastructure, with OpenAI, Anthropic, and Mistral converging on a compatible tool-call protocol. Engineers who master structured output and multi-step tool chains will build more reliable pipelines — those who don't will inherit brittle regex-based extraction code.",
    key_signals: [
      "OpenAI, Anthropic, and Mistral now share a compatible tool-call schema — multi-provider portability is real.",
      "Reliability of tool selection correlates with prompt clarity, not model size — a well-documented schema beats a bigger model.",
      "Multi-step tool chains expose a new failure class: partial completions and silent schema mismatches that pass validation.",
    ],
  },
  sections: [
    {
      type: "industry_news",
      title: "Industry & Technology News",
      items: [
        {
          title: "OpenAI Structured Outputs Eliminates JSON Validation Overhead",
          insight:
            "Constrained decoding forces the model to emit JSON that exactly matches a caller-supplied schema. This shifts validation from post-processing to generation, removing an entire class of retry logic from application code.",
          why_it_matters:
            "AI backend code becomes measurably simpler — no more retry loops for malformed tool responses.",
          sources: [],
        },
        {
          title: "Anthropic Tool Use API Reaches Feature Parity with GPT-4 Turbo",
          insight:
            "Claude now supports parallel tool calls and streaming tool responses. The behavioral gap between providers has narrowed to latency and cost, not capability.",
          why_it_matters:
            "Multi-provider architectures are practical — you can arbitrage cost without rewriting tool schemas.",
          sources: [],
        },
      ],
    },
    {
      type: "market_trends",
      title: "Market Trends & Business Developments",
      items: [
        {
          title: "AI Inference Costs Down 10x in 18 Months — Commodity Pressure Accelerates",
          insight:
            "Groq, Together AI, and Fireworks are compressing inference margins toward zero. The competitive moat is shifting from raw model capability to latency, fine-tuning UX, and vertical-specific data.",
          why_it_matters:
            "Startups built on API cost arbitrage face margin collapse — the winners will own proprietary data or domain fine-tuned models.",
          sources: [],
        },
        {
          title: "Enterprise AI Adoption Concentrates in Document Processing and RAG",
          insight:
            "Document extraction and RAG over internal knowledge bases — not creative generation — are driving the first wave of provable enterprise ROI. Production deployments favor retrieval patterns over chat interfaces.",
          why_it_matters:
            "The near-term market for AI tooling is in retrieval and extraction infrastructure, not generative UX.",
          sources: [],
        },
      ],
    },
    {
      type: "technical_discoveries",
      title: "Technical Discoveries & Research",
      items: [
        {
          title: "QLoRA Fine-Tuning at 4-bit Precision Matches Full Fine-Tuning on Downstream Tasks",
          insight:
            "Quantized LoRA closes the quality gap with full fine-tuning while reducing GPU memory by 4–8x. The key insight: most weights are redundant for task-specific adaptation, making quantization safe for the adapter layers.",
          why_it_matters:
            "Custom fine-tuned models are now accessible to engineers without A100-tier infrastructure.",
          sources: [],
        },
        {
          title: "Speculative Decoding Cuts LLM Latency 30–50% Without Quality Loss",
          insight:
            "A small draft model proposes tokens; the main model verifies batches in parallel. The parallelism achieves 3–4x token throughput on the verification step with no accuracy trade-off.",
          why_it_matters:
            "Streaming UX improves dramatically — both first-token latency and throughput improve simultaneously.",
          sources: [],
        },
      ],
    },
  ],
  learning_track: [
    {
      title: "Function Calling & Tool Use",
      reason:
        "Direct prerequisite for everything in this brief — you cannot debug multi-tool pipelines without understanding the protocol.",
      difficulty: "beginner",
      chat_connection:
        "Builds on the LLM fundamentals you've been exploring in recent chat sessions.",
      category: "AI / ML",
    },
    {
      title: "RAG Pipeline Architecture",
      reason:
        "The dominant enterprise deployment pattern — combining vector retrieval with LLM synthesis is the most in-demand applied AI skill right now.",
      difficulty: "intermediate",
      chat_connection: null,
      category: "AI / ML",
    },
    {
      title: "LoRA & Fine-Tuning",
      reason:
        "Lets you customize models for domain tasks without full training cost — bridges research papers and production deployments.",
      difficulty: "intermediate",
      chat_connection: null,
      category: "AI / ML",
    },
    {
      title: "Speculative Decoding & Inference Optimization",
      reason:
        "Understanding the inference stack separates engineers who consume AI APIs from those who optimize and operate them at scale.",
      difficulty: "advanced",
      chat_connection: null,
      category: "AI / ML",
    },
  ],
  action_items: [
    "Implement a minimal tool-use loop with the OpenAI function calling API — define 2 tools, verify schema compliance, handle edge cases in < 100 lines.",
    "Build a 3-step RAG pipeline: chunk a 10-page PDF, embed with a small model, retrieve + generate with injected context.",
    "Run a QLoRA fine-tune on Llama-3-8B using the unsloth library — compare outputs on 5 domain prompts before and after fine-tuning.",
  ],
  industry_context:
    "Brief optimized for an AI/ML engineer building production systems with LLMs and modern inference infrastructure.",
  // backward-compat fields
  news_insight: {
    title: "LLM Tool Calling Reshapes How Engineers Build Production AI Systems",
    summary:
      "Function calling in LLMs is production-critical infrastructure now, with major providers converging on a compatible protocol.",
    why_it_matters:
      "Engineers who master structured output and tool chains build more reliable pipelines.",
    sources: [],
  },
  perspectives: {
    common_themes: [
      "OpenAI, Anthropic, and Mistral now share a compatible tool-call schema.",
      "Reliability correlates with prompt clarity, not model size.",
      "Multi-step chains expose partial completions and silent schema mismatches.",
    ],
    synthesis:
      "Function calling infrastructure has matured to the point where multi-provider portability is practical and the reliability bar has shifted from model capability to prompt engineering discipline.",
    notable_tension: null,
  },
  learning_topics: [
    { title: "Function Calling & Tool Use", reason: "Protocol foundation.", difficulty: "beginner", category: "AI / ML" },
    { title: "RAG Pipeline Architecture", reason: "Dominant enterprise pattern.", difficulty: "intermediate", category: "AI / ML" },
    { title: "LoRA & Fine-Tuning", reason: "Custom model adaptation.", difficulty: "intermediate", category: "AI / ML" },
    { title: "Speculative Decoding", reason: "Inference optimization.", difficulty: "advanced", category: "AI / ML" },
  ],
  next_step:
    "Implement a minimal tool-use loop with the OpenAI function calling API — define 2 tools, verify schema compliance, handle edge cases in < 100 lines.",
}
