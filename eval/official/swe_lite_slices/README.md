# SWE-bench Lite 固定选题

题池 = HuggingFace `princeton-nlp/SWE-bench_Lite` **test** 顺序（300 题）。

| 文件 | 用途 |
|------|------|
| `instance_order.txt` | 全量 300 ID（HF 拉取顺序） |
| `swe_lite_slice_{3,5,10,25}.txt` | 官方回归档位：顺序前缀 |
| custom N | 同一 `instance_order.txt` 前 N 题（3≤N≤300） |

不要随机抽样当官方回归。指纹 = 所选 ID 列表的 SHA-256。
