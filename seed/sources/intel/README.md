# Intel 常驻语料（种子）

> 对齐写作种子：`seed/sources/writing` · RAG 契约见 [docs/15](../../docs/15-rag-and-sources.md)。  
> **Turn / `search_sources` / `enrich_ioc` 永不拉网**；充实库用本目录 + 离线 fetch。

## 布局

```text
seed/sources/intel/
├── SOURCES.yaml          # 上游清单（许可 / sparse / 体积上限）
├── _demo/lab-notes/      # 进 git：golden / 开箱可搜
├── ioc/                  # 进 git：demo IOC 卡（enrich_ioc 可读）
└── vendor/               # gitignore：make intel-corpus-fetch 产出
    ├── hunt/
    ├── techniques/
    ├── actors/
    └── ioc/
```

Compose 只读挂载：

```text
./seed/sources/intel  →  /workspace/sources/seed/intel  (ro)
```

索引路径形如 `sources/seed/intel/_demo/...`、`sources/seed/intel/vendor/...`。

## 命令

```bash
make intel-corpus-fetch          # 读 SOURCES.yaml → cache clone → 转 md/卡 → vendor/
make intel-corpus-fetch ONLY=threat-hunter,atomic-red-team
make sync-sources                # Turn 外重建索引（栈已 up）
```

约束（脚本强制）：

- `vendor/` ≤ **150 MiB**
- 禁止复制 `*.exe` / `*.dll` / `*.msi` / `*.pdf` 等（见 `SOURCES.yaml` `forbidden_globs`）
- Maltrail 默认 **关闭**（`enabled: false`）；需要时再开

## Demo vs 充实

| 层 | 提交？ | 作用 |
|----|--------|------|
| `_demo/` + `ioc/` | 是 | CI / golden / 无网开箱 |
| `vendor/` | 否 | Demo/自用充实 RAG |
| `.cache/intel-corpus/` | 否 | 上游浅克隆缓存 |

改完语料后若要立刻可搜：`make sync-sources`。
