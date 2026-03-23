# Unix Philosophy for Python

## Table of Contents

1. Modularity
2. Clarity
3. Composition
4. Separation
5. Simplicity
6. Parsimony
7. Transparency
8. Robustness
9. Representation
10. Least Surprise
11. Silence
12. Repair
13. Economy
14. Generation
15. Optimization
16. Diversity
17. Extensibility
18. Review Checklist

## 1. Modularity

- Prefer small parts with clean interfaces.
- Use modules, packages, `Protocol`, and injected collaborators to separate responsibilities.
- Avoid kitchen-sink functions that mix validation, persistence, network calls, and orchestration.

## 2. Clarity

- Prefer explicit names, explicit types, and obvious state.
- Use `dataclass`, `Enum`, and straightforward conditionals before clever bitmasks or metaprogramming.
- Reject patterns that save lines but increase interpretation cost.

## 3. Composition

- Design units that can be connected.
- In Python, use generators, decorators, middleware, and small call chains for composition.
- Avoid handlers that hardwire logging, auth, retries, and business logic into one body.

## 4. Separation

- Separate policy from mechanism and interface from engine.
- Keep business rules independent from vendor SDK details, transport layers, and storage specifics.
- Hide concrete backends behind small interfaces when multiple implementations are plausible.

## 5. Simplicity

- Start with the simplest structure that works.
- Avoid Java-style abstraction stacks unless the code has demonstrated a need for them.
- Prefer a simple store object or function over speculative factories and builders.

## 6. Parsimony

- Build a big program only when smaller pieces will not do.
- For operational cleanup, migrations, or one-time backfills, prefer a standalone script.
- Avoid adding permanent runtime surfaces for temporary jobs.

## 7. Transparency

- Make state and behavior easy to inspect.
- Prefer readable enums, explicit state names, and log-friendly values over magic numbers.
- Design so a maintainer can understand failures from logs and stack traces.

## 8. Robustness

- Robustness comes from simplicity plus visible failure modes.
- Catch precise exceptions, validate inputs early, and preserve context with `raise ... from ...`.
- Never swallow exceptions and pretend success.

## 9. Representation

- Put knowledge into data.
- Replace long branching logic with lookup tables, configuration maps, or declarative schemas.
- Change business variants by editing data, not code flow, when possible.

## 10. Least Surprise

- Make APIs behave exactly as their names suggest.
- Do not hide writes inside getters.
- Do not use mutable default arguments.
- Do not make callers guess whether a method mutates, caches, retries, or logs.

## 11. Silence

- When a lower-level component has nothing surprising to say, keep it silent.
- Library and helper code should return values or raise errors, not print to stdout.
- Leave logging policy to the application boundary.

## 12. Repair

- Fail fast when required prerequisites are missing.
- Let startup crash loudly on missing config or broken dependencies.
- For runtime failures, use the framework's central error handling instead of ad hoc suppression.

## 13. Economy

- Optimize for programmer time before machine time.
- Prefer standard library and mainstream tools unless profiling or operational evidence justifies more complexity.
- Do not introduce lower-level languages or niche libraries for imagined wins.

## 14. Generation

- Generate repetitive structure when tools can do it reliably.
- Use `pydantic`, OpenAPI generation, migration generators, and codegen where it removes boilerplate safely.
- Avoid hand-maintaining repetitive schemas or docs if the source of truth can produce them.

## 15. Optimization

- Get it working, then measure.
- Use profilers and traces before introducing concurrency, caching, or lower-level rewrites.
- Reject performance work driven only by fear or taste.

## 16. Diversity

- Distrust the "one true way."
- Use Python as glue across the right storage and service choices.
- Reach for Redis, Elasticsearch, queues, or other specialized systems when the problem demands them.

## 17. Extensibility

- Design for reasonable future change without overbuilding.
- In Python, default arguments and keyword arguments often provide enough extension room.
- Prefer additive, unsurprising APIs over complex option patterns.

## 18. Review Checklist

Use these prompts during design or review:

- Does each module or class have one obvious job?
- Are dependencies expressed through small interfaces instead of concrete entanglement?
- Is the code clear without hidden state, magic flags, or naming surprises?
- Are policy and mechanism separated?
- Can one-off operational work live in a script instead of the production path?
- Are logs, errors, and state values easy to inspect?
- Are exceptions handled precisely and noisily enough?
- Is branching knowledge better represented as data?
- Are defaults safe and unsurprising?
- Is low-level code quiet unless explicitly asked to log?
- Is the solution optimized for maintainability first?
- Is extensibility achieved with simple Python features before custom patterns?
