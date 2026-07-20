# 17 — Multi-table / `search_records`（蓝图）

> **日常票状态见 [15 RE5](15-rag-and-sources.md)。** 本文只留形状；开闸后再扩。

```text
search_records(query, channel?, filters?)
  → 确定性 rule router
  → parallel channels（各 ≤300ms）
  → ACL 谓词 → fused hits（无后端则空）
```

- 仅工具中介；超时降级；禁止 LLM 每问路由 / 新 graph 节点。  
- 现状：工具返回 `unimplemented` / 空 hits。  
- 开闸：选一张业务表 + ACL → 一个 `RecordChannel` + deny/timeout golden。
