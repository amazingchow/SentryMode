# Self-Explanatory Documentation Reference

## Table of Contents

1. Core Protocol
2. Root Document Template
3. Package Document Template
4. Module Docstring Template
5. Trigger Guide
6. Audit Checklist

## 1. Core Protocol

- Update documentation atomically with code changes.
- Sync from the inside out:
  - changed file
  - module docstring
  - nearest `.package.md`
  - root architecture markdown if the change is globally relevant
- Preserve fractal autonomy: each directory should expose enough markdown context for an agent to reconstruct the local worldview.

## 2. Root Document Template

Use the root document for the system contract and top-level architecture.

```md
# Root Architecture

## Core Synchronization Protocol

1. Update package and module docs immediately after code changes.
2. Bubble local changes upward only when they affect global understanding.
3. Keep each layer description aligned with actual code ownership.

## Top-Level Architecture

- `/src/entrypoints`: framework wiring, transport adapters, DI bootstrap.
- `/src/domain`: pure business entities and rules.
- `/src/usecases`: application orchestration.
- `/src/infrastructure`: database, cache, API, and other external adapters.
- `/src/shared`: reusable cross-cutting helpers.
- `/tests`: test suite and fixtures.
- `/api`: contracts such as OpenAPI, GraphQL, or protobuf.
```

Write the root doc when:

- a new top-level area appears or disappears
- layer responsibilities shift
- a new architectural rule becomes mandatory

## 3. Package Document Template

Use `.package.md` as the local map for a package.

```md
# Package: src.domain.auth

1. Status: Authentication core domain package. Pure business logic; no framework or ORM coupling.
2. Logic: Validates credentials, issues domain results, and raises domain exceptions on failure.
3. Constraints:
   - Do not import `fastapi`, `sqlalchemy`, or HTTP clients.
   - Express external IO through `Protocol` or other abstract seams.

## Member List

- `entities.py`: core models.
- `services.py`: domain logic.
- `interfaces.py`: abstract repositories or gateways.
- `exceptions.py`: package-specific errors.
```

Keep it minimal. It is a reconstruction aid, not a design essay.

## 4. Module Docstring Template

Use module header docstrings for the most local architectural truth.

```python
"""
[INPUT]: (creds: Credentials) + injected UserRepository protocol
         - Raw credentials and storage abstraction.
[OUTPUT]: Token
         - Returns a token object.
         - Raises InvalidCredentialsError on failed validation.
[POS]:   Located in /src/domain.
         Upstream: called by /src/usecases.
         Downstream: implemented by /src/infrastructure via interfaces.py.

[PROTOCOL]:
1. Sync this docstring when signatures or core flow change.
2. Re-check the package document after updating this file.
"""
```

Include:

- key inputs and outputs
- important raised exceptions
- architectural position
- upstream and downstream direction when relevant

## 5. Trigger Guide

Update the module docstring when:

- a public function or class signature changes
- the module takes new dependencies
- the core control flow or side effects change
- raised exceptions or return shapes change

Update `.package.md` when:

- files are added, removed, renamed, or split
- package responsibilities change
- architectural constraints change
- the member list is stale

Update the root doc when:

- a package is promoted, merged, or renamed in a way that changes the system map
- top-level layer responsibilities change
- the project adopts a new architectural rule or layout

## 6. Audit Checklist

Use these prompts during review:

- Can a reader understand this directory's role from local markdown alone?
- Do module docstrings still match actual inputs, outputs, and dependency direction?
- Does each `.package.md` list the current files and real constraints?
- Does the root doc still reflect the current top-level layout?
- Are purity boundaries and forbidden imports documented where they matter?
- Did the code change introduce a new side effect or dependency that the docs omit?
- Is any documentation describing an idealized architecture instead of the real one?
