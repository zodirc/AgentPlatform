# Demo（5 分钟可复现）

> 目的：按固定路径演示，不改产品逻辑。前置：`make up`，浏览器打开 `http://localhost/`，已登录；模型在「设置 → 模型」或 `.env` 配好。

## A. 写作（RAG → 改稿 → 审批）

1. 打开 **写作** `/writing`，新建或进入会话。  
2. 让 Agent 基于语料写/改一小节（应出现 `search_sources` 或可引用素材）。  
3. 若有 `propose_patch` / diff：**批准或拒绝**一次，看工作台状态与终态一致。  
4. （可选）导出或 `/verify`：强调 **Turn completed ≠ 交付一定正确**。

## B. Agent（改文件 → 审批 → Stop）

1. 打开 **Agent** `/agent`，指向当前 Work。  
2. 让它改一个小文件（会走写盘审批）→ **批准**。  
3. 再发一轮稍长任务，执行中点 **Stop**：应为 **取消态**，不要讲成「失败」。  
4. （可选）`run_tests`：免审但只允许测试启动器（见 docs/31 E1）。

## C. Ops 旁路观测（不影响前台速率）

> 密钥：启动日志或 `.env` 的 `OPS_TEST_SECRET`。路径：`/ops/<secret>/…`。  
> **只读 / 旁路**：不挂写作热路径，不改 loop。

1. 在写作里先跑一轮带检索的 Turn，记下 `turn_id`（或从 Ops「最近检索」点开）。  
2. `/ops/<secret>/retrieval` → 看 L1/L2/L3；注意诊断条与层差高亮。  
3. 同一 Turn 点 **模型信封** / **Raw 快照**（页内「同 Turn 观测」链接）。  
4. 评测：`/ops/<secret>/test` 的 `golden` 是切片；完整证明用 `suite=ci` ≡ `make gate`（见 docs/29）。

## 失败救场

| 现象 | 处理 |
|------|------|
| 无检索审计 | 确认 writing 真调了 `search_sources`；刷新 Ops 列表 |
| 无 bwrap | 需重建 runtime 镜像；本机无包会降级（docs/31） |
| Stop 仍显示失败 | 看终态事件 / Turn 状态字段，以库为准 |
