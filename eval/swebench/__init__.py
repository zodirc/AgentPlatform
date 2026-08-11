"""SWE-bench Lite helpers for agent coding (structural lane fused into Profile).

Protocol: docs/plan/coding-structural-intelligence.md §8.

This package does **not** reimplement the official harness. It:
1. Freezes the lite-50 stratified slice (also mirrored under eval/official/swe_lite_slices/).
2. Computes process metrics (file-level localization hit rate, empty-diff rate).
3. Documents Ops L1 recipes with **no outbound network** during ops_eval Turns
   (answer-leak ban).

Official score remains `% resolved` from `swebench.harness` via
`make official-bench-coding-eval`.
"""

from __future__ import annotations
