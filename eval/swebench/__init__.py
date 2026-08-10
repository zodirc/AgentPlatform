"""SWE-bench Lite dual-track runner for coding structural intelligence.

Protocol: docs/plan/coding-structural-intelligence.md §8.

This package does **not** reimplement the official harness. It:
1. Freezes the lite-50 stratified slice (also mirrored under eval/official/swe_lite_slices/).
2. Computes process metrics (file-level localization hit rate, empty-diff rate).
3. Documents / orchestrates dual-track runs with STRUCTURAL_ENABLED=0|1 and **no outbound
   network** during agent Turns (answer-leak ban).

Official score remains `% resolved` from `swebench.harness` via
`make official-bench-coding-eval`.
"""

from __future__ import annotations
