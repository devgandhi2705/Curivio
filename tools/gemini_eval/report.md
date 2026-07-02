# Gemini Model Evaluation Report

Generated: 2026-06-26 19:18 UTC

Models: gemini-2.5-flash · gemini-3.5-flash · gemini-3.1-flash-lite  
Cases 1–7 scored. Case 8 qualitative only.

## Summary Table

| Model | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | Avg C1–C7 |
|---|---|---|---|---|---|---|---|---|---|
| gemini-2.5-flash | 81.2% | 100.0% | 93.8% | 100.0% | 100.0% | 100.0% | 100.0% | *diag* | 96.4% |
| gemini-3.5-flash | Q | 0.0% | 100.0% | 93.8% | 93.8% | 87.5% | … | *diag* | 75.0% |
| gemini-3.1-flash-lite | 75.0% | 100.0% | 93.8% | 93.8% | 93.8% | 87.5% | 87.5% | *diag* | 90.2% |

---

## Per-Case Detail

### Case 1: DSA for interviews

**Prompt:** _Teach me data structures and algorithms from scratch, I want to be ready for technical interviews._

**Expected shape:** `fixed_sequence`  
**Checklist:** Big-O / complexity analysis, arrays & strings, recursion, sorting algorithms, linked lists, stacks & queues, hashing / hash tables, trees (incl. BST), graphs (BFS/DFS), dynamic programming


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 16639ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Learning Data Structures and Algorithms from scratch with the goal of technical interviews is a progressive subject with a defined set of core concepts and problem-solving techniques that lead to a tangible skill endpoint.",
  "days": [
    {
      "day_number": 1,
      "focus": "Introduction to Data Structures and Algorithms, their importance in software engineering and technical interviews.",
      "display_title": "Welcome to DSA: Your Interview Prep Journey Starts Here",
      "frame_hint": "timeline",
      "rationale": "Sets the stage and explains the 'why' behind learning DSA, motivating the learner for the journey ahead."
    },
    {
      "day_number": 2,
      "focus": "Understanding Time Complexity, introducing Big O notation (O(1), O(log n), O(n)).",
      "display_title": "Demystifying Big O: Understanding Time Complexity",
      "frame_hint": "timeline",
      "rationale": "Big O is fundamental for evaluating algorithm efficiency and is a core concept that underpins all subsequent algorithm discussions."
    },
    {
      "day_number": 3,
      "focus": "Deeper dive into Big O: Space Complexity, average/worst/best case analysis, common time complexities (O(n log n), O(n^2), O(2^n)).",
      "display_title": "Beyond Time: Space Complexity & Real-World Big O",
      "frame_hint": "timeline",
      "rationale": "Completes the foundational understanding of algorithm analysis before introducing specific data structures."
    },
    {
      "day_number": 4,
      "focus": "Arrays: Definition, characteristics, operations (access, insertion, deletion), static vs. dynamic arrays.",
      "display_title": "Mastering Arrays: The Foundation of Data Storage",
      "frame_hint": "timeline",
      "rationale": "Arrays are the most basic and widely used data structure, essential for building more complex structures and algorithms."
    },
    {
      "day_number": 5,
      "focus": "Array-based problem-solving: implementing common array operations, basic search/manipulation problems (e.g., finding max/min, reversing, two-pointers concept).",
      "display_title": "Array Adventures: Solving Your First Coding Problems",
      "frame_hint": "timeline",
      "rationale": "Applies theoretical knowledge to practical coding problems, reinforcing understanding of array properties and problem-solving techniques."
    },
    {
      "day_number": 6,
      "focus": "Linked Lists: Introduction, types (singly), nodes, pointers, advantages over arrays.",
      "display_title": "Introduction to Linked Lists: A Flexible Alternative",
      "frame_hint": "timeline",
      "rationale": "Introduces the second fundamental data structure, highlighting its differences and use cases compared to arrays."
    },
    {
      "day_number": 7,
      "focus": "Linked Lists operations: Traversal, insertion at head/tail/middle, deletion.",
      "display_title": "Navigating Linked Lists: Operations and Manipulation",
      "frame_hint": "timeline",
      "rationale": "Builds practical skills for manipulating linked lists, crucial for solving more advanced problems."
    },
    {
      "day_number": 8,
      "focus": "Linked List problem-solving: reversing a linked list, finding middle element, cycle detection (basic).",
      "display_title": "Linked List Challenges: Sharpen Your Pointer Skills",
      "frame_hint": "timeline",
      "rationale": "Reinforces linked list concepts through common interview-style problems, enhancing practical application."
    },
    {
      "day_number": 9,
      "focus": "Recursion: Concept, base case, recursive step, call stack visualization.",
      "display_title": "Unraveling Recursion: Thinking in Self-Referential Steps",
      "frame_hint": "timeline",
      "rationale": "Introduces a powerful algorithmic paradigm used extensively in tree, graph, and dynamic programming problems."
    },
    {
      "day_number": 10,
      "focus": "Recursion practice: Fibonacci sequence, factorial, tower of Hanoi (conceptual), debugging recursive calls.",
      "display_title": "Recursive Puzzles: Applying the Power of Self-Calls",
      "frame_hint": "timeline",
      "rationale": "Solidifies understanding of recursion with classic examples and prepares for its application in more complex data structures and algorithms."
    }
  ]
}
```

**Normalized score: 81.2%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='fixed_sequence', expected='fixed_sequence' |
| coverage_completeness | 2/3 | The plan covers most of the checklist items but misses or stops short on several key areas such as stacks & queues, hashing / hash tables, trees (incl. BST), graphs (BFS/DFS), and dynamic programming. — Hit: ['Big-O / complexity analysis', 'arrays & strings', 'recursion', 'linked |
| sequencing_soundness | 3/3 | Each concept builds logically on prior ones, introducing foundational concepts before moving on to more complex data structures and algorithms. |
| theme_distinctiveness | N/A | fixed_sequence |
| source_quality | N/A | fixed_sequence |
| frame_hint_variety | 1/3 | Distinct frame_hint values (1): ['timeline'] |
| user_facing_polish | 2/2 | The display_title fields are natural and engaging, making the content more approachable for learners. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** skipped-quota-exhausted  |  **Latency:** —ms  *(retried)*

*Quota exhausted — no output available.*


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 5811ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Data structures and algorithms have a defined set of core concepts that can be mastered sequentially to achieve interview readiness.",
  "days": [
    {
      "day_number": 1,
      "focus": "Big-O Notation and Time/Space Complexity",
      "display_title": "Understanding Algorithmic Efficiency",
      "frame_hint": "timeline",
      "rationale": "Essential foundation to analyze and compare the performance of future data structures."
    },
    {
      "day_number": 2,
      "focus": "Arrays and Dynamic Arrays (ArrayLists)",
      "display_title": "Foundational Linear Structures",
      "frame_hint": "timeline",
      "rationale": "The most fundamental memory structures; needed to understand indexing and memory layout."
    },
    {
      "day_number": 3,
      "focus": "Linked Lists (Singly and Doubly)",
      "display_title": "Pointers and Nodes",
      "frame_hint": "timeline",
      "rationale": "Introduces non-contiguous memory management and pointer manipulation."
    },
    {
      "day_number": 4,
      "focus": "Stacks and Queues",
      "display_title": "LIFO vs FIFO Operations",
      "frame_hint": "timeline",
      "rationale": "Standard abstract data types built on top of linear structures."
    },
    {
      "day_number": 5,
      "focus": "Hash Tables and Hash Functions",
      "display_title": "Constant Time Lookups",
      "frame_hint": "timeline",
      "rationale": "The most important tool for optimizing search and storage operations."
    },
    {
      "day_number": 6,
      "focus": "Introduction to Binary Trees",
      "display_title": "Hierarchical Data Foundations",
      "frame_hint": "timeline",
      "rationale": "Shifts perspective from linear to branching structures."
    },
    {
      "day_number": 7,
      "focus": "Binary Search Trees (BST)",
      "display_title": "Efficient Searching and Sorting",
      "frame_hint": "timeline",
      "rationale": "Building on trees to maintain order and facilitate logarithmic search."
    },
    {
      "day_number": 8,
      "focus": "Recursion Fundamentals",
      "display_title": "Thinking Recursively",
      "frame_hint": "timeline",
      "rationale": "Prerequisite logic for effectively traversing trees and graphs."
    },
    {
      "day_number": 9,
      "focus": "Sorting Algorithms (Merge Sort, Quick Sort)",
      "display_title": "Divide and Conquer",
      "frame_hint": "timeline",
      "rationale": "Classic algorithms that illustrate optimal search and arrangement strategies."
    },
    {
      "day_number": 10,
      "focus": "Binary Search Algorithm",
      "display_title": "Searching Sorted Arrays",
      "frame_hint": "timeline",
      "rationale": "Puts algorithmic logic into practice to solve search problems efficiently."
    }
  ]
}
```

**Normalized score: 75.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='fixed_sequence', expected='fixed_sequence' |
| coverage_completeness | 2/3 | The plan covers most of the checklist items but misses 'graphs (BFS/DFS)' and 'dynamic programming'. — Hit: ['Big-O / complexity analysis', 'arrays & strings', 'linked lists', 'stacks & queues', 'hashing / hash tables', 'trees (incl. BST)', 'recursion', 'sorting algorithms']; Mis |
| sequencing_soundness | 2/3 | The plan introduces concepts in a mostly logical order, but recursion is introduced after trees, which could be considered a minor slip since recursion is often used to traverse trees. |
| theme_distinctiveness | N/A | fixed_sequence |
| source_quality | N/A | fixed_sequence |
| frame_hint_variety | 1/3 | Distinct frame_hint values (1): ['timeline'] |
| user_facing_polish | 2/2 | The display titles are natural and engaging, making the plan easy to follow for a user. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 2: Immune system & vaccines

**Prompt:** _Explain how the human immune system works, from the basics to how vaccines train it._

**Expected shape:** `fixed_sequence`  
**Checklist:** innate immunity, adaptive immunity, lymphocytes (T cells / B cells), antibodies / antigens, immune memory, how vaccines work, real disease / application example


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 13281ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Understanding the human immune system, from basic components to the function of vaccines, is a subject with a clear, learnable progression and a defined endpoint for foundational mastery.",
  "days": [
    {
      "day_number": 1,
      "focus": "Definition and purpose of the immune system; overview of its main components and functions.",
      "display_title": "Welcome to Your Body's Defense: An Introduction to the Immune System",
      "frame_hint": "timeline",
      "rationale": "Establishes a foundational understanding and context for the entire journey, defining what the immune system is and why it's crucial."
    },
    {
      "day_number": 2,
      "focus": "Differentiating between innate and adaptive immunity, highlighting their key characteristics and roles.",
      "display_title": "Two Branches of Defense: Innate vs. Adaptive Immunity",
      "frame_hint": "comparison",
      "rationale": "Introduces the two principal divisions of the immune system, providing a high-level conceptual framework for subsequent detailed learning."
    },
    {
      "day_number": 3,
      "focus": "Exploring the physical and chemical barriers (skin, mucous membranes, pH, beneficial microbes) as the body's first line of defense.",
      "display_title": "Your Body's Shield: Physical and Chemical Barriers",
      "frame_hint": "timeline",
      "rationale": "Begins the detailed exploration of innate immunity by covering the immediate, non-cellular defenses that pathogens encounter first."
    },
    {
      "day_number": 4,
      "focus": "Identifying and describing the main cells of the innate immune system: phagocytes (macrophages, neutrophils), natural killer (NK) cells, mast cells, and dendritic cells (as initial detectors).",
      "display_title": "The Patrol Squad: Cells of Innate Immunity",
      "frame_hint": "single-discovery-story",
      "rationale": "Details the cellular components responsible for the immediate, non-specific responses characteristic of innate immunity."
    },
    {
      "day_number": 5,
      "focus": "Understanding the process, signs (redness, heat, swelling, pain), and molecular mediators of the inflammatory response, and its purpose in healing and pathogen containment.",
      "display_title": "Fire Alarm! Understanding the Inflammatory Response",
      "frame_hint": "timeline",
      "rationale": "Explains a critical, integrated process of innate immunity that coordinates defense and repair at the site of injury or infection."
    },
    {
      "day_number": 6,
      "focus": "Introducing the key characteristics of adaptive immunity (specificity, memory) and the primary lymphocytes: B cells and T cells.",
      "display_title": "The Specialized Forces: Introduction to Adaptive Immunity",
      "frame_hint": "timeline",
      "rationale": "Marks the transition from innate to adaptive immunity, introducing the specialized cells that provide a highly targeted and long-lasting defense."
    },
    {
      "day_number": 7,
      "focus": "Understanding B cell development, the structure and diverse functions of antibodies (neutralization, opsonization, complement activation), and the concept of humoral immunity.",
      "display_title": "Antibody Army: How B Cells Drive Humoral Immunity",
      "frame_hint": "single-discovery-story",
      "rationale": "Focuses on the B lymphocyte arm of adaptive immunity, detailing how antibodies are produced and their critical roles in pathogen clearance."
    },
    {
      "day_number": 8,
      "focus": "Exploring Helper T cell types, their recognition of antigens presented on MHC Class II molecules, activation pathways, and their role in orchestrating broader immune responses through cytokines.",
      "display_title": "The Command Center: Helper T Cells and Their Role",
      "frame_hint": "timeline",
      "rationale": "Explains the central role of Helper T cells as coordinators of both humoral and cell-mediated immunity, crucial for an effective adaptive response."
    },
    {
      "day_number": 9,
      "focus": "Understanding Cytotoxic T lymphocyte (CTL) function, their recognition of antigens on MHC Class I molecules, and how they directly eliminate infected or cancerous cells.",
      "display_title": "The Hit Squad: Cytotoxic T Cells and Direct Cell Killing",
      "frame_hint": "single-discovery-story",
      "rationale": "Details the direct cellular killing mechanism of adaptive immunity, providing insight into how the body clears intracellular pathogens and abnormal cells."
    },
    {
      "day_number": 10,
      "focus": "Explaining the formation of memory B and T cells, the characteristics of the secondary immune response (faster, stronger), and the fundamental importance of immunological memory for long-term protection.",
      "display_title": "Learning from Experience: The Power of Immunological Memory",
      "frame_hint": "timeline",
      "rationale": "Consolidates the concept of immunological memory, which is a hallmark of adaptive immunity and lays the groundwork for understanding vaccine efficacy."
    }
  ]
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='fixed_sequence', expected='fixed_sequence' |
| coverage_completeness | 3/3 | The plan comprehensively covers all checklist items, including innate immunity, adaptive immunity, lymphocytes, antibodies/antigens, immune memory, and how vaccines work, with a clear progression to a natural endpoint. — Hit: ['innate immunity', 'adaptive immunity', 'lymphocytes  |
| sequencing_soundness | 3/3 | Each concept builds logically on prior ones, with no skipped prerequisites, demonstrating a sound and coherent sequence. |
| theme_distinctiveness | N/A | fixed_sequence |
| source_quality | N/A | fixed_sequence |
| frame_hint_variety | 3/3 | Distinct frame_hint values (3): ['comparison', 'timeline', 'single-discovery-story'] |
| user_facing_polish | 2/2 | Display titles are natural, engaging, and clearly convey the focus of each day, making the learning journey appealing and easy to follow. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** done  |  **Latency:** 15500ms

*Output present but JSON parse failed. Raw (first 300 chars):*
```
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "The human immune system has a structured, fundamental blueprint that can be fully comprehended through a sequential progression from basic physical barriers to complex adaptive memory and clinical vaccines.",
  "days": [
    {
      "
```

**Normalized score: 0.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 0/3 | output shape='', expected='fixed_sequence' |
| coverage_completeness | N/A | No output |
| sequencing_soundness | N/A | No output |
| theme_distinctiveness | N/A | No output |
| source_quality | N/A | No output |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | N/A | No output |
| technical_reliability | 0/2 | JSON parse failed |


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 3781ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "The immune system is a biological system with established core mechanisms and functions that can be mapped from innate basics to complex adaptive responses and medical interventions.",
  "days": [
    {
      "day_number": 1,
      "focus": "Barriers and the innate immune system overview",
      "display_title": "The First Line of Defense",
      "frame_hint": "timeline",
      "rationale": "Starting with innate immunity provides the necessary foundational context before moving to specialized cells."
    },
    {
      "day_number": 2,
      "focus": "White blood cell types and their roles",
      "display_title": "The Cellular Infantry",
      "frame_hint": "comparison",
      "rationale": "Identifying the specific actors is required to understand how they interact in later stages."
    },
    {
      "day_number": 3,
      "focus": "Inflammation as a signaling mechanism",
      "display_title": "The Alarm System",
      "frame_hint": "single-discovery-story",
      "rationale": "Explaining inflammation bridges the gap between surface barriers and systemic response."
    },
    {
      "day_number": 4,
      "focus": "Introduction to the adaptive immune system",
      "display_title": "Beyond the Basics",
      "frame_hint": "timeline",
      "rationale": "Shifting the focus to the system's ability to learn and adapt is the logical next step."
    },
    {
      "day_number": 5,
      "focus": "Function of B-cells and antibodies",
      "display_title": "The Precision Attack",
      "frame_hint": "comparison",
      "rationale": "B-cells and antibodies are central to the adaptive response; they need dedicated exploration."
    },
    {
      "day_number": 6,
      "focus": "T-cells and cellular immunity",
      "display_title": "The Targeted Hunters",
      "frame_hint": "comparison",
      "rationale": "T-cells function differently than B-cells; contrasting them clarifies their specific duties."
    },
    {
      "day_number": 7,
      "focus": "Immunological memory and lifelong protection",
      "display_title": "The Body's Library",
      "frame_hint": "single-discovery-story",
      "rationale": "Explaining memory helps the learner understand how immunity lasts after an initial infection."
    },
    {
      "day_number": 8,
      "focus": "Principles of vaccination and exposure",
      "display_title": "Training the Troops",
      "frame_hint": "timeline",
      "rationale": "Applying the learned concepts of memory and adaptation to how vaccines actually work."
    },
    {
      "day_number": 9,
      "focus": "Autoimmunity and system dysfunction",
      "display_title": "When the Shield Breaks",
      "frame_hint": "single-discovery-story",
      "rationale": "Exploring when the system fails provides deeper appreciation for how it functions when healthy."
    },
    {
      "day_number": 10,
      "focus": "Review of the immune lifecycle",
      "display_title": "The Orchestrated Defense",
      "frame_hint": "timeline",
      "rationale": "Synthesizing all parts of the journey into a cohesive understanding of human immunity."
    }
  ]
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='fixed_sequence', expected='fixed_sequence' |
| coverage_completeness | 3/3 | The plan comprehensively covers all checklist items from innate immunity to how vaccines work, including real disease/application examples through the discussion of immune system components and functions. — Hit: ['innate immunity', 'adaptive immunity', 'lymphocytes (T cells / B c |
| sequencing_soundness | 3/3 | Each day's focus logically builds upon the previous, starting with barriers and innate immunity, progressing through white blood cells, inflammation, and into adaptive immunity, covering T and B cells, antibodies, immune memory, and finally vaccines, demonstrating a coherent and  |
| theme_distinctiveness | N/A | fixed_sequence |
| source_quality | N/A | fixed_sequence |
| frame_hint_variety | 3/3 | Distinct frame_hint values (3): ['comparison', 'timeline', 'single-discovery-story'] |
| user_facing_polish | 2/2 | Display titles such as 'The First Line of Defense', 'The Cellular Infantry', and 'The Orchestrated Defense' are natural and engaging, suggesting a well-considered user experience. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 3: Startup funding & VC

**Prompt:** _I want to stay updated on startup funding, venture capital, and the startup ecosystem._

**Expected shape:** `rotating_theme`  
**Checklist:** funding rounds / VC activity, M&A / exits, founder stories, specific verticals, macro conditions


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 6608ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The startup funding and venture capital landscape is constantly evolving with new deals, fund formations, market trends, and policy changes, making 'staying updated' the primary goal rather than reaching a fixed learning endpoint.",
  "themes": [
    {
      "name": "Recent Funding Rounds & Exits",
      "description": "Tracking significant seed, Series A-Z funding rounds, M&A activities, and IPOs across various sectors."
    },
    {
      "name": "Venture Capital Landscape",
      "description": "Insights into new VC funds, changes in investment theses, LP commitments, and prominent investor moves."
    },
    {
      "name": "Startup Ecosystem Trends & Policy",
      "description": "Analysis of emerging startup sectors, macroeconomic impacts, regional shifts, and relevant regulatory developments."
    },
    {
      "name": "Founder & Investor Perspectives",
      "description": "Key takeaways from interviews, founder stories, investor analyses, and strategic advice from industry leaders."
    }
  ],
  "trusted_sources": [
    "techcrunch.com",
    "axios.com/pro",
    "sifted.eu",
    "wallstreetjournal.com",
    "fortune.com/venture"
  ],
  "display_summary": "Currently tracking: Latest Funding Rounds, VC Landscape, Ecosystem Trends, and Founder/Investor Perspectives."
}
```

**Normalized score: 93.8%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers most of the checklist items including funding rounds, M&A/exits, founder stories, and macro conditions, with only 'specific verticals' not explicitly mentioned. — Hit: ['funding rounds / VC activity', 'M&A / exits', 'founder stories', 'macro conditions']; Missed:  |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | The themes are distinct and jointly cover the domain, including recent funding rounds, venture capital landscape, ecosystem trends, and founder/investor perspectives. |
| source_quality | 2/3 | The trusted sources include some domain-specific outlets like techcrunch.com but also more general ones like wallstreetjournal.com and fortune.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging, providing a clear overview of the current focus areas. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** done  |  **Latency:** 10530ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The venture capital and startup ecosystem is continuously evolving with new deals, shifting macroeconomic factors, and regulatory changes, making it an ongoing tracking effort rather than a finite curriculum.",
  "themes": [
    {
      "name": "VC Macro Trends & Fundraises",
      "description": "Analysis of venture capital fund-raising, dry powder levels, shifting valuation multiples, and broader ecosystem health."
    },
    {
      "name": "Early-Stage Activity (Seed & Series A)",
      "description": "Tracking emerging sectors, innovative seed-stage deals, and strategic narratives behind successful early raises."
    },
    {
      "name": "Late-Stage & Exits (M&A/IPOs)",
      "description": "Monitoring mega-rounds, strategic corporate acquisitions, IPO windows, and liquidity events."
    },
    {
      "name": "Deal Structuring & Founder Strategies",
      "description": "Deconstructing term sheets, governance shifts, down-round strategies, and founder negotiation tactics in the current market."
    }
  ],
  "trusted_sources": [
    "techcrunch.com",
    "pitchbook.com",
    "crunchbase.com",
    "strictlyvc.com",
    "theprime.vc",
    "venturebeat.com"
  ],
  "display_summary": "Currently tracking: VC Macro Trends, Early-Stage Deals, Late-Stage Exits, and Deal Structuring Strategies"
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers most checklist items including funding rounds, M&A/exits, and specific verticals through its themes. — Hit: ['funding rounds / VC activity', 'M&A / exits', 'specific verticals']; Missed: ['founder stories', 'macro conditions'] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct, covering VC macro trends, early-stage activity, late-stage exits, and deal structuring strategies, jointly covering the domain. |
| source_quality | 3/3 | Trusted sources include domain-specific outlets like techcrunch.com, pitchbook.com, and crunchbase.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally, providing a clear overview of the tracked topics. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 2422ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "Venture capital and startup markets are dynamic, cyclical, and driven by real-time macroeconomic shifts, meaning there is no final state of knowledge to achieve.",
  "themes": [
    {
      "name": "Market Sentiment & Macro",
      "description": "Analyzing interest rate impacts, dry powder availability, and valuation trends."
    },
    {
      "name": "The Founder's Playbook",
      "description": "Strategies for pitching, cap table management, and navigating dilution."
    },
    {
      "name": "M&A and Liquidity Events",
      "description": "Tracking exits, secondary markets, and the current landscape for IPOs."
    },
    {
      "name": "Investor Thesis Shifts",
      "description": "Understanding what VCs are prioritizing in their current investment mandates."
    }
  ],
  "trusted_sources": [
    "techcrunch.com",
    "pitchbook.com",
    "axios.com/pro/deals",
    "theinformation.com",
    "crunchbase.com/news"
  ],
  "display_summary": "Currently tracking: Macro market shifts, founder fundraising strategies, exit environments, and evolving VC investment theses."
}
```

**Normalized score: 93.8%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 2/3 | The plan covers most checklist items, including funding rounds/VC activity, M&A/exits, and macro conditions, but misses specific verticals and founder stories. — Hit: ['funding rounds / VC activity', 'M&A / exits', 'macro conditions']; Missed: ['founder stories', 'specific vertic |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | The themes are distinct and jointly cover the domain, including market sentiment, founder strategies, M&A and liquidity events, and investor thesis shifts. |
| source_quality | 3/3 | The trusted sources match the expected domain-specific outlets, including techcrunch.com, pitchbook.com, crunchbase.com, and theinformation.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 4: Pharma industry

**Prompt:** _Keep me updated on the pharmaceutical industry — drug approvals, clinical trials, and major deals._

**Expected shape:** `rotating_theme`  
**Checklist:** FDA / regulatory approvals, clinical trial results, M&A / licensing deals, pricing & policy, R&D breakthroughs


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 6437ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The pharmaceutical industry is dynamic, with continuous advancements in drug development, regulatory changes, and evolving market dynamics, meaning there's no fixed endpoint to being 'updated'.",
  "themes": [
    {
      "name": "Drug Approvals & Pipeline",
      "description": "Updates on new drug approvals (FDA, EMA), significant clinical trial results, and progress in the drug development pipeline."
    },
    {
      "name": "Pharma M&A and Deals",
      "description": "Coverage of major mergers, acquisitions, partnerships, and investment rounds within the pharmaceutical and biotech sectors."
    },
    {
      "name": "Regulatory & Policy Shifts",
      "description": "News on changes in drug pricing, patent law, healthcare policy, and other regulatory actions affecting the industry."
    },
    {
      "name": "Biotech Innovations & Trends",
      "description": "Emerging scientific breakthroughs, new therapeutic modalities, and significant trends in biotechnology."
    }
  ],
  "trusted_sources": [
    "fda.gov",
    "reuters.com",
    "fiercepharma.com",
    "endpointsnews.com",
    "clinicaltrials.gov"
  ],
  "display_summary": "Currently tracking: Drug Approvals & Pipeline, Pharma M&A and Deals, Regulatory & Policy Shifts, Biotech Innovations & Trends"
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers all checklist items including FDA approvals, clinical trial results, M&A deals, pricing and policy, and R&D breakthroughs. — Hit: ['FDA / regulatory approvals', 'clinical trial results', 'M&A / licensing deals', 'pricing & policy', 'R&D breakthroughs']; Missed: [] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | The themes are distinct and jointly cover the pharmaceutical industry domain, including drug approvals, M&A deals, regulatory shifts, and biotech innovations. |
| source_quality | 3/3 | The trusted sources include domain-specific outlets such as fda.gov, fiercepharma.com, and endpointsnews.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display summary reads naturally and is engaging, providing a clear overview of the current tracking themes. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** done  |  **Latency:** 9281ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The pharmaceutical landscape is continuously changing with ongoing drug approvals, clinical trials, and corporate deals, meaning it has no fixed endpoint and requires continuous monitoring.",
  "themes": [
    {
      "name": "Regulatory & FDA Approvals",
      "description": "Tracking FDA, EMA, and global agency approvals, Complete Response Letters (CRLs), advisory committee votes, and expanded indications."
    },
    {
      "name": "Clinical Trial Readouts",
      "description": "Analyzing newly released Phase I/II/III data, pipeline advancements, primary endpoint achievements, and patient safety readouts."
    },
    {
      "name": "Pharma M&A & Deals",
      "description": "Monitoring acquisitions, licensing deals, venture capital inflows, and strategic alliances shaping the biotech and pharma landscape."
    },
    {
      "name": "Pricing, Policy & Market Access",
      "description": "Following drug pricing legislation, patent cliffs, generic/biosimilar competition, and healthcare reimbursement policy updates."
    }
  ],
  "trusted_sources": [
    "fda.gov",
    "fiercepharma.com",
    "endpointsnews.com",
    "biopharmadive.com",
    "statnews.com",
    "reuters.com"
  ],
  "display_summary": "Currently tracking: Regulatory Decisions, Clinical Trials, M&A activity, and Biotech Policy & Pricing."
}
```

**Normalized score: 93.8%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 2/3 | The plan covers most checklist items but misses 'R&D breakthroughs'. — Hit: ['FDA / regulatory approvals', 'clinical trial results', 'M&A / licensing deals', 'pricing & policy']; Missed: ['R&D breakthroughs'] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the pharmaceutical industry domain. |
| source_quality | 3/3 | Trusted sources include domain-specific outlets like fda.gov, fiercepharma.com, and statnews.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display summary is natural and engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 2375ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The pharmaceutical industry is in a state of constant flux driven by R&D breakthroughs, shifting regulatory landscapes, and market consolidation, making it a continuous monitoring task rather than a finite curriculum.",
  "themes": [
    {
      "name": "FDA & Regulatory Hurdles",
      "description": "Monitoring new drug approvals, fast-track designations, and rejected applications."
    },
    {
      "name": "Clinical Pipeline Updates",
      "description": "Analyzing phase-gate outcomes and data readouts for late-stage clinical trials."
    },
    {
      "name": "Market Dynamics & M&A",
      "description": "Tracking strategic acquisitions, partnerships, and high-level corporate pharmaceutical shifts."
    },
    {
      "name": "Policy & Pricing",
      "description": "Keeping current on legislative changes, drug pricing negotiations, and healthcare access laws."
    }
  ],
  "trusted_sources": [
    "fiercepharma.com",
    "statnews.com",
    "fda.gov",
    "biopharmadive.com",
    "evaluate.com"
  ],
  "display_summary": "Currently tracking: Regulatory approvals, clinical trial readouts, industry consolidation, and pricing policy updates."
}
```

**Normalized score: 93.8%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 2/3 | The plan covers most checklist items but misses 'R&D breakthroughs'. — Hit: ['FDA / regulatory approvals', 'clinical trial results', 'M&A / licensing deals', 'pricing & policy']; Missed: ['R&D breakthroughs'] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the pharmaceutical industry domain. |
| source_quality | 3/3 | Trusted sources include domain-specific outlets like fiercepharma.com, statnews.com, and fda.gov. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 5: Latest AI trends

**Prompt:** _I want to learn about latest AI trends._

**Expected shape:** `rotating_theme`  
**Checklist:** model releases / research, industry / funding, regulation, enterprise adoption


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 8983ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The 'Latest AI Trends' is a continuously evolving subject with no fixed endpoint, requiring ongoing monitoring to stay current.",
  "themes": [
    {
      "name": "Model Advancements",
      "description": "New AI model releases, significant capability jumps, and benchmark achievements."
    },
    {
      "name": "Industry & Investment",
      "description": "Funding rounds, M&A activity, major partnerships, and market shifts in the AI industry."
    },
    {
      "name": "Policy & Ethics",
      "description": "Developments in AI regulation, governance frameworks, and ethical discussions."
    },
    {
      "name": "Applications & Products",
      "description": "Emerging AI-powered products, enterprise adoption, and novel use cases across sectors."
    }
  ],
  "trusted_sources": [
    "techcrunch.com",
    "reuters.com",
    "arxiv.org",
    "theverge.com",
    "bloomberg.com",
    "openai.com",
    "deepmind.google"
  ],
  "display_summary": "Currently tracking: Model Advancements, Industry & Investment, Policy & Ethics, and Applications & Products."
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers all checklist items including model releases/research, industry/funding, regulation, and enterprise adoption. — Hit: ['model releases / research', 'industry / funding', 'regulation', 'enterprise adoption']; Missed: [] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the domain of latest AI trends. |
| source_quality | 3/3 | Trusted sources include domain-specific outlets like arxiv.org and techcrunch.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** done  |  **Latency:** 6593ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The AI industry is evolving at an unprecedented pace with continuous model releases, shifting regulatory landscapes, and emerging business models, making it a field requiring ongoing tracking rather than a static curriculum.",
  "themes": [
    {
      "name": "Foundation Models & Capabilities",
      "description": "New LLM releases, multimodal breakthroughs, and benchmark performances."
    },
    {
      "name": "Enterprise Adoption & Business Strategy",
      "description": "How corporations are integrating AI, measuring ROI, and restructuring workflows."
    },
    {
      "name": "AI Infrastructure & Hardware",
      "description": "GPU constraints, custom silicon developments, and data center energy demands."
    },
    {
      "name": "Regulatory & Policy Landscape",
      "description": "Evolving legislation like the EU AI Act, copyright lawsuits, and safety standards."
    },
    {
      "name": "M&A, Funding & Partnerships",
      "description": "Venture capital trends, big tech acquisitions, and strategic ecosystem alliances."
    }
  ],
  "trusted_sources": [
    "venturebeat.com",
    "techcrunch.com",
    "bloomberg.com",
    "mckinsey.com",
    "stratechery.com",
    "reuters.com"
  ],
  "display_summary": "Currently tracking: Foundation Models, Enterprise ROI, Infrastructure Bottlenecks, AI Policy, and Ecosystem Funding."
}
```

**Normalized score: 93.8%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers all checklist items including model releases, industry and funding, regulation, and enterprise adoption. — Hit: ['model releases / research', 'industry / funding', 'regulation', 'enterprise adoption']; Missed: [] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the domain, including foundation models, enterprise adoption, AI infrastructure, regulatory landscape, and funding. |
| source_quality | 2/3 | Trusted sources include relevant outlets like venturebeat.com and techcrunch.com, but also more generic sources like bloomberg.com and reuters.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 4156ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "The rapid evolution of AI models, market dynamics, and shifting global regulations ensures that there is no final state of 'knowing,' only a continuous process of staying updated.",
  "themes": [
    {
      "name": "Model Benchmarks & Capability Shifts",
      "description": "Analyzing technical whitepapers and release notes to understand the shifting ceiling of foundation model performance."
    },
    {
      "name": "Corporate AI Strategy & Ecosystems",
      "description": "Tracking how major tech firms are integrating AI into business models, M&A activity, and strategic partnerships."
    },
    {
      "name": "Global AI Governance & Policy",
      "description": "Monitoring legislative updates, safety standards, and regional regulatory frameworks impacting implementation."
    },
    {
      "name": "Emerging AI Business Use-Cases",
      "description": "Identifying shifts from 'AI hype' to functional enterprise deployment patterns and ROI metrics."
    }
  ],
  "trusted_sources": [
    "arxiv.org",
    "theverge.com",
    "bloomberg.com",
    "deepmind.google/discover",
    "openai.com/news"
  ],
  "display_summary": "Currently tracking: Model Capabilities, Corporate Strategy, Global Policy, and Real-World Use-Cases."
}
```

**Normalized score: 93.8%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers all checklist items including model releases/research, industry/funding, regulation, and enterprise adoption. — Hit: ['model releases / research', 'industry / funding', 'regulation', 'enterprise adoption']; Missed: [] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the domain of latest AI trends. |
| source_quality | 2/3 | Trusted sources include arxiv.org, a domain-specific outlet, but also more general news sites like theverge.com and bloomberg.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 6: World news & current events

**Prompt:** _Help me stay informed about world news and current events._

**Expected shape:** `rotating_theme`  
**Checklist:** geopolitics, domestic politics / policy, economy / markets, one major ongoing global issue


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 8860ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "World news and current events are continuously unfolding, making 'staying current' an ongoing process rather than a fixed curriculum with an endpoint.",
  "themes": [
    {
      "name": "Geopolitics & Diplomacy",
      "description": "Major international conflicts, alliances, diplomatic efforts, and power shifts"
    },
    {
      "name": "Global Economy & Markets",
      "description": "Inflation, interest rates, trade agreements, energy markets, and financial stability"
    },
    {
      "name": "Major Domestic Politics",
      "description": "Elections, significant policy changes, and political stability in influential nations"
    },
    {
      "name": "Humanitarian & Social Issues",
      "description": "Major crises, human rights developments, global health concerns, and social movements"
    }
  ],
  "trusted_sources": [
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "nytimes.com",
    "ft.com"
  ],
  "display_summary": "Currently tracking: Geopolitics & Diplomacy, Global Economy & Markets, Major Domestic Politics, Humanitarian & Social Issues"
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 3/3 | The plan covers geopolitics, economy/markets, and domestic politics/policy, with humanitarian and social issues addressing a major ongoing global issue. — Hit: ['geopolitics', 'economy / markets', 'domestic politics / policy', 'one major ongoing global issue']; Missed: [] |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the domain of world news and current events. |
| source_quality | 3/3 | Trusted sources include domain-specific outlets like reuters.com, apnews.com, and bbc.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** done  |  **Latency:** 80688ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "World news and international affairs are constantly evolving; staying informed requires a structured, rotating analysis of critical global domains rather than a finite syllabus.",
  "themes": [
    {
      "name": "Geopolitics & Security",
      "description": "Tracking active conflicts, diplomatic negotiations, and shifts in international alliances."
    },
    {
      "name": "Global Economy & Trade",
      "description": "Monitoring trade disputes, central bank policies, supply chain changes, and global economic indicators."
    },
    {
      "name": "Climate & Resource Governance",
      "description": "Examining environmental policies, energy transitions, and resource scarcity challenges worldwide."
    },
    {
      "name": "Democratic Health & Elections",
      "description": "Following significant domestic elections, policy changes, and political movements in key sovereign nations."
    },
    {
      "name": "Transnational Technology & Society",
      "description": "Investigating global tech regulation, public health trends, and transnational human rights developments."
    }
  ],
  "trusted_sources": [
    "reuters.com",
    "apnews.com",
    "economist.com",
    "bloomberg.com",
    "foreignaffairs.com"
  ],
  "display_summary": "Currently tracking: Geopolitics & Security, Global Economy & Trade, Climate Governance, Democratic Health, and Transnational Tech."
}
```

**Normalized score: 87.5%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 2/3 | The plan covers geopolitics, economy/markets, and one major ongoing global issue (climate governance), but misses domestic politics/policy as a distinct theme, despite 'Democratic Health & Elections' partially addressing it. — Hit: ['geopolitics', 'economy / markets', 'one major  |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the domain of world news and current events, with minimal overlap. |
| source_quality | 2/3 | Trusted sources include domain-specific outlets like reuters.com and apnews.com, but also more specialized sources like economist.com and foreignaffairs.com, with no direct match to bbc.com. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging, providing a clear overview of the current focus areas. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 4921ms

**Raw output:**
```json
{
  "shape": "rotating_theme",
  "day_count": 14,
  "reasoning": "World news is a perpetual flow of unfolding events with no static end point, requiring constant synthesis of evolving geopolitical and economic dynamics.",
  "themes": [
    {
      "name": "Geopolitical Flashpoints",
      "description": "Monitoring active conflicts, territorial disputes, and shifting diplomatic alliances."
    },
    {
      "name": "Global Economic Indicators",
      "description": "Tracking inflation trends, central bank policies, and major trade agreements."
    },
    {
      "name": "International Governance",
      "description": "Following actions by the UN, EU, and other multi-lateral bodies impacting global law."
    },
    {
      "name": "Emerging Tech & Infrastructure",
      "description": "Developments in energy transitions, digital infrastructure, and cross-border policy."
    }
  ],
  "trusted_sources": [
    "reuters.com",
    "apnews.com",
    "economist.com",
    "foreignpolicy.com",
    "aljazeera.com"
  ],
  "display_summary": "Currently tracking: Geopolitical Flashpoints, Global Economic Indicators, International Governance, and Emerging Tech & Infrastructure."
}
```

**Normalized score: 87.5%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='rotating_theme', expected='rotating_theme' |
| coverage_completeness | 2/3 | The plan covers geopolitics and economy/markets, but misses domestic politics/policy and only touches on one major ongoing global issue indirectly through other themes. — Hit: ['geopolitics', 'economy / markets']; Missed: ['domestic politics / policy', 'one major ongoing global i |
| sequencing_soundness | N/A | rotating_theme |
| theme_distinctiveness | 3/3 | Themes are distinct and jointly cover the domain of world news and current events. |
| source_quality | 2/3 | Mostly relevant sources, but lacks bbc.com and includes foreignpolicy.com and aljazeera.com which are not in the expected list. |
| frame_hint_variety | N/A | rotating_theme — no day entries, frame_hint N/A |
| user_facing_polish | 2/2 | The display_summary field reads naturally and is engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 7: Chess beginner to intermediate

**Prompt:** _Teach me how to play chess, from beginner to a strong intermediate level._

**Expected shape:** `fixed_sequence`  
**Checklist:** piece movement / rules, opening principles, tactics (forks / pins / skewers), basic endgames, positional strategy, reviewing your own games


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 11171ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Learning chess from beginner to strong intermediate involves mastering a defined set of rules, strategies, and tactical patterns, making it a learnable and reachable subject with a clear endpoint.",
  "days": [
    {
      "day_number": 1,
      "focus": "Chessboard setup and individual piece movements (pawn, knight, bishop, rook, queen, king)",
      "display_title": "Understanding the Board & How Each Piece Moves",
      "frame_hint": "timeline",
      "rationale": "The absolute first step to playing chess is knowing how the pieces are set up and how they legally move."
    },
    {
      "day_number": 2,
      "focus": "Special chess moves: castling, en passant, pawn promotion; and the ultimate objective of the game (checkmate)",
      "display_title": "Special Moves & The Goal: Achieving Checkmate",
      "frame_hint": "timeline",
      "rationale": "Introduces crucial special rules and defines the game's objective, building upon basic movement knowledge."
    },
    {
      "day_number": 3,
      "focus": "Distinguishing between check, checkmate, and stalemate; identifying legal responses to check",
      "display_title": "Check, Checkmate, and Stalemate: Knowing the Game's Endings",
      "frame_hint": "timeline",
      "rationale": "Essential for understanding game termination conditions and avoiding illegal moves or missed wins/draws."
    },
    {
      "day_number": 4,
      "focus": "Relative value of chess pieces; simple exchanges and trading material effectively",
      "display_title": "The Value of Your Pieces: Making Smart Trades",
      "frame_hint": "comparison",
      "rationale": "Teaches fundamental decision-making regarding material, which is critical for evaluating positions and moves."
    },
    {
      "day_number": 5,
      "focus": "Introduction to basic tactical motifs: forks and pins, and how to identify them in simple positions",
      "display_title": "First Tactics: Uncovering Forks and Pins",
      "frame_hint": "single-discovery-story",
      "rationale": "Introduces the learner to their first practical attacking patterns, crucial for converting advantages."
    },
    {
      "day_number": 6,
      "focus": "Core opening principles: controlling the center, developing pieces, king safety (castling early)",
      "display_title": "Blueprint for Success: Core Opening Principles",
      "frame_hint": "timeline",
      "rationale": "Establishes a foundational understanding of how to begin a game effectively, preparing for the middlegame."
    },
    {
      "day_number": 7,
      "focus": "Exploring common basic opening sequences: Italian Game, Ruy Lopez (first few moves) and their underlying ideas",
      "display_title": "Your First Openings: Italian Game & Ruy Lopez",
      "frame_hint": "timeline",
      "rationale": "Provides concrete examples of applying opening principles, giving the learner a starting repertoire."
    },
    {
      "day_number": 8,
      "focus": "Basic endgame concepts: King and Rook vs. King checkmate patterns, the 'box' method",
      "display_title": "Winning Simple Endgames: King and Rook vs. King",
      "frame_hint": "single-discovery-story",
      "rationale": "Introduces the first concrete endgame technique, essential for converting material advantages into a win."
    },
    {
      "day_number": 9,
      "focus": "Introduction to positional play: understanding central control, space, and pawn structure basics",
      "display_title": "Beyond Tactics: Understanding Positional Play",
      "frame_hint": "timeline",
      "rationale": "Broadens the learner's perspective beyond just tactics, introducing the strategic elements of chess."
    },
    {
      "day_number": 10,
      "focus": "Reviewing one's own games: identifying mistakes, missed opportunities (tactical and strategic), and learning from them",
      "display_title": "Learning From Your Games: The Post-Mortem",
      "frame_hint": "single-discovery-story",
      "rationale": "Encourages self-improvement through critical analysis, a vital skill for progressing past the beginner stage."
    }
  ]
}
```

**Normalized score: 100.0%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='fixed_sequence', expected='fixed_sequence' |
| coverage_completeness | 3/3 | The plan covers all checklist items, including piece movement/rules, opening principles, tactics, basic endgames, positional strategy, and reviewing one's own games, reaching a natural endpoint. — Hit: ['piece movement / rules', 'opening principles', 'tactics (forks / pins / skew |
| sequencing_soundness | 3/3 | Each concept builds logically upon prior ones, with no prerequisite skipped, demonstrating a sound sequence. |
| theme_distinctiveness | N/A | fixed_sequence |
| source_quality | N/A | fixed_sequence |
| frame_hint_variety | 3/3 | Distinct frame_hint values (3): ['comparison', 'timeline', 'single-discovery-story'] |
| user_facing_polish | 2/2 | Display titles are natural and engaging, such as 'Understanding the Board & How Each Piece Moves' and 'Beyond Tactics: Understanding Positional Play'. |
| technical_reliability | 2/2 | Clean JSON, first try |


#### gemini-3.5-flash
- **Status:** pending  |  **Latency:** —ms

*Pending — not yet collected.*


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 3953ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Chess has a structured foundation of rules, tactics, and endgame principles that allow a beginner to build a measurable, logical progression toward intermediate proficiency.",
  "days": [
    {
      "day_number": 1,
      "focus": "Board setup and piece movement",
      "display_title": "The Arena and its Actors",
      "frame_hint": "timeline",
      "rationale": "Before playing, the learner must master how each piece moves and the board coordinate system."
    },
    {
      "day_number": 2,
      "focus": "Check, checkmate, and stalemate",
      "display_title": "Understanding the Win Condition",
      "frame_hint": "timeline",
      "rationale": "Understanding the difference between a win and a draw is essential for every decision made on the board."
    },
    {
      "day_number": 3,
      "focus": "Basic opening principles: central control and development",
      "display_title": "Building a Solid Foundation",
      "frame_hint": "timeline",
      "rationale": "Beginners often move pieces aimlessly; learning to prioritize the center sets up a stronger game."
    },
    {
      "day_number": 4,
      "focus": "Simple tactical motifs: forks and pins",
      "display_title": "The Art of the Double Attack",
      "frame_hint": "timeline",
      "rationale": "Tactics win games at the beginner level; recognizing forks and pins is the first step toward board vision."
    },
    {
      "day_number": 5,
      "focus": "King and Rook vs King endgame",
      "display_title": "The First Checkmate Pattern",
      "frame_hint": "timeline",
      "rationale": "Mastering the basic checkmate ensures the learner can convert a material advantage into a win."
    },
    {
      "day_number": 6,
      "focus": "Relative value of pieces and piece trades",
      "display_title": "Evaluating the Exchange",
      "frame_hint": "timeline",
      "rationale": "Learning why trading a knight for a bishop can be beneficial helps the learner stop blundering material."
    },
    {
      "day_number": 7,
      "focus": "King safety: castling and pawn structure",
      "display_title": "Protecting the Monarch",
      "frame_hint": "timeline",
      "rationale": "A king in the center is a vulnerability; castling early is a crucial transition from the opening to the middlegame."
    },
    {
      "day_number": 8,
      "focus": "Common beginner traps and opening pitfalls",
      "display_title": "Avoiding the Early Blunders",
      "frame_hint": "timeline",
      "rationale": "Awareness of Scholar's Mate and other traps prevents the learner from losing prematurely."
    },
    {
      "day_number": 9,
      "focus": "Introduction to positional thinking: weak squares",
      "display_title": "The Quiet Game",
      "frame_hint": "timeline",
      "rationale": "Introducing the idea that pieces have better and worse squares is the start of positional play."
    },
    {
      "day_number": 10,
      "focus": "Review of fundamental principles and first full-game analysis",
      "display_title": "Connecting the Dots",
      "frame_hint": "timeline",
      "rationale": "Synthesizing the first 9 days into a cohesive understanding of how a full game flows."
    }
  ]
}
```

**Normalized score: 87.5%**

| Dimension | Score | Evidence |
|---|---|---|
| shape_correctness | 3/3 | output shape='fixed_sequence', expected='fixed_sequence' |
| coverage_completeness | 3/3 | The plan covers all essential checklist items, including piece movement, opening principles, tactics, basic endgames, positional strategy, and reviewing games. — Hit: ['piece movement / rules', 'opening principles', 'tactics (forks / pins / skewers)', 'basic endgames', 'positiona |
| sequencing_soundness | 3/3 | Each concept builds logically on prior ones, with no noticeable gaps or prerequisite concepts skipped. |
| theme_distinctiveness | N/A | fixed_sequence |
| source_quality | N/A | fixed_sequence |
| frame_hint_variety | 1/3 | Distinct frame_hint values (1): ['timeline'] |
| user_facing_polish | 2/2 | Display titles, such as 'The Arena and its Actors' and 'The Quiet Game', are natural and engaging. |
| technical_reliability | 2/2 | Clean JSON, first try |


### Case 8: ML fundamentals + research (diagnostic)

**Prompt:** _I want to deeply understand machine learning fundamentals while also following the latest ML research as it happens._

**Type:** Diagnostic — ambiguity test. Not scored.


#### gemini-2.5-flash
- **Status:** done  |  **Latency:** 14610ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Machine Learning fundamentals represent a well-defined body of knowledge that can be systematically learned and mastered, providing a solid foundation for continuous research engagement.",
  "days": [
    {
      "day_number": 1,
      "focus": "Define Machine Learning, supervised vs unsupervised vs reinforcement learning, key applications and challenges.",
      "display_title": "What is Machine Learning? An Overview",
      "frame_hint": "timeline",
      "rationale": "Establish foundational understanding of ML definitions, categories, and real-world relevance as the starting point for the journey."
    },
    {
      "day_number": 2,
      "focus": "Linear Regression model, understanding the cost function (e.g., Mean Squared Error), and the Gradient Descent optimization algorithm.",
      "display_title": "Building Your First Model: Linear Regression",
      "frame_hint": "timeline",
      "rationale": "Introduce a simple, interpretable model to grasp core ML concepts like prediction, loss, and iterative optimization."
    },
    {
      "day_number": 3,
      "focus": "Logistic Regression for binary classification, the sigmoid activation function, decision boundaries, and cross-entropy loss.",
      "display_title": "From Regression to Classification: Logistic Regression",
      "frame_hint": "timeline",
      "rationale": "Extend the understanding of linear models to solve classification problems, a fundamental and widely used ML task."
    },
    {
      "day_number": 4,
      "focus": "Introduction to neural network architecture, from perceptrons to multi-layer perceptrons (MLPs), and common activation functions.",
      "display_title": "The Dawn of Neural Networks: From Perceptrons to MLPs",
      "frame_hint": "timeline",
      "rationale": "Introduce the basic building blocks of deep learning, setting the stage for understanding more complex network structures."
    },
    {
      "day_number": 5,
      "focus": "Detailed explanation of the backpropagation algorithm, including the chain rule, forward and backward passes, and weight updates.",
      "display_title": "How Neural Networks Learn: Understanding Backpropagation",
      "frame_hint": "timeline",
      "rationale": "Explain the fundamental algorithm that enables neural networks to efficiently learn from data and update their parameters."
    },
    {
      "day_number": 6,
      "focus": "High-level intuition and applications of Convolutional Neural Networks (CNNs) for image data and Recurrent Neural Networks (RNNs) for sequence data.",
      "display_title": "Diving Deeper: Specialized Architectures (CNNs & RNNs)",
      "frame_hint": "timeline",
      "rationale": "Provide an initial exposure to specialized deep learning architectures that are crucial for specific data types and tasks."
    },
    {
      "day_number": 7,
      "focus": "Understanding the bias-variance trade-off, identifying overfitting and underfitting, and regularization techniques (L1, L2, Dropout).",
      "display_title": "Navigating Model Challenges: Overfitting and Regularization",
      "frame_hint": "timeline",
      "rationale": "Address common pitfalls in model training and introduce critical methods to build robust and generalizable ML models."
    },
    {
      "day_number": 8,
      "focus": "Techniques for data cleaning, handling missing values, categorical encoding, feature scaling, and basic feature engineering.",
      "display_title": "Preparing Your Data: Preprocessing and Feature Engineering",
      "frame_hint": "timeline",
      "rationale": "Emphasize the critical importance of data quality and preparation, as these steps profoundly impact model performance."
    },
    {
      "day_number": 9,
      "focus": "Key evaluation metrics for classification (accuracy, precision, recall, F1-score, ROC-AUC) and regression (MAE, RMSE, R-squared).",
      "display_title": "Measuring Success: Key Evaluation Metrics",
      "frame_hint": "timeline",
      "rationale": "Equip the learner with the tools to properly assess, compare, and understand the performance of different ML models."
    },
    {
      "day_number": 10,
      "focus": "Overview of current ML research areas, how to find and interpret research papers (e.g., arXiv, top conferences), and prominent research labs.",
      "display_title": "Stepping into the Research World: How to Stay Current",
      "frame_hint": "timeline",
      "rationale": "Bridge the gap between fundamentals and the research frontier, guiding the learner on effective ways to engage with ongoing advancements."
    }
  ]
}
```

**Ambiguity handling:**
The model picked the 'fixed_sequence' shape cleanly, focusing on a systematic learning path for machine learning fundamentals. It did not explicitly blend both shapes or note the tension between the two intents. However, it attempted to address the 'rotating_theme' intent in the last day of the sequence, providing an overview of current research areas. The result is mostly coherent, but the 'fixed_sequence' shape reflects the stronger intent signal in the prompt for deeply understanding fundamentals.


#### gemini-3.5-flash
- **Status:** pending  |  **Latency:** —ms

*Pending — not yet collected.*


#### gemini-3.1-flash-lite
- **Status:** done  |  **Latency:** 3203ms

**Raw output:**
```json
{
  "shape": "fixed_sequence",
  "day_count": 10,
  "reasoning": "Machine learning fundamentals form a cohesive academic syllabus that transitions from linear algebra foundations to neural network architectures.",
  "days": [
    {
      "day_number": 1,
      "focus": "Mathematical foundations: Linear algebra, calculus, and probability for ML",
      "display_title": "The Mathematical Bedrock of ML",
      "frame_hint": "timeline",
      "rationale": "Establishes the quantitative literacy required to understand loss functions and gradients."
    },
    {
      "day_number": 2,
      "focus": "Supervised learning: Linear regression and logistic regression basics",
      "display_title": "Foundations of Supervised Learning",
      "frame_hint": "timeline",
      "rationale": "Provides the simplest context for understanding optimization and model training."
    },
    {
      "day_number": 3,
      "focus": "Optimization: Gradient descent and backpropagation",
      "display_title": "How Models Learn: Optimization",
      "frame_hint": "single-discovery-story",
      "rationale": "Moves from static models to the mechanism of iterative improvement."
    },
    {
      "day_number": 4,
      "focus": "Neural network architectures: Perceptrons and Multi-Layer Perceptrons",
      "display_title": "Building Blocks of Neural Networks",
      "frame_hint": "timeline",
      "rationale": "Introduces the structural complexity required for deep learning."
    },
    {
      "day_number": 5,
      "focus": "Regularization and generalization: Overfitting, underfitting, and bias-variance tradeoff",
      "display_title": "The Art of Generalization",
      "frame_hint": "comparison",
      "rationale": "Teaches the practical necessity of managing model performance on unseen data."
    },
    {
      "day_number": 6,
      "focus": "Computer Vision basics: Convolutional Neural Networks (CNNs)",
      "display_title": "Spatial Pattern Recognition",
      "frame_hint": "timeline",
      "rationale": "Applies fundamental concepts to specific architecture types for image processing."
    },
    {
      "day_number": 7,
      "focus": "Sequence modeling: RNNs, LSTMs, and the Attention mechanism",
      "display_title": "Processing Sequential Data",
      "frame_hint": "comparison",
      "rationale": "Transitions from static architectures to those capable of handling temporal context."
    },
    {
      "day_number": 8,
      "focus": "Transformer architecture: Self-attention and the path to LLMs",
      "display_title": "The Transformer Revolution",
      "frame_hint": "single-discovery-story",
      "rationale": "Connects foundational theory to the dominant architecture of current research."
    },
    {
      "day_number": 9,
      "focus": "Reading academic papers: Analyzing research methodology and benchmarks",
      "display_title": "Decoding Research Literature",
      "frame_hint": "single-discovery-story",
      "rationale": "Shifts focus from learning concepts to analyzing state-of-the-art research outputs."
    },
    {
      "day_number": 10,
      "focus": "Synthesis: Evaluating model performance against industry benchmarks",
      "display_title": "Assessing ML Research",
      "frame_hint": "comparison",
      "rationale": "Consolidates all previous modules into a framework for critical analysis."
    }
  ]
}
```

**Ambiguity handling:**
The model picked a 'fixed_sequence' shape cleanly, focusing on a structured learning path for machine learning fundamentals. It did not explicitly blend both intents or note the tension between the two, instead prioritizing the 'deeply understand fundamentals' aspect. The result is coherent and well-structured, reflecting the stronger intent signal in the prompt for foundational knowledge. However, it does not fully address the 'following the latest research as it happens' intent, which might require a 'rotating_theme' approach.

