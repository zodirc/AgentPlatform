# PROD-1 · 产品镜像小套件（草稿 · 2026-08-04）

> **状态**：批次 A 起步稿 · **未冻结** · **禁止用于调参**（只做验收资产）  
> **协议**：与 BEIR L1 相同 — writing scenario · arm=free · `search_sources` · first-seen 合并  
> **语料**：`seed/sources/writing/**`（树状 path/tags 分布，非扁平 BEIR）  
> **规模目标**：20–30 题；本稿先落 **24** 题草案，人工复核 gold 后再版本冻结为 `prod1-v0`

## 用法（规划）

1. 物化：将 `seed/sources/writing` 同步进隔离 Work（或复用 writing seed 可见性）。  
2. 题面：下表 `need` 作为 Information need（自由臂，不写工具剧本）。  
3. Gold：`gold_paths` 为相对 `sources/writing/` 的路径（允许多 gold）。  
4. 计分：与 BEIR 相同 IR 指标（nDCG@10 / R@k）；另记 `gold_read_rate`（RET-14 同款）。  
5. **冻结后**才跑：RET-4/11 落地后复验 BEIR→PROD 迁移率。

## 题集草案（24）

| id | need（信息需求） | gold_paths |
|----|------------------|------------|
| p01 | 《我真不想重生啊》的主角叫什么名字？ | novels/novels1.md |
| p02 | 《我真不想重生啊》重生时主角在哪所大学的哪个校区？ | novels/novels1.md |
| p03 | 《我真不想重生啊》里沈幼楚就读于哪所学校？ | novels/novels1.md |
| p04 | 小说《亮剑》的作者是谁？首次出版是哪一年？ | dramas/drama1.md |
| p05 | 电视剧《亮剑》央视版多少集？首播在哪一年？ | dramas/drama1.md |
| p06 | 李云龙在 1955 年授衔时被授予什么军衔？ | dramas/drama1.md |
| p07 | 电视剧《潜伏》的男主角叫什么？他潜伏在哪个机构？ | dramas/drama6.md |
| p08 | 《潜伏》里余则成的公开掩护身份是怎样的夫妻设定？ | dramas/drama6.md |
| p09 | 《人民的名义》中汉东省两大派系分别叫什么？谁是「达康书记」？ | dramas/drama4.md |
| p10 | 《人民的名义》「一一六」事件与哪家工厂有关？ | dramas/drama4.md |
| p11 | 电影《心花路放》的导演是谁？领衔主演是谁？ | movie/movie1.md |
| p12 | 《心花路放》公路之旅的终点是哪里？票房大约多少？ | movie/movie1.md |
| p13 | 玄武门之变发生在哪一年？发动者是谁？ | periods/periods2.md |
| p14 | 玄武门之变中被杀的太子与齐王分别是谁？ | periods/periods2.md |
| p15 | 重庆谈判最终签署的文件叫什么？历时多少天？ | periods/periods4.md |
| p16 | 重庆谈判期间中共提出的三大口号是什么？ | periods/periods4.md |
| p17 | 《铁齿铜牙纪晓岚》主要讲述哪三位人物的故事？ | dramas/drama3.md |
| p18 | 《好先生》的男主角职业设定是什么？ | dramas/drama5.md |
| p19 | 《水浒传》资料里梁山泊首领最终是谁？ | novels/novels2.md |
| p20 | 1950 年中国志愿军入朝的资料文档路径在哪一类目录？ | periods/periods1.md |
| p21 | 《战争之王》电影资料的主题 slug 是什么？ | movie/movie2.md |
| p22 | 《北平无战事》属于 writing 库的哪一类子目录？ | dramas/drama8.md |
| p23 | 写作既定事实库默认一部作品应放成几个 markdown 文件？ | （可选：FORMAT.md 若纳入索引；否则删本题） |
| p24 | 《五号特工组》是什么类型的作品资料？ | dramas/drama2.md |

## 复核清单（冻结前）

- [ ] 每题在对应 gold 文件中用原文可核验答案（写 `answer_hint` 字段）  
- [ ] path_prefix / 可见性与 writing Work 一致  
- [ ] 删掉依赖未索引文件的题（如 p23 若 FORMAT 不在 sources）  
- [ ] 版本戳记：`prod1-v0` + 题包 fingerprint  
- [ ] 写入 runner 注册票（另立；本起步只定题）

## 机器可读草稿

见同目录 `prod1_draft.jsonl`（每行一题；`frozen=false`）。
