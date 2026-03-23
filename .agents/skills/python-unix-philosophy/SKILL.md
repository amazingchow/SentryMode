---
name: python-unix-philosophy
description: Apply Unix philosophy to Python architecture, refactoring, and code review. Use when Codex needs to design or review Python modules, services, scripts, dependency boundaries, error handling, configuration-driven logic, or API surfaces; especially when the goal is to reduce coupling, improve clarity, split oversized components, prefer simple mechanisms, or make future extension safer without over-engineering.
---

# Python Unix Philosophy

## Overview

Use this skill to translate broad Unix philosophy into concrete Python decisions. Favor small parts, explicit interfaces, unsurprising behavior, and data-driven design over clever abstractions or speculative frameworks.

Read [references/unix-python-principles.md](references/unix-python-principles.md) when you need the full principle index, review checklist, or examples for a specific rule.

## Workflow

1. Classify the request.
   - Architecture/design: choose module boundaries, ownership, and interfaces.
   - Refactor: split large units and remove accidental complexity.
   - Code review: identify where the code violates Unix-style constraints.
   - Script/tooling: decide whether a one-off task belongs in the app or a standalone script.
2. Map the problem to the smallest relevant principle set.
   - Reach first for modularity, clarity, separation, simplicity, robustness, and least surprise.
   - Pull in economy, optimization, diversity, or extensibility only when they materially affect the decision.
3. Prefer local, concrete improvements.
   - Replace giant functions with small collaborators.
   - Replace inheritance-heavy seams with `Protocol`, simple functions, or composition.
   - Replace hardcoded branches with tables or config maps.
   - Replace hidden side effects with explicit names and explicit state changes.
4. Explain tradeoffs in plain language.
   - Say which principle is being honored or violated.
   - Say why the proposed change improves maintenance, testing, or debugging.
   - Prefer one clear recommendation over many equally plausible options.

## Default Heuristics

- Keep modules and classes narrow in purpose.
- Program to consumer-facing interfaces; in Python this usually means `Protocol`, callables, or small objects.
- Prefer `dataclass`, `Enum`/`StrEnum`, and typed dictionaries/models over clever flags or magic state.
- Separate policy from mechanism: business rules should not depend on vendor SDK details.
- Use standalone scripts for one-off maintenance work instead of adding permanent app endpoints.
- Make failures explicit with precise exceptions and `raise ... from ...`.
- Keep library code quiet: return values or raise errors; do not `print()`.
- Fold changing knowledge into configuration or data tables instead of long `if/elif` chains.
- Avoid surprising APIs: no mutable default arguments, no hidden writes in getters, no silent retries unless the contract says so.
- Optimize only after profiling or clear evidence.

## Design Guidance

### Architecture

- Start from the smallest useful interface.
- Prefer composition over inheritance.
- Add abstraction only after duplication or test seams prove the need.
- Choose boring, standard tools first; justify extra frameworks with concrete payoff.

### Refactoring

- Find the unit doing more than one job.
- Split mechanism from policy before introducing patterns.
- Preserve behavior first, then simplify names, signatures, and dependency flow.
- If a task is operational and temporary, move it into `scripts/` instead of the main runtime path.

### Code Review

- Review for maintenance risk, not stylistic novelty.
- Flag tight coupling, implicit behavior, giant interfaces, silent failure, and premature optimization.
- Tie each finding to a principle so the feedback is teachable and reusable.
- If multiple fixes are possible, recommend the smallest change that restores clarity and safety.

## Principle Priority

When principles compete, use this bias order:

1. Clarity over cleverness.
2. Simplicity over speculative extensibility.
3. Transparency over hidden convenience.
4. Robustness over silent recovery.
5. Developer time over marginal machine-time wins, unless profiling says otherwise.

## Reference Usage

- Read only the sections you need from [references/unix-python-principles.md](references/unix-python-principles.md).
- Use the review checklist in that file when auditing a change set or proposing a refactor plan.
- Reuse the anti-patterns and preferred patterns there when you need short, teachable rationale.
