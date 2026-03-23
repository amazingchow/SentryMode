---
name: sync-self-explanatory-docs
description: "Synchronize Python architecture documentation with code using a three-level self-explanatory system: repository root docs, package-level `.package.md` files, and module header docstrings. Use when Codex changes Python project structure, adds or removes modules, refactors boundaries, updates entrypoints/domain/usecases/infrastructure responsibilities, or needs to audit and repair drift between the codebase and its architectural documentation."
---

# Sync Self Explanatory Docs

## Overview

Use this skill to keep the map aligned with the terrain. After changing Python code or architecture, update the closest module docstring first, then the containing package map, and finally the root architecture document if the change affects global understanding.

Read [references/self-explanatory-reference.md](references/self-explanatory-reference.md) when you need concrete templates for `/.root.md`, `/.package.md`, or module header docstrings.

## Workflow

1. Identify the scope of the change.
   - Module-local: behavior, signature, inputs/outputs, exceptions, dependency direction.
   - Package-level: new files, removed files, changed responsibilities, changed constraints.
   - System-wide: changed top-level layout, renamed layers, new runtime entrypoints, new architectural rules.
2. Update documentation from the inside out.
   - Start with the changed module docstring.
   - Bubble up to the nearest `.package.md`.
   - Update the root architecture document only if the package change affects global understanding.
3. Keep each layer focused on its job.
   - Module docstring: input, output, position, and synchronization protocol.
   - Package doc: status, logic, constraints, and member list.
   - Root doc: canonical architecture, layer boundaries, and synchronization rules.
4. Prefer concise truth over verbose aspiration.
   - Document what the code really does now.
   - Name upstream and downstream dependencies explicitly.
   - State forbidden imports or side effects where they matter.

## Three Levels

### Root Document

- Treat the root markdown as the system contract.
- Describe the top-level layout, major layer responsibilities, and the synchronization protocol.
- Update it only when a local change changes the global map.

### Package Document

- Keep one `.package.md` per meaningful package or bounded context.
- Use a minimal structure: status, logic, constraints, then member list.
- Rewrite it immediately when files are added, removed, renamed, or repurposed inside the package.

### Module Header Docstring

- Put the most local truth at the top of the Python module.
- Capture inputs, outputs, placement in the architecture, and dependency direction.
- Synchronize it when public signatures, core flows, or dependency expectations change.

## Default Heuristics

- Document boundaries, not implementation trivia.
- Prefer three accurate lines over a stale essay.
- Record constraints that prevent architectural drift, such as forbidden framework imports in domain code.
- Mention upstream callers and downstream collaborators when that helps reconstruction.
- If a module has heavy side effects, make them explicit in the docstring.
- If a package is supposed to stay pure, say so in the package constraints.
- Do not invent future architecture; reflect the current state.

## When Repairing Drift

- Compare code, package docs, and root docs before editing.
- Fix the smallest stale layer first so higher-level updates reflect fresh local truth.
- If names and files changed, update member lists before polishing prose.
- If a package's actual dependencies violate its documented constraints, call out the mismatch instead of silently rewriting away the problem.

## Review Expectations

- Flag missing or stale `.package.md` files when packages have clearly evolved.
- Flag module docstrings that no longer match inputs, outputs, side effects, or dependency direction.
- Flag root docs that still describe old layers, folders, or architecture decisions.
- Recommend synchronization as part of the same change, not as a follow-up chore.

## Reference Usage

- Use [references/self-explanatory-reference.md](references/self-explanatory-reference.md) for templates, trigger rules, and a review checklist.
- Load only the section you need: root, package, module, or audit checklist.
