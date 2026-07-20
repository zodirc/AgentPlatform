# Offline retrieval bench (docs/27 §8.1 layer 1 · docs/28 RE0/RE3)

Layer-1 A/B harness for `search_sources` quality — **no agent loop**.

## Layout

```text
eval/retrieval/
├── README.md
├── EFFECT_CHECKLIST.md
├── corpus/             # fixed sources tree → copied to tmp/sources/
│   ├── hr/             # leave, onboarding, expense, remote-work
│   ├── legal/          # nda (+ 张白鹿 noise), employment-ip
│   └── writing/        # liangjian, yuefei, zengguofan, scene-chuanyun
├── qrels.yaml          # query → expect path/section + path_prefix A/B
└── (runner: scripts/retrieval_bench.py)
```

Run after expanding corpus/qrels:

```bash
make retrieval-bench
```

## Hit field baseline (RE0)

| Field | Hybrid / vector hit | Keyword (filesystem) before RE1 | Notes |
|-------|---------------------|----------------------------------|-------|
| `path` | yes | yes | workspace-relative |
| `chunk_id` | yes | no (file-level) | RE1 may add when section-parsed |
| `citation_id` | yes | yes (`cite:{stem}`) | required for cite loop |
| `excerpt` | yes | yes | truncated |
| `score` | yes | often absent | keyword may omit |
| `section_title` | yes | no (until RE1) | intentional gap |
| `line_start` / `line_end` | yes | no (until RE1) | intentional gap |

`path_prefix` (RE0 freeze): optional string; relative; auto-prefixed with `sources/` if omitted; reject `..` / absolute; illegal → empty hits + `hint`.

## Run

From repo root (uses runtime venv / PYTHONPATH):

```bash
cd services/runtime && python3 ../../scripts/retrieval_bench.py
# or:
make retrieval-bench
```

Compares **A** (no filter) vs **B** (`path_prefix` from qrels when set) on Recall@k / noise hits.

## Effect gate

RE3 merge requires this bench to show: target-path recall not worse; noise paths down when `path_prefix` applied.
