## How this project is configured to work automatically
Task prompts arrive here already fully planned and reviewed elsewhere — no manual "use skill X" instruction should ever be needed. This file makes the automatic behavior below actually automatic:

- Codebase exploration → the Explore Codebase skill (graphify), before Grep/Glob/Read. See skills/explore-codebase/SKILL.md for commands and freshness caveats.
- Coding principles below apply unconditionally, every turn.
- Superpowers' session-start hook already engages its TDD/verification/review discipline automatically — no reinforcement needed here.
- claude-mem's lifecycle hooks already capture and inject session memory automatically — no reinforcement needed here.
- ponytail's hooks already re-inject its YAGNI/anti-over-engineering discipline every turn — no reinforcement needed here.

## Always-Active Coding Principles (Karpathy Guidelines — enforced directly here, not left to skill-matching)
Apply to every task, unconditionally:
1. Think before coding: state assumptions out loud, ask when genuinely ambiguous — never silently pick an interpretation.
2. Simplicity first: write only what was asked. No speculative abstractions, no unrequested flexibility.
3. Surgical changes: touch only what the task requires, match existing style. Mention pre-existing dead code found along the way — don't delete it unasked.
4. Goal-driven execution: turn the task into a concrete, verifiable success criterion before calling it done.
(Full skill at skills/karpathy-guidelines/SKILL.md for detailed examples on a specific edge case.)

## Working with externally-planned tasks
Detailed prompts arriving from outside this session (structured as GOAL / STEP 1 — RECON / STEP 2 — BUILD / STEP 3 — VERIFY, or similar) are an already-completed, already-reviewed plan. Treat it as settled:
- Skip Superpowers' own brainstorm/spec-generation phase for these — go straight to execution.
- Superpowers' TDD, verification-before-completion, and review skills still apply in full.
- If the plan is genuinely silent on a point it needed to cover, stop and ask — same bar as "ask when ambiguous," not license to improvise past it.
- Recon steps must report real findings (file:line, actual behavior) before the build step starts, never assumptions.

## Project facts (Curivio)
- Single LLM entry point: backend/llm/model_provider.py (Gemini-primary/Groq-fallback). Never hand-roll a new provider client — this is a hard rule, not a style preference the graph would infer from usage patterns alone.