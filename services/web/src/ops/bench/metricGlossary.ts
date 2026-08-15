/** Official bench metric names + how to read them (smoke vs effect). */

export type MetricExplain = {
  leaf: string;
  zh: string;
  en: string;
  /** Short suite tag: 编码 / 英文检索 BEIR / 中文检索 C-MTEB / 上下文. */
  scope: string;
  /** One-line: process vs official effect; smoke vs anchor. */
  effect: string;
};

export type MetricScopeId = "code" | "beir" | "cmteb" | "context" | "other";

const SCOPES: { id: MetricScopeId; re: RegExp; zh: string }[] = [
  { id: "cmteb", re: /retrieval_zh|cmteb/i, zh: "中文检索 C-MTEB" },
  { id: "code", re: /\bcoding(_infer)?\b/i, zh: "编码" },
  { id: "context", re: /\bcontext\b|longbench/i, zh: "上下文 LongBench" },
  { id: "beir", re: /\bretrieval\b|beir/i, zh: "英文检索 BEIR" },
];

export function metricScope(
  key: string,
): { id: MetricScopeId; zh: string } {
  for (const s of SCOPES) {
    if (s.re.test(key)) return { id: s.id, zh: s.zh };
  }
  return { id: "other", zh: "" };
}

const LEAF: Record<
  string,
  Pick<MetricExplain, "zh" | "en" | "effect">
> = {
  resolve_rate: {
    zh: "官方解决率",
    en: "Resolve rate (FAIL→PASS)",
    effect:
      "效果主指标：harness 判定补丁是否让官方失败测试变绿。n5 冒烟不作结论，n25+harness 才可立锚。",
  },
  n_resolved: {
    zh: "官方通过题数",
    en: "Resolved instance count",
    effect: "resolve_rate 的分子。须同时看分母 n_instances。",
  },
  n_instances: {
    zh: "编码题数",
    en: "Instance count",
    effect: "分母。n5=冒烟；n25 / full300 才谈效果。",
  },
  patch_rate: {
    zh: "补丁交出率",
    en: "Non-empty patch rate",
    effect: "过程指标：交没交 git diff。交了≠修对。效果只看 resolve_rate。",
  },
  file_hit_rate: {
    zh: "金标文件命中率",
    en: "Gold-file hit rate",
    effect: "过程：改到了官方相关文件。1.0 仍可能 resolve=0（修错逻辑）。",
  },
  locate_fuse_ok_rate: {
    zh: "定位融合成功率",
    en: "Locate fuse-ok rate",
    effect:
      "过程：grep/search 转 Locate 后 AST+LSP 合成功了的比例。不是官方效果。分母看 locate_fuse_n。",
  },
  locate_fuse_n: {
    zh: "定位融合调用次数",
    en: "Locate fuse attempts",
    effect: "Locate 调了几次（不是题数）。下面几个 n_locate_fuse_* 是这几次里的分桶计数。",
  },
  n_locate_fuse_no_ws_symbol: {
    zh: "定位：工作区没有这个符号",
    en: "Locate: no workspace-symbol match",
    effect:
      "过程计数：去 AST 索引里查这个名字，定义表里没有。常见是查了模块名、文件 stem、形参——索引只收函数/类这类定义，不是任意词。次数高不代表索引坏了，也不是题没修好。对照 locate_fuse_n。",
  },
  n_locate_fuse_definition_null: {
    zh: "定位：有候选但定义为空",
    en: "Locate: definition_null",
    effect:
      "粗定位到了候选，LSP 跳转定义却是空。比「工作区没有符号」更像真没对上定义。",
  },
  n_locate_fuse_lsp_failed: {
    zh: "定位：语言服务失败",
    en: "Locate: LSP failed",
    effect: "LSP 报错。这才算定位基建故障，和「查了不该查的名字」不是一类。",
  },
  n_locate_fuse_lsp_timeout: {
    zh: "定位：语言服务超时",
    en: "Locate: LSP timeout",
    effect: "LSP 超时。基建问题，不是模型胡查。",
  },
  n_locate_fuse_non_definition: {
    zh: "定位：查询不是定义名",
    en: "Locate: non_definition_query",
    effect:
      "比 no_ws_symbol 更明确：查询本身就不是定义名（模块/包名等），单独分桶，不应当成索引损坏。",
  },
  n_grep_locate_failed: {
    zh: "grep 转定位失败次数",
    en: "grep→Locate failed count",
    effect: "grep 被转去 Locate 后失败的次数。过程指标。",
  },
  n_grep_locate_incomplete: {
    zh: "grep 转定位不完整次数",
    en: "grep→Locate incomplete count",
    effect: "有候选但不完整（常和 no_ws_symbol 同源）。过程指标。",
  },
  bucket_share_no_patch: {
    zh: "分桶占比：没交补丁",
    en: "Bucket share: no patch",
    effect:
      "多少题连 nonempty git diff 都没交。过程分桶，不是官方效果。全场交了补丁则为 0。",
  },
  bucket_share_patch_no_apply: {
    zh: "分桶占比：补丁打不上",
    en: "Bucket share: patch does not apply",
    effect:
      "交了补丁，但在仓库底板上 git apply 失败（要改的旧代码对不上）。不是「测试没过」——打上了但官方测试仍红，是另一桶。此项高说明改错位置或上下文漂移；0 只说明补丁能贴上。",
  },
  n_nonempty_patches: {
    zh: "非空补丁题数",
    en: "Non-empty patch count",
    effect: "patch_rate 的分子。交了 diff 的题数。",
  },
  n_instance_ids: {
    zh: "编码题 ID 数",
    en: "Instance-id count",
    effect: "抽样题数，通常等于 n_instances。",
  },
  edit_ok_n: {
    zh: "成功写入次数",
    en: "Successful edits",
    effect: "edit_file 真正写进去的次数（跨题合计）。不是官方通过数。",
  },
  edit_impact_coverage: {
    zh: "编辑附带影响面",
    en: "Edit impact coverage",
    effect: "过程：成功编辑有没有带 impact 字段。",
  },
  edit_checks_coverage: {
    zh: "编辑附带检查",
    en: "Edit checks coverage",
    effect: "过程：成功编辑有没有带语法/检查字段。",
  },
  syntax_reject_count: {
    zh: "语法拒绝次数",
    en: "Syntax-reject count",
    effect: "编辑因语法错误被拒。过程指标。",
  },
  syntax_warning_passthrough_count: {
    zh: "语法警告仍写入",
    en: "Syntax-warning passthrough",
    effect: "有语法警告但仍写进文件的次数。",
  },
  span_fail_n: {
    zh: "替换片段没对上",
    en: "Span/old_text mismatch count",
    effect:
      "edit 要替换的旧文本在文件里找不到（或匹配多次）。补丁因此可能 apply 失败。过程计数。",
  },
  span_fail_with_candidates_rate: {
    zh: "片段失败且给出候选",
    en: "Span-fail with candidates",
    effect: "片段没对上时，有没有返回候选位置。1 表示失败时仍给了候选。",
  },
  file_hit_n: {
    zh: "金标文件命中题数",
    en: "Gold-file hit count",
    effect: "file_hit_rate 的分子。",
  },
  repro_rerun_rate: {
    zh: "复现后再跑测试",
    en: "Repro-rerun rate",
    effect: "过程：是否在修之前先复现失败测试。低不代表没修好。",
  },
  read_outline_coverage: {
    zh: "截断阅读带目录",
    en: "Read-outline coverage",
    effect: "截断的 read_file 是否附了标题目录。长文件导航用。",
  },
  n_read_truncated: {
    zh: "截断阅读次数",
    en: "Truncated reads",
    effect: "read_file 因为太长被截断的次数。",
  },
  n_read_with_outline: {
    zh: "截断阅读含目录次数",
    en: "Truncated reads with outline",
    effect: "read_outline_coverage 的分子。",
  },
  n_testish_tool: {
    zh: "测试类命令次数",
    en: "Test-like tool calls",
    effect: "看起来在跑 pytest/unittest 的命令数。分母给 test_summary。",
  },
  n_test_summary: {
    zh: "解析出测试摘要次数",
    en: "Parsed test_summary count",
    effect: "test_summary_attach_rate 的分子。",
  },
  verify_receipt_rate: {
    zh: "交卷回执率",
    en: "Verify-receipt rate",
    effect: "过程：交卷时有没有生成验证回执。不是官方 resolve。",
  },
  verify_receipt_then_test_rate: {
    zh: "回执后有测试",
    en: "Tested after verify-receipt",
    effect: "出了回执之后是否又跑了测试。",
  },
  n_verify_receipt: {
    zh: "交卷回执次数",
    en: "Verify-receipt count",
    effect: "verify_receipt_rate 的分子。",
  },
  mirror_prewarm_ok: {
    zh: "仓库镜像预热成功",
    en: "Mirror prewarm ok",
    effect: "SWE 题仓库镜像预热是否成功。基建，不是效果。",
  },
  mirror_prewarm_failed: {
    zh: "仓库镜像预热失败",
    en: "Mirror prewarm failed",
    effect: "镜像没预热上。后续 checkout/apply 可能受影响。",
  },
  exit_code: {
    zh: "harness 退出码",
    en: "Harness exit code",
    effect: "0 表示官方测试脚手架跑完了。非 0 时 resolve_rate 不可信。",
  },
  edit_related_tests_coverage: {
    zh: "相关测试覆盖",
    en: "Related-tests coverage",
    effect: "过程：成功编辑是否附带了相关测试路径。方案出口 ≥0.5。",
  },
  related_tests_adoption_rate: {
    zh: "相关测试采用率",
    en: "Related-tests adoption",
    effect: "过程：给了相关测试后模型有没有去跑。",
  },
  test_summary_attach_rate: {
    zh: "测试摘要挂载率",
    en: "test_summary attach rate",
    effect: "过程：pytest/unittest 输出是否解析成摘要。方案出口 ≥0.6。",
  },
  tests_before_submit_rate: {
    zh: "交卷前有测试",
    en: "Tests-before-submit rate",
    effect: "过程：交卷前是否跑过测试。",
  },
  steps_total: {
    zh: "总步数",
    en: "Total agent steps",
    effect: "成本/纪律，非官方效果。",
  },
  elapsed_s_total: {
    zh: "题内耗时合计（秒）",
    en: "Sum of per-instance elapsed seconds",
    effect: "可并行，通常大于墙钟。非官方效果。",
  },
  suite_wall_s: {
    zh: "套件墙钟（秒）",
    en: "Suite wall-clock seconds",
    effect: "该套件从开始到结束的真实时间。",
  },
  ndcg_at_1: {
    zh: "nDCG@1（第1名对不对）",
    en: "Normalized Discounted Cumulative Gain @ 1",
    effect:
      "只看第 1 条：金标排第 1 就是 1，否则 0。比 R@1 更简称「头名对了没」。",
  },
  ndcg_at_10: {
    zh: "nDCG@10（前10名排位）",
    en: "Normalized Discounted Cumulative Gain @ 10",
    effect:
      "前 10 条里相关文档排得越靠前越高；完美名次（金标全在最前）为 1。和召回不同：召回只问「有没有进名单」，nDCG 还问「排第几」。例如只有 1 个金标时，第 1 名=1、第 2 名≈0.63、第 10 名≈0.29、前 10 没有=0。金标若在第 50 名，nDCG@10 仍是 0。smoke 20q 不作结论。",
  },
  ndcg_at_100: {
    zh: "nDCG@100（前100名排位）",
    en: "Normalized Discounted Cumulative Gain @ 100",
    effect:
      "和 nDCG@10 同一套分：相关越靠前越高，但窗口放到前 100。第 50 名在这里能得分，在 @10 里是 0。",
  },
  recall_at_1: {
    zh: "召回率 R@1",
    en: "Recall @ 1",
    effect: "金标有没有出现在第 1 条（只问中没中，不问排第几）。",
  },
  recall_at_10: {
    zh: "召回率 R@10",
    en: "Recall @ 10",
    effect: "金标有没有出现在前 10。中了算进，排第 1 和第 10 在这项里一样。",
  },
  recall_at_100: {
    zh: "召回率 R@100",
    en: "Recall @ 100",
    effect:
      "金标有没有出现在前 100（只问进没进名单）。英文检索 BEIR 的第一验收位：进不去，nDCG 再好看也白搭。中文检索 C-MTEB 同名另算，两套不能相加。n≥100 才谈效果。",
  },
  map_at_1: {
    zh: "平均精度均值 MAP@1",
    en: "Mean Average Precision @ 1",
    effect: "平均精度（切在 1）。辅助排序指标。",
  },
  map_at_10: {
    zh: "平均精度均值 MAP@10",
    en: "Mean Average Precision @ 10",
    effect: "平均精度（切在 10）。辅助 nDCG。",
  },
  map_at_100: {
    zh: "平均精度均值 MAP@100",
    en: "Mean Average Precision @ 100",
    effect: "平均精度（切在 100）。",
  },
  n_queries: {
    zh: "查询数",
    en: "Query count (per dataset, then macro)",
    effect: "20=冒烟；≥100 才作检索效果结论。",
  },
  n_qrels: {
    zh: "相关文档标注数",
    en: "Qrels count",
    effect: "金标条数（宏平均可能带小数）。",
  },
  n_scored: {
    zh: "实际打分查询数",
    en: "Scored query count",
    effect: "去掉缺失/未跑后的分母。",
  },
  infra_rate: {
    zh: "基建失败占比",
    en: "Infra-failure rate",
    effect: "Turn/索引等基建挂了的比例。默认宏分会剔除；>0 时看 *_incl_infra。",
  },
  n_infra_excluded: {
    zh: "剔除的基建失败数",
    en: "Infra cases excluded from primary macros",
    effect: "主指标分母已不含这些题。",
  },
  agent_f1: {
    zh: "用词重合 F1",
    en: "Word-overlap F1 (after normalize)",
    effect:
      "去掉标点、冠词（a/an/the）后按空格拆成词，看终答和标准答案共用了多少词。多写、漏写都会掉分；意思近但用词不同不算高分。limit>0 为冒烟。",
  },
  agent_em: {
    zh: "整句相同 EM",
    en: "Exact Match",
    effect:
      "同样规范化后，和标准答案整句完全一样才得 1。有末行 Answer: 时只对照短语。F1 允许部分用词对上，EM 不允许。",
  },
  n_cases: {
    zh: "上下文题数",
    en: "LongBench case count",
    effect: "smoke 常为 60（每 task 截 20）。",
  },
};

/** Last metric leaf: official.retrieval.ndcg_at_10 → ndcg_at_10 */
export function metricLeaf(key: string): string {
  let k = key.trim();
  k = k.replace(/^official\./i, "");
  k = k.replace(
    /^(coding_infer|coding|retrieval_zh|retrieval|context)\./i,
    "",
  );
  k = k.replace(/^agent\./i, "");
  const parts = k.split(".");
  return parts[parts.length - 1] || k;
}

export function describeMetric(key: string): MetricExplain {
  const raw = metricLeaf(key);
  const incl = raw.endsWith("_incl_infra");
  const leaf = incl ? raw.slice(0, -"_incl_infra".length) : raw;
  const base = LEAF[leaf];
  const { zh: scope } = metricScope(key);
  const inclNote = incl
    ? "含基建失败题（通常把失败当 0 拉低分数）。"
    : "";
  if (!base) {
    return {
      leaf: raw,
      zh: leaf.replace(/_/g, " "),
      en: leaf,
      scope,
      effect: [scope, inclNote].filter(Boolean).join(" · ") || "过程/诊断字段。",
    };
  }
  return {
    leaf: raw,
    zh: base.zh,
    en: base.en,
    scope,
    effect: [scope, base.effect, inclNote].filter(Boolean).join(" · "),
  };
}

/** Headline keys shown on 总览, first match wins per suite family. */
export const OVERVIEW_HEADLINE_LEAVES = [
  "resolve_rate",
  "recall_at_100",
  "ndcg_at_10",
  "agent_f1",
  "agent_em",
  "patch_rate",
] as const;
