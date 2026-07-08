# Shared Python contracts (`agent-contracts`)

Cross-service Pydantic v2 models for api ↔ runtime command boundaries (ADR-017).

## Install

```bash
pip install packages/contracts/python
```

## Usage

```python
from agent_contracts import ApproveToolCallCommand, StartTurnCommand
```

Runtime internal commands validate request bodies against these models.

## Tests

```bash
pytest packages/contracts/python/tests -q
```
