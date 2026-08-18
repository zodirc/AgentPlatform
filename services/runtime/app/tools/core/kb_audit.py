"""Knowledge-base quality audit (stdlib).

Used as a writing-scenario tool and as ``eval/0112/scan.py``.
Detectors are rule/pattern based — they do not key off article ids.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

ISSUE_TYPES: dict[str, dict[str, str]] = {
    "empty": {
        "label": "空条目",
        "impact": "用户问到该问题会得到空白答案，客服等于没有知识。",
    },
    "stale_conflict": {
        "label": "与现行规则矛盾",
        "impact": "自动回复会念过错政策（退货、运费、支付、发票、会员、优惠），直接造成客诉或资损。",
    },
    "dup_question": {
        "label": "同问重复",
        "impact": "检索可能命中互相打架的两条，模型随机采用一条，表现为幻觉或口径漂移。",
    },
    "intra_conflict": {
        "label": "库内互斥",
        "impact": "同一主题两条说法相反，即使每条单独看也不知道以谁为准。",
    },
    "coverage_gap": {
        "label": "覆盖缺口",
        "impact": "规则里有、库里没有（或全是错的），机器人只能编或拒答。",
    },
}

_PUNCT_RE = re.compile(r"[\s\-—–_,.，。！？、；：:\"'“”‘’（）()【】\[\]《》·•]+")


def normalize_question(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text or "").lower()
    return _PUNCT_RE.sub("", folded)


def parse_rules(markdown: str) -> dict[str, Any]:
    """Pull checkable facts out of business_context.md. Missing keys stay None."""
    rules: dict[str, Any] = {
        "no_reason_days": None,
        "quality_days": None,
        "non_quality_freight": None,
        "quality_freight": None,
        "ship_hours": None,
        "couriers": [],
        "arrive_days": None,
        "pay_supported": [],
        "cod_forbidden": False,
        "paper_invoice": False,
        "invoice_channel": None,
        "silver_spend": None,
        "silver_discount": None,
        "gold_spend": None,
        "gold_discount": None,
        "coupon_full_reduce": [],
        "coupon_stack": False,
        "online_hours": None,
        "phone_hours": None,
        "email_sla": None,
        "raw": markdown,
    }
    m = re.search(r"普通商品[：:]\s*(\d+)\s*天无理由", markdown)
    if m:
        rules["no_reason_days"] = int(m.group(1))
    m = re.search(r"质量问题[：:]\s*(\d+)\s*天", markdown)
    if m:
        rules["quality_days"] = int(m.group(1))
    if "非质量问题退货运费：买家承担" in markdown or "非质量问题退货运费:买家承担" in markdown:
        rules["non_quality_freight"] = "buyer"
    if "质量问题退货运费：商家承担" in markdown or "质量问题退货运费:商家承担" in markdown:
        rules["quality_freight"] = "merchant"
    m = re.search(r"发货时间[：:].*?(\d+)\s*小时", markdown)
    if m:
        rules["ship_hours"] = int(m.group(1))
    m = re.search(r"合作快递[：:]\s*([^\n]+)", markdown)
    if m:
        rules["couriers"] = re.findall(r"中通|韵达|圆通|顺丰|申通|极兔", m.group(1))
    m = re.search(r"到货时间[：:].*?(\d)\s*-\s*(\d)\s*天", markdown)
    if m:
        rules["arrive_days"] = (int(m.group(1)), int(m.group(2)))
    if "不支持：货到付款" in markdown or "不支持货到付款" in markdown:
        rules["cod_forbidden"] = True
    pay = re.search(r"支持[：:]\s*([^\n]+)", markdown)
    if pay and "微信" in pay.group(1):
        rules["pay_supported"] = [p.strip() for p in re.split(r"[、,，]", pay.group(1)) if p.strip()]
    if "不支持纸质发票" in markdown:
        rules["paper_invoice"] = False
        rules["invoice_channel"] = "订单详情页" if "订单详情页" in markdown else None
    m = re.search(r"银卡会员[：:].*?满\s*(\d+)\s*元.*?(\d+)\s*折", markdown, re.S)
    if m:
        rules["silver_spend"] = int(m.group(1))
        rules["silver_discount"] = int(m.group(2))
    m = re.search(r"金卡会员[：:].*?满\s*(\d+)\s*元.*?(\d+)\s*折", markdown, re.S)
    if m:
        rules["gold_spend"] = int(m.group(1))
        rules["gold_discount"] = int(m.group(2))
    rules["coupon_full_reduce"] = [
        (int(a), int(b)) for a, b in re.findall(r"满\s*(\d+)\s*减\s*(\d+)", markdown)
    ]
    if "优惠券不叠加" in markdown:
        rules["coupon_stack"] = False
    m = re.search(r"在线客服[：:]\s*([0-9:：\-]+)", markdown)
    if m:
        rules["online_hours"] = m.group(1).replace("：", ":")
    m = re.search(r"电话客服[：:]\s*([0-9:：\-]+)", markdown)
    if m:
        rules["phone_hours"] = m.group(1).replace("：", ":")
    if "邮件客服" in markdown:
        rules["email_sla"] = True
    return rules


def _finding(
    article_id: str,
    issue_type: str,
    evidence: str,
    action: str,
    severity: str,
    suggestion: str,
) -> dict[str, Any]:
    meta = ISSUE_TYPES[issue_type]
    return {
        "id": article_id,
        "type": issue_type,
        "type_label": meta["label"],
        "severity": severity,
        "evidence": evidence,
        "action": action,
        "suggestion": suggestion,
        "impact": meta["impact"],
    }


def _claims_cod_supported(answer: str) -> bool:
    if "不支持货到付款" in answer or "暂不支持货到付款" in answer:
        return False
    return bool(re.search(r"支持.{0,8}货到付款|货到付款.{0,12}(支持|可以)", answer))


def _claims_all_merchant_freight(answer: str) -> bool:
    if re.search(r"非质量.{0,12}买家|质量问题.{0,12}商家", answer):
        return False
    return bool(
        re.search(
            r"所有退货.{0,12}(运费)?.{0,8}商家承担|退货运费(都)?由商家承担|运费商家承担",
            answer,
        )
    )


def _claims_30_day_no_reason(answer: str) -> bool:
    return bool(re.search(r"30\s*天无理由", answer)) and "质量问题" not in answer.split("30")[0][-8:]


def _claims_48h_as_sla(answer: str) -> bool:
    if re.search(r"(一般|通常).{0,6}24\s*小时", answer) and re.search(r"(大促|预售|延长).{0,12}48", answer):
        return False
    return bool(re.search(r"(下单后|付款后)?\s*48\s*小时内发货", answer))


def _claims_sf_primary(answer: str) -> bool:
    if "顺丰" not in answer:
        return False
    if re.search(r"不支持指定|系统(会)?自动分配", answer):
        return False
    return bool(re.search(r"(使用|用的是)?顺丰", answer))


def _claims_paper_invoice(answer: str) -> bool:
    return "纸质发票" in answer


def _claims_invoice_in_note(answer: str) -> bool:
    return bool(re.search(r"备注.{0,8}(发票|抬头)", answer))


def _wrong_member_thresholds(answer: str, rules: dict[str, Any]) -> str | None:
    bits = []
    silver = re.search(r"银卡.{0,24}满\s*(\d+)\s*元", answer)
    gold = re.search(r"金卡.{0,24}满\s*(\d+)\s*元", answer)
    if silver and rules.get("silver_spend") and int(silver.group(1)) != rules["silver_spend"]:
        bits.append(f"银卡门槛写 {silver.group(1)}，现行为 {rules['silver_spend']}")
    if gold and rules.get("gold_spend") and int(gold.group(1)) != rules["gold_spend"]:
        bits.append(f"金卡门槛写 {gold.group(1)}，现行为 {rules['gold_spend']}")
    sd = re.search(r"银卡.{0,40}?(\d+)\s*折", answer)
    gd = re.search(r"金卡.{0,40}?(\d+)\s*折", answer)
    if sd and rules.get("silver_discount") and int(sd.group(1)) != rules["silver_discount"]:
        bits.append(f"银卡折扣写 {sd.group(1)} 折，现行为 {rules['silver_discount']} 折")
    if gd and rules.get("gold_discount") and int(gd.group(1)) != rules["gold_discount"]:
        bits.append(f"金卡折扣写 {gd.group(1)} 折，现行为 {rules['gold_discount']} 折")
    return "；".join(bits) if bits else None


def _wrong_coupons(answer: str, rules: dict[str, Any]) -> str | None:
    pairs = [(int(a), int(b)) for a, b in re.findall(r"满\s*(\d+)\s*减\s*(\d+)", answer)]
    expected = set(tuple(p) for p in rules.get("coupon_full_reduce") or [])
    if pairs and expected and set(pairs) != expected:
        got = "、".join(f"满{a}减{b}" for a, b in pairs)
        exp = "、".join(f"满{a}减{b}" for a, b in sorted(expected))
        return f"券面额写 {got}，现行为 {exp}"
    return None


def _claims_stack_coupons(answer: str) -> bool:
    if "不叠加" in answer or "不可叠加" in answer:
        return False
    return bool(re.search(r"可以.{0,6}叠加|叠加使用|最多叠加", answer))


def _claims_247_online(answer: str) -> bool:
    return bool(re.search(r"7\s*[x×]\s*24|7x24|全天候|24\s*小时.{0,6}(在线|服务)", answer))


def _phone_workdays_only(answer: str) -> bool:
    return "电话" in answer and "工作日" in answer


def scan_articles(articles: list[dict[str, Any]], rules_md: str) -> dict[str, Any]:
    rules = parse_rules(rules_md)
    findings: list[dict[str, Any]] = []
    by_id = {str(a.get("id")): a for a in articles}

    for art in articles:
        aid = str(art.get("id") or "")
        answer = (art.get("answer") or "").strip()
        question = (art.get("question") or "").strip()
        if not answer:
            findings.append(
                _finding(
                    aid,
                    "empty",
                    f"问题「{question}」答案为空",
                    "补写",
                    "P0",
                    "按现行规则补全答案；暂时无法回答则下线该条目，避免空白命中。",
                )
            )
            continue

        if rules.get("cod_forbidden") and _claims_cod_supported(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"回复声称支持货到付款；现行规则不支持。原文：{answer[:80]}",
                    "修改",
                    "P0",
                    "改为明确不支持货到付款，并列出微信/支付宝/银行卡/花呗/信用卡。",
                )
            )
        if rules.get("no_reason_days") == 7 and _claims_30_day_no_reason(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"写成 30 天无理由退货；现行普通商品为 {rules['no_reason_days']} 天无理由。",
                    "修改",
                    "P0",
                    "改为 7 天无理由；质量问题单独写 30 天内可退换，运费按质量/非质量拆开。",
                )
            )
        if rules.get("non_quality_freight") == "buyer" and _claims_all_merchant_freight(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"写成所有退货运费商家承担；现行非质量问题运费由买家承担。原文：{answer[:80]}",
                    "修改",
                    "P0",
                    "改为：质量问题商家承担运费，非质量问题买家承担。",
                )
            )
        if rules.get("ship_hours") == 24 and _claims_48h_as_sla(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"发货 SLA 写成 48 小时；现行为下单后 {rules['ship_hours']} 小时内（预售除外）。",
                    "修改",
                    "P1",
                    "改为 24 小时内发货；预售以商品页为准，不要把 48 小时当默认。",
                )
            )
        official_couriers = rules.get("couriers") or []
        if official_couriers and _claims_sf_primary(answer) and "顺丰" not in official_couriers:
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"主快递写成顺丰；现行合作快递为 {'/'.join(official_couriers)}，系统自动分配。",
                    "修改",
                    "P1",
                    f"改为 { '、'.join(official_couriers) }，并说明不可指定。",
                )
            )
        if rules.get("paper_invoice") is False and _claims_paper_invoice(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"仍承诺纸质发票；现行仅支持电子发票。原文：{answer[:80]}",
                    "修改",
                    "P1",
                    "改为仅电子发票，申请入口为订单详情页，不要让用户写在备注里。",
                )
            )
        elif rules.get("invoice_channel") == "订单详情页" and _claims_invoice_in_note(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    "发票申请写成下单备注；现行为订单详情页申请。",
                    "修改",
                    "P1",
                    "指引改为：下单后在订单详情页申请电子发票，填写抬头和税号。",
                )
            )
        member_err = _wrong_member_thresholds(answer, rules)
        if member_err:
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    member_err,
                    "修改",
                    "P1",
                    f"银卡累计满 {rules.get('silver_spend')} 元享 {rules.get('silver_discount')} 折；"
                    f"金卡累计满 {rules.get('gold_spend')} 元享 {rules.get('gold_discount')} 折 + 优先客服。",
                )
            )
        coupon_err = _wrong_coupons(answer, rules)
        if coupon_err:
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    coupon_err,
                    "修改",
                    "P1",
                    "改成现行满减活动，并写明优惠券不可叠加。",
                )
            )
        if rules.get("coupon_stack") is False and _claims_stack_coupons(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"写成优惠券可叠加；现行不叠加。原文：{answer[:80]}",
                    "修改",
                    "P1",
                    "改为每笔订单优惠券不可叠加使用。",
                )
            )
        if _claims_247_online(answer):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"在线客服写成 7×24；现行 {rules.get('online_hours') or '9:00-22:00'}。",
                    "修改",
                    "P1",
                    f"改为在线客服 {rules.get('online_hours') or '9:00-22:00'}。",
                )
            )
        if _phone_workdays_only(answer) and rules.get("phone_hours"):
            findings.append(
                _finding(
                    aid,
                    "stale_conflict",
                    f"电话客服写成仅工作日；现行未限制工作日，时间为 {rules['phone_hours']}。",
                    "修改",
                    "P2",
                    f"改为电话客服 {rules['phone_hours']}（含周末，除非业务另行确认）。",
                )
            )

    qmap: dict[str, list[str]] = defaultdict(list)
    for art in articles:
        key = normalize_question(str(art.get("question") or ""))
        if key:
            qmap[key].append(str(art.get("id")))
    for _key, ids in qmap.items():
        if len(ids) < 2:
            continue
        sample_q = by_id[ids[0]].get("question")
        for aid in ids:
            findings.append(
                _finding(
                    aid,
                    "dup_question",
                    f"与 {', '.join(i for i in ids if i != aid)} 问句相同：「{sample_q}」",
                    "合并",
                    "P0",
                    "只保留一条且必须与现行规则一致；另一条删除或改成跳转。",
                )
            )

    freight_camps: dict[str, list[str]] = defaultdict(list)
    for art in articles:
        cat = str(art.get("category") or "")
        if "退货" not in cat:
            continue
        ans = str(art.get("answer") or "")
        if not ans.strip():
            continue
        if _claims_all_merchant_freight(ans):
            freight_camps["all_merchant"].append(str(art["id"]))
        elif re.search(r"非质量.{0,20}买家", ans):
            freight_camps["split"].append(str(art["id"]))
    if freight_camps["all_merchant"] and freight_camps["split"]:
        all_ids = freight_camps["all_merchant"] + freight_camps["split"]
        for aid in all_ids:
            findings.append(
                _finding(
                    aid,
                    "intra_conflict",
                    "退货运费口径互斥："
                    f"{', '.join(freight_camps['split'])} 按质量拆分，"
                    f"{', '.join(freight_camps['all_merchant'])} 写全部商家承担。",
                    "合并",
                    "P0",
                    "以现行规则（非质量买家 / 质量商家）为准，删掉全商家承担的写法。",
                )
            )

    coverage_gaps: list[dict[str, Any]] = []
    blob = "\n".join(str(a.get("answer") or "") + str(a.get("question") or "") for a in articles)
    if rules.get("email_sla") and "邮件" not in blob:
        coverage_gaps.append(
            {
                "type": "coverage_gap",
                "type_label": ISSUE_TYPES["coverage_gap"]["label"],
                "topic": "邮件客服",
                "action": "新增",
                "severity": "P2",
                "evidence": "现行规则有邮件客服（24 小时内回复），库中无对应条目。",
                "suggestion": "新增 FAQ：邮件客服如何联系、SLA 24 小时内回复。",
                "impact": ISSUE_TYPES["coverage_gap"]["impact"],
            }
        )
    if rules.get("invoice_channel") == "订单详情页" and not re.search(r"订单详情页.{0,12}发票|发票.{0,12}订单详情页", blob):
        coverage_gaps.append(
            {
                "type": "coverage_gap",
                "type_label": ISSUE_TYPES["coverage_gap"]["label"],
                "topic": "电子发票申请入口",
                "action": "新增",
                "severity": "P1",
                "evidence": "现行申请入口是订单详情页；现有发票条目未给出该路径（或仍在教备注/纸质）。",
                "suggestion": "新增或改写「怎么申请发票」：下单后订单详情页申请电子发票。",
                "impact": ISSUE_TYPES["coverage_gap"]["impact"],
            }
        )

    rank = {"P0": 0, "P1": 1, "P2": 2}
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for f in findings:
        key = (f["id"], f["type"])
        if key not in merged:
            merged[key] = dict(f)
            continue
        old = merged[key]
        if f["evidence"] not in old["evidence"]:
            old["evidence"] = f"{old['evidence']}；{f['evidence']}"
        if f["suggestion"] not in old["suggestion"]:
            old["suggestion"] = f"{old['suggestion']} {f['suggestion']}"
        if rank.get(f["severity"], 9) < rank.get(old["severity"], 9):
            old["severity"] = f["severity"]
        if f["action"] != old["action"] and f["action"] not in old["action"]:
            old["action"] = f"{old['action']}/{f['action']}"
    deduped = list(merged.values())

    flagged_ids = sorted({f["id"] for f in deduped})
    counts: dict[str, int] = defaultdict(int)
    for f in deduped:
        counts[f["type"]] += 1
    for g in coverage_gaps:
        counts[g["type"]] += 1

    return {
        "summary": (
            f"扫描 {len(articles)} 条，{len(flagged_ids)} 条有问题，"
            f"{len(deduped)} 条发现，{len(coverage_gaps)} 个覆盖缺口。"
        ),
        "article_count": len(articles),
        "flagged_article_count": len(flagged_ids),
        "flagged_ids": flagged_ids,
        "counts_by_type": dict(counts),
        "findings": deduped,
        "coverage_gaps": coverage_gaps,
        "issue_types": {
            k: {"label": v["label"], "impact": v["impact"]} for k, v in ISSUE_TYPES.items()
        },
    }


def load_articles(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path} must be a JSON array of articles")
    return raw


def scan_paths(corpus_path: Path, rules_path: Path) -> dict[str, Any]:
    articles = load_articles(corpus_path)
    rules_md = rules_path.read_text(encoding="utf-8")
    result = scan_articles(articles, rules_md)
    result["corpus_path"] = str(corpus_path)
    result["rules_path"] = str(rules_path)
    return result


def render_report(result: dict[str, Any]) -> str:
    counts = result.get("counts_by_type") or {}
    lines = [
        "# 知识库体检报告",
        "",
        "给业务方：以下为对现行规则的自动扫描结果，不是模型随口评价。",
        "",
        "## 摘要",
        "",
        result.get("summary", ""),
        "",
        f"- 扫描条目：{result.get('article_count')}",
        f"- 有问题的条目：{result.get('flagged_article_count')}（{', '.join(result.get('flagged_ids') or [])}）",
        "",
        "## 问题分类与影响",
        "",
        "| 类型 | 条数 | 业务影响 |",
        "|------|------|----------|",
    ]
    types = result.get("issue_types") or {
        k: {"label": v["label"], "impact": v["impact"]} for k, v in ISSUE_TYPES.items()
    }
    for key, meta in types.items():
        n = counts.get(key, 0)
        lines.append(f"| {meta['label']} (`{key}`) | {n} | {meta['impact']} |")
    lines += [
        "",
        "## 优先处理",
        "",
        "1. **P0**：空条目、货到付款/退货窗口/运费写错、同问重复、库内运费互斥 — 当天改。",
        "2. **P1**：发货时效、快递公司、发票、会员门槛、优惠券 — 本周改。",
        "3. **P2**：客服时段措辞、邮件客服缺口 — 排期补。",
        "",
        "## 问题条目",
        "",
    ]
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in result.get("findings") or []:
        by_id[f["id"]].append(f)
    if not by_id:
        lines.append("未检出条目级问题。")
    for aid in sorted(by_id):
        rows = by_id[aid]
        lines.append(f"### {aid}")
        lines.append("")
        for f in rows:
            lines.append(
                f"- **{f['type_label']}**（{f['severity']}）→ {f['action']}："
                f"{f['evidence']}"
            )
            lines.append(f"  - 建议：{f['suggestion']}")
        lines.append("")
    gaps = result.get("coverage_gaps") or []
    lines += ["## 覆盖缺口（需新增）", ""]
    if not gaps:
        lines.append("未检出覆盖缺口。")
    else:
        for g in gaps:
            lines.append(
                f"- **{g['topic']}**（{g['severity']}）→ {g['action']}：{g['evidence']}"
            )
            lines.append(f"  - 建议：{g['suggestion']}")
    lines += [
        "",
        "## 方法与局限",
        "",
        "- 检测是确定性规则（对照 `business_context.md` 的可解析条款 + 空答案 + 归一化同问 + 退货运费口径聚类），不在热路径上再调模型。",
        "- 规则里没写的内容（价保、保修细节、海外配送）**不会**仅仅因为「库里有、规则没有」被标过时。",
        "- 近义不同问（「多久能发货」vs「付款后多久能发货」）靠规则条款对齐，不靠 embedding；漏检近义互斥时应用检索补一刀。",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    findings_path = out_dir / "findings.json"
    report_path = out_dir / "report.md"
    findings_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    report_path.write_text(render_report(result), encoding="utf-8")
    return findings_path, report_path


async def audit_knowledge_base(
    corpus_path: str = "sources/kb/kb_articles.json",
    rules_path: str = "sources/kb/business_context.md",
    write_report: bool = True,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Tool handler: scan workspace files; optionally write drafts/kb-audit-report.md."""
    from app.tools.core.paths import _resolve_path, _workspace_root

    corpus = _resolve_path(corpus_path)
    rules = _resolve_path(rules_path)
    if not corpus.is_file():
        return {
            "status": "error",
            "summary": f"corpus not found: {corpus_path}",
            "error": "corpus_not_found",
        }
    if not rules.is_file():
        return {
            "status": "error",
            "summary": f"rules not found: {rules_path}",
            "error": "rules_not_found",
        }
    result = scan_paths(corpus, rules)
    result["status"] = "ok"
    if write_report:
        report_rel = Path("drafts") / "kb-audit-report.md"
        dest = _workspace_root() / report_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_report(result), encoding="utf-8")
        result["report_path"] = str(report_rel)
    # Keep tool_result budget-friendly: full findings stay, summary is first.
    return result
