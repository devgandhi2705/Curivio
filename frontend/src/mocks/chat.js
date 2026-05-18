/**
 * Mock responses for the chat API.
 * selectMockResponse picks a template based on keywords in the message.
 */

export const MOCK_CHAT_DEFAULT = {
  session_id: "mock-session",
  message_id: 1,
  response: `**Vector databases** store and retrieve data as high-dimensional vectors — numerical representations of content (text, images, audio) produced by embedding models.

Key concepts:
- **Embeddings** — dense float vectors capturing semantic meaning
- **Approximate Nearest Neighbor (ANN)** — fast similarity search at scale
- **HNSW** — a popular graph-based ANN index used by Qdrant, Weaviate, etc.

**Why they matter for AI:** LLMs have fixed context windows, so vector DBs serve as external long-term memory. You embed your documents, store the vectors, then at query time retrieve the most relevant chunks to include in the prompt — this is the core of RAG (Retrieval-Augmented Generation).

Popular options: **Pinecone** (managed), **Qdrant** (open-source, fast), **Weaviate** (graph-aware), **ChromaDB** (local-first, great for prototyping).`,
  topic_hint: "Vector Databases",
  action: null,
  recommendations: {
    based_on_topic: "Vector Databases",
    source: "stored",
    next_topics: [
      { topic: "RAG Pipelines", reason: "Natural next step — combines vector search with LLM generation" },
      { topic: "Semantic Search", reason: "Core use case that motivates vector databases" },
    ],
    prerequisites: [
      { topic: "Embeddings", reason: "You need embeddings to populate a vector store" },
    ],
    advanced_topics: [
      { topic: "HNSW Index Internals", reason: "Understanding the algorithm helps tune performance" },
      { topic: "Hybrid Search", reason: "Combines dense and sparse retrieval for better recall" },
    ],
  },
  context_used: {
    has_deep_research: true,
    has_learning_path: true,
    has_topic_expansion: true,
    has_github_repos: false,
    interests_count: 3,
    history_turns: 0,
  },
  created_at: new Date().toISOString(),
}

export const MOCK_CHAT_ROADMAP = {
  session_id: "mock-session",
  message_id: 2,
  response: `Here's a structured learning roadmap for **Machine Learning**:

**Stage 1 — Foundations (2–4 weeks)**
- Python proficiency (NumPy, Pandas)
- Linear algebra essentials: matrices, dot products, eigenvalues
- Probability & statistics: distributions, Bayes' theorem, MLE

**Stage 2 — Core ML (4–6 weeks)**
- Supervised learning: linear/logistic regression, decision trees, SVMs
- Unsupervised learning: k-means, PCA, DBSCAN
- Model evaluation: cross-validation, precision/recall, AUC-ROC

**Stage 3 — Deep Learning (6–8 weeks)**
- Neural network fundamentals: backprop, activations, optimizers
- CNNs for vision, RNNs/LSTMs for sequences
- Transformers and attention mechanisms

**Stage 4 — Practical Skills**
- Experiment tracking (MLflow, W&B)
- Model deployment (FastAPI, Docker, cloud serving)
- MLOps fundamentals

Recommended starting point: **fast.ai Practical Deep Learning** — top-down approach that gets you building real models fast.`,
  topic_hint: "Machine Learning",
  action: "learning_roadmap",
  recommendations: {
    based_on_topic: "Machine Learning",
    source: "stored",
    next_topics: [
      { topic: "Deep Learning", reason: "Natural progression after ML fundamentals" },
      { topic: "MLOps", reason: "Needed to deploy and maintain models in production" },
    ],
    prerequisites: [],
    advanced_topics: [
      { topic: "Reinforcement Learning", reason: "Extends supervised learning to sequential decision making" },
    ],
  },
  context_used: {
    has_deep_research: false,
    has_learning_path: true,
    has_topic_expansion: true,
    has_github_repos: false,
    interests_count: 2,
    history_turns: 1,
  },
  created_at: new Date().toISOString(),
}

export const MOCK_CHAT_REPOS = {
  session_id: "mock-session",
  message_id: 3,
  response: `Here are well-regarded GitHub repositories for learning **transformers** and **attention mechanisms**:

**Foundational implementations**
- \`karpathy/minGPT\` — clean, minimal GPT in ~300 lines of PyTorch. Best for understanding the architecture.
- \`karpathy/nanoGPT\` — production-ready successor, trains real models fast.
- \`jalammar/illustrated-transformer\` — not runnable code, but the visual explainer that everyone links.

**Production libraries**
- \`huggingface/transformers\` — the definitive library. 100k+ stars, every major model.
- \`facebookresearch/fairseq\` — Facebook's sequence modeling toolkit, good for research.

**Learning-focused**
- \`harvardnlp/annotated-transformer\` — the original "Attention Is All You Need" paper with line-by-line annotation.
- \`lucidrains/x-transformers\` — highly modular, great for experimenting with variants.

Start with **minGPT** if you want to understand the mechanics — it's deliberately minimal so nothing hides the core ideas.`,
  topic_hint: "Transformers",
  action: "show_repos",
  recommendations: {
    based_on_topic: "Transformers",
    source: "stored",
    next_topics: [
      { topic: "Fine-tuning LLMs", reason: "Apply transformer knowledge to adapt pretrained models" },
    ],
    prerequisites: [
      { topic: "Attention Mechanism", reason: "Core building block of all transformer architectures" },
    ],
    advanced_topics: [
      { topic: "Flash Attention", reason: "Memory-efficient attention used in modern LLMs" },
      { topic: "Mixture of Experts", reason: "Architecture powering GPT-4 and Mixtral" },
    ],
  },
  context_used: {
    has_deep_research: true,
    has_learning_path: false,
    has_topic_expansion: true,
    has_github_repos: true,
    interests_count: 4,
    history_turns: 2,
  },
  created_at: new Date().toISOString(),
}

export const MOCK_CHAT_COMPARE = {
  session_id: "mock-session",
  message_id: 4,
  response: `**PyTorch vs TensorFlow** — a practical comparison:

| | PyTorch | TensorFlow |
|---|---|---|
| **Paradigm** | Define-by-run (dynamic) | Both static + eager |
| **Debugging** | Standard Python debugger | More complex |
| **Research use** | Dominant (>80% of papers) | Less common now |
| **Production** | TorchServe, ONNX export | TF Serving, TFLite |
| **Mobile/edge** | PyTorch Mobile | TFLite (more mature) |

**When to choose PyTorch:**
- Research, experimentation, custom architectures
- You want readable, Pythonic code
- Working with Hugging Face ecosystem

**When to choose TensorFlow:**
- Mobile or edge deployment (TFLite is very mature)
- Existing team/codebase in TF
- Need TF.js for browser-side ML

**Verdict for learning:** Start with **PyTorch**. The research community has largely converged on it, Hugging Face uses it by default, and the mental model (tensors as NumPy arrays with autograd) transfers cleanly.`,
  topic_hint: "Deep Learning Frameworks",
  action: "compare",
  recommendations: {
    based_on_topic: "Deep Learning Frameworks",
    source: "stored",
    next_topics: [
      { topic: "JAX", reason: "Growing alternative from Google with functional approach" },
      { topic: "ONNX", reason: "Framework-agnostic model export format" },
    ],
    prerequisites: [],
    advanced_topics: [
      { topic: "Custom CUDA Kernels", reason: "For when framework ops are the bottleneck" },
    ],
  },
  context_used: {
    has_deep_research: true,
    has_learning_path: false,
    has_topic_expansion: true,
    has_github_repos: false,
    interests_count: 3,
    history_turns: 1,
  },
  created_at: new Date().toISOString(),
}

const ROADMAP_KEYWORDS = /roadmap|learning path|where.*start|how.*learn|curriculum|syllabus/i
const REPOS_KEYWORDS   = /repos?|github|implement|code|example|show me/i
const COMPARE_KEYWORDS = /compare|vs\.?|versus|difference|better|which.*should/i

export function selectMockResponse(message, sessionId) {
  const base = COMPARE_KEYWORDS.test(message)
    ? MOCK_CHAT_COMPARE
    : ROADMAP_KEYWORDS.test(message)
    ? MOCK_CHAT_ROADMAP
    : REPOS_KEYWORDS.test(message)
    ? MOCK_CHAT_REPOS
    : MOCK_CHAT_DEFAULT

  return { ...base, session_id: sessionId, created_at: new Date().toISOString() }
}
