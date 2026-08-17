# SWE-bench Lite 固定选题

题池 = HuggingFace `princeton-nlp/SWE-bench_Lite` **test** 顺序（300 题）。

| 文件 | 用途 |
|------|------|
| `instance_order.txt` | 全量 300 ID（HF 拉取顺序） |
| `swe_lite_slice_{3,5,10,25}.txt` | 官方回归档位：顺序前缀 |
| `swe_lite_slice_50.txt` | 结构智能冒烟：按仓库分层抽样（seed=20260810）；与 `eval/swebench/lite50.txt` 同 ID |
| custom N | 同一 `instance_order.txt` 前 N 题（3≤N≤300） |

不要随机抽样当官方回归。指纹 = 所选 ID 列表的 SHA-256。

结构智能路径见 `eval/swebench/README.md` 与 [工具与上下文 §2](../../../docs/core/tools-and-context.md)。
