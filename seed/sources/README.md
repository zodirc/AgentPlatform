# 写作既定事实库（Seed）

## 怎么用

1. **让联网 AI 写内容：** 复制 [`PROMPT_FOR_RESEARCH_AI.md`](PROMPT_FOR_RESEARCH_AI.md)，文末填主题。
2. **保存到仓库（常驻）：**

```text
seed/sources/writing/novels/<slug>.md
seed/sources/writing/dramas/<slug>.md
seed/sources/writing/persons/<slug>.md
seed/sources/writing/periods/<slug>.md
```

3. 格式：[`FORMAT.md`](FORMAT.md) · 模板：[`_template.md`](_template.md)

一部作品默认 **一个文件**。

## 运行时如何能搜到（挂载，不拷贝）

Compose 将本目录 **只读挂载** 到容器内：

```text
./seed/sources/writing  →  /workspace/sources/seed/writing  (ro)
```

- 索引路径形如：`sources/seed/writing/dramas/….md`
- **不把文件复制进** 宿主机 `workspace/`（用户沙箱仍 gitignore）
- 启动 IX0 / IX2 监视会扫到该挂载；热路径 `search_sources` **不建库**
- 改完 seed 后若要立刻重建索引：`make seed-sources`（= `make sync-sources`，只索引不拷贝）
- Agent **不能**写入 `sources/seed/**`（只读）；请改仓库里的 `seed/sources/writing/`
