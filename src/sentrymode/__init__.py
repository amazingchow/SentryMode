"""
SentryMode package metadata.

[INPUT]: Import-time package loading.
[OUTPUT]: Package metadata (`__version__`) for runtime and tests.
[POS]: Top-level namespace marker for `sentrymode`.
       Upstream: tooling and tests importing package metadata.
       Downstream: none.

[PROTOCOL]:
1. Keep this module side-effect free.
2. Sync version metadata with release/tag policy updates.
"""

__version__ = "0.1.0"
