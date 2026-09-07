# Delegate wait / join

Parent `delegate` parks the parent Turn (`waiting_child`) instead of nesting the child's 12 steps inside the parent while.

- Read-only types (`explore`, `retrieve`, `researcher`, `fact_checker`, `planner`) join concurrently (wall clock = slowest).
- Mutating types join serially, still outside the parent while.
- `wait=false` is the escape hatch back to a blocking nested engine (also used for nested depth>0).
- Do not poll the child with extra parent model turns; the controller joins then resumes the same `run_id`.
