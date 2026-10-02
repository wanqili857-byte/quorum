"""交叉表：把几家审核员的发现对齐成一张表——**一致** / **独有** / **被推翻**。

为什么这是核心：单个审核员会错，而且错得不显眼。真实案例——某次三个审核员里有一个
断言「在役权重其实是上一版」，语气肯定、给了命令；是另一个审核员用逐字节 ``cmp`` 把它推翻了。
不做交叉就会照单全收。

对齐是**启发式**的，不是魔法：位置里的路径 token + 问题文本的字符二元组相似度。
输出刻意保守——宁可把同一条拆成两条（你去合并），也不要把两条不相干的合成一条（你去拆）。
所以每条都带「怎么对上的」，并且**留一列复验结论给你填**。
"""
from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import Config
from .gates import clip_cell, read_text, severity_of, split_table_rows

PATH_RE = re.compile(r"[\w./\-]+\.(?:py|md|json|jsonl|ya?ml|ipynb|sh|txt|toml|cfg)")
NOISE = set(" 　\t\n:：。，,、（）()「」【】*`>|/\\-_'\"…")


def _uniq(seq) -> List[str]:
    """保序去重（两轴都用它：vendor 与 harness 的取值集合）。"""
    seen: List[str] = []
    for x in seq:
        if x not in seen:
            seen.append(x)
    return seen


def _paths(text: str) -> set:
    out = set()
    for m in PATH_RE.findall(text or ""):
        out.add(m.rsplit("/", 1)[-1])            # 只比文件名，跨审核员的目录写法常不同
    return out


NUM_RE = re.compile(r"\d+(?:\.\d+)?")
ID_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]{2,}")


def _tokens(text: str) -> set:
    """显著词集合：数字、标识符/代码词、以及字符二元组。

    单靠字符二元组分不开——实测同一条发现的两份措辞相似度 0.138，而**不同**的两条也有 0.120，
    几乎没有分离度。加进数字与标识符后再做 IDF 加权，同一条升到 0.14–0.21、不同条落到 ≤0.06。
    """
    t = set(NUM_RE.findall(text or ""))
    t |= {x.lower() for x in ID_RE.findall(text or "")}
    clean = "".join(ch for ch in (text or "") if ch not in NOISE)
    t |= {clean[i:i + 2] for i in range(len(clean) - 1)}
    return t


def _idf_weighter(all_tokens: List[set]):
    n = max(1, len(all_tokens))
    df: Dict[str, int] = {}
    for t in all_tokens:
        for x in t:
            df[x] = df.get(x, 0) + 1

    def weight(x: str) -> float:
        return math.log(1.0 + n / df.get(x, 1))

    return weight


def _weighted_jaccard(a: set, b: set, weight) -> float:
    if not a or not b:
        return 0.0
    inter = sum(weight(x) for x in a & b)
    union = sum(weight(x) for x in a | b)
    return inter / union if union else 0.0


@dataclass
class Row:
    reviewer: str
    vendor: str            # 模型来源（声明）
    harness: str           # agent 框架（事实，从通道推出）
    severity: str
    location: str
    problem: str
    evidence: str
    role: str = "primary"

    @property
    def sev_rank(self) -> int:
        return severity_of(self.severity)


@dataclass
class Cluster:
    rows: List[Row] = field(default_factory=list)
    why: str = ""
    members: List[int] = field(default_factory=list)

    @property
    def disagreement(self) -> str:
        """同簇各家措辞/归因的**分歧程度**。

        合并只说明「说的是同一处」，不说明「结论相同」——而汇总表只印一句话，
        读者很容易把一簇当成一个结论。真实案例：一簇里三家里有一家**归因是错的**。
        这里给出一个粗粒度信号，让读者知道该不该逐条细读。
        """
        if len(self.rows) < 2:
            return ""
        toks = [_tokens(r.location + " " + r.problem) for r in self.rows]
        weight = _idf_weighter(toks)
        sims = [_weighted_jaccard(toks[i], toks[j], weight)
                for i in range(len(toks)) for j in range(i + 1, len(toks))]
        avg = sum(sims) / len(sims) if sims else 0.0
        # 阈值必须落在「同一条发现」的相似度区间**之上**才有区分力。
        # 标定（见 _tokens）：同一条的两份措辞 0.14–0.21，不同条 ≤0.06。
        # 旧阈值 0.20 正好落在这个区间里 —— 于是它既报不出真分歧，也拦不住假一致。
        if avg < 0.30:
            return "⚠️ 各家归因可能不同（平均相似度 %.2f < 0.30）——**逐条读原话**" % avg
        return "各家措辞接近（平均相似度 %.2f）" % avg

    @property
    def reviewers(self) -> List[str]:
        return [r.reviewer for r in self.rows]

    @property
    def vendors(self) -> List[str]:
        return _uniq(r.vendor for r in self.rows)

    @property
    def harnesses(self) -> List[str]:
        return _uniq(r.harness for r in self.rows)

    @property
    def severity(self) -> str:
        top = max(self.rows, key=lambda r: r.sev_rank)
        return top.severity

    @property
    def primary_vendors(self) -> List[str]:
        # CONTRACT：**cross 的结论不计入「跨模型族一致」**。
        # 旧版只看 len(families)，于是被标成 cross 的审核员照样把置信度抬高一档。
        return _uniq(r.vendor for r in self.rows if r.role == "primary")

    @property
    def primary_harnesses(self) -> List[str]:
        """primary 审核员用到的 harness。**这是第二个独立轴**，不是 vendor 的别名。

        两家 vendor 走同一个 harness 时，它们的共识可能来自 harness 本身
        （同一套 system prompt、同一套工具、同一种「读文件—找证据—列表格」的套路），
        而不是来自两个独立模型。见 `label()`。
        """
        return _uniq(r.harness for r in self.rows if r.role == "primary")

    def label(self) -> str:
        n_rev = len(self.reviewers)
        n_v = len(self.primary_vendors)
        n_h = len(self.primary_harnesses)
        if n_rev == 1:
            return "单家独有 · 待复验"
        if n_v >= 2:
            # 两个轴分开说：vendor 跨了几家、harness 是不是只有一种。
            # 只有 vendor 那一维时，「跨模型族一致」是对的，但读者会顺手读成
            # 「两个独立来源互相印证」——而它们在 harness 这一维上可能根本不独立。
            # 所以这里**加注记而不降级**：模型层的独立是真的，抹掉是过度惩罚。
            if n_h == 1:
                return ("跨模型族一致 · 高置信（注：primary 同走 %s 这一个 harness，"
                        "共识可能来自 harness 而非模型）" % self.primary_harnesses[0])
            return "跨模型族一致 · 高置信（两轴皆跨：%d vendor × %d harness）" % (n_v, n_h)
        if n_v == 1 and n_h >= 2:
            # 反向的不独立：换 harness 不换模型，盲区还是共享的。
            return ("同一 vendor · 仅 harness 不同（%s）——同权重同盲区，"
                    "独立性只来自 harness" % "、".join(self.primary_harnesses))
        if n_v == 1:
            return "含交叉 · 中置信（仅一家 primary vendor）"
        return "仅交叉审核员 · 待复验"

    def headline(self) -> str:
        return self.rows[0].problem


def collect(cfg: Config) -> Tuple[List[Row], Dict[str, str]]:
    rows: List[Row] = []
    snaps: Dict[str, str] = {}
    for r in cfg.reviewers:
        p = cfg.out_path(r.name)
        text = read_text(p)
        if not text:
            continue
        # 只认 runner 写在头部的**机器可读标记**。旧版用 `材料快照：\`([^\`]+)\`` 全篇扫描、
        # 后者覆盖前者 —— 审核员只要在正文里写一行同格式文本，就能把真快照盖掉、
        # 从而**关掉 plate 的快照不一致告警**。
        m = re.search(r"<!--\s*quorum:snapshot\s+(\S+)\s*-->", text)
        if not m:
            m = re.search(r"材料快照：`([^`]+)`", text.split("\n---\n")[0])
        if m:
            snaps[r.name] = m.group(1)
        else:
            snaps[r.name] = "（该结论无快照标记）"
        for sev, loc, prob, ev in split_table_rows(text):
            rows.append(Row(r.name, r.vendor, r.harness, sev, loc, prob, ev, r.role))
    return rows, snaps


def cluster(rows: List[Row], thr_same_file: float = 0.07, thr_text: float = 0.10) -> List[Cluster]:
    """把不同审核员的发现对齐。**启发式**：宁可拆细，不要合错。

    阈值是标定出来的（见 `_tokens` 的注释）：同一条发现的两份措辞落在 0.14–0.21，
    不同条落在 ≤0.06。位置指向同一文件时把门槛放低（0.07）——审核员的措辞差异通常比文件路径大。
    """
    tokens = [_tokens(r.location + " " + r.problem) for r in rows]
    weight = _idf_weighter(tokens)
    clusters: List[Cluster] = []
    for idx, row in enumerate(rows):
        best: Optional[Cluster] = None
        best_score = 0.0
        best_same_file = False
        for c in clusters:
            if row.reviewer in c.reviewers:
                continue                      # 同一家的两条不合并（他自己分开写的就是两件事）
            for other_idx in c.members:
                sf = bool(_paths(row.location) & _paths(rows[other_idx].location))
                sc = _weighted_jaccard(tokens[idx], tokens[other_idx], weight)
                if (sf and sc >= thr_same_file) or sc >= thr_text:
                    score = sc + (0.05 if sf else 0.0)
                    if score > best_score:
                        best, best_score, best_same_file = c, score, sf
        if best is not None:
            best.members.append(idx)
            best.rows.append(row)
            best.why = ("同文件 + 相似度 %.2f" % best_score) if best_same_file else ("相似度 %.2f" % best_score)
        else:
            c = Cluster([row])
            c.members = [idx]
            clusters.append(c)
    clusters.sort(key=lambda c: (-len(c.primary_vendors), -len(c.primary_harnesses),
                                 -len(c.reviewers),
                                 -max(r.sev_rank for r in c.rows)))
    return clusters


def render(cfg: Config, clusters: List[Cluster], snaps: Dict[str, str]) -> str:
    got = [r.name for r in cfg.reviewers if os.path.exists(cfg.out_path(r.name))]
    out: List[str] = ["# %s · 交叉表" % cfg.project, ""]
    out.append("> 已收结论：%s%s" % (", ".join(got) or "（无）",
                                    "· 缺：" + ", ".join(r.name for r in cfg.reviewers if r.name not in got)
                                    if len(got) < len(cfg.reviewers) else ""))
    if len(set(snaps.values())) > 1:
        out.append("> 🔴 **材料快照不一致**——各家审的不是同一份材料，对齐结果不可当真：%s"
                   % json.dumps(snaps, ensure_ascii=False))
    elif snaps:
        out.append("> 材料快照一致：`%s`" % list(snaps.values())[0])

    # 两个来源轴单独摆出来。这是交叉表的**元信息**，不是细节：
    # 「vendor 跨了几家」和「harness 跨了几种」是两回事，而后者决定前者值多少。
    out.append("> 来源轴：%s" % " · ".join(
        "%s[%s @ %s / %s]" % (r.name, r.vendor, r.harness, r.role) for r in cfg.reviewers))
    prim = [r for r in cfg.reviewers if r.role == "primary"]
    if len(prim) >= 2:
        if len({r.harness for r in prim}) == 1 and len({r.vendor for r in prim}) >= 2:
            out.append("> ⚠️ primary 的 vendor 不同，但**全走同一个 harness**（`%s`）——"
                       "它们的一致可能来自 harness（同一套 system prompt / 工具 / 套路），"
                       "而非来自两个独立模型。" % prim[0].harness)
        elif len({r.vendor for r in prim}) == 1 and len({r.harness for r in prim}) >= 2:
            out.append("> ⚠️ primary 全是同一 vendor（`%s`）——换 harness 不换模型，"
                       "盲区仍然共享，独立性只来自 harness。" % prim[0].vendor)
    out += ["", "## 汇总", "",
            "| # | 一致度 | 严重度 | 位置 | 一句话 | 哪几家 |", "|---|---|---|---|---|---|"]
    for i, c in enumerate(clusters, 1):
        out.append("| %d | %s | %s | %s | %s | %s |" % (
            i, c.label(), c.severity, clip_cell(c.rows[0].location, 50),
            clip_cell(c.headline(), 80), "+".join(c.reviewers)))

    out += ["", "## 明细（**每家原话都列出来**——合并只说明「说的是同一处」，不说明「结论相同」）", ""]
    for i, c in enumerate(clusters, 1):
        out.append("### %d. %s · %s · 位置 `%s`" % (
            i, c.severity, c.label(), clip_cell(c.rows[0].location, 60).replace("`", "")))
        out.append("")
        for r in c.rows:
            out.append("- **%s**（%s @ %s）：%s" % (r.reviewer, r.vendor, r.harness,
                                                    r.problem.strip()))
            if r.evidence.strip():
                out.append("  - 证据：%s" % r.evidence.strip()[:300])
        out.append("")
        if c.disagreement:
            out.append("  - %s" % c.disagreement)
        out.append("  - 复验：⬜（填 `confirmed` / `refuted` / `partial` + 一句证据）")
        out.append("")

    out += ["## 读法", "",
            "- **两个来源轴要分开读**：`vendor`（模型是谁训的，**声明**）与 `harness`"
            "（哪个 agent CLI 在跑它，**事实**）。一致性只在**两轴都跨**时才等于「两个独立来源互相印证」。",
            "- **跨模型族一致** = 不同 vendor 的模型独立得出同一结论，最值得先看；"
            "但若它们同走一个 harness，共识可能来自 harness 本身——表头会注记。",
            "- **同一 vendor · 仅 harness 不同** = 换了外壳没换模型，盲区还是共享的，独立性有限。",
            "- **单家独有** = 未必错，也未必对。真实案例里，被推翻的那条正是单家独有。",
            "- 同一簇里各家的**措辞与归因可能不同**（甚至相反）——所以明细逐条列原话，别只看汇总的一句话。",
            "- 「复验」由作者填：**审核员的结论是断言，不是事实**。",
            "- 对齐是启发式（IDF 加权词重叠，同文件降门槛）：宁可拆细，不要合错。该合并的手工合并。",
            ""]
    return "\n".join(out)


def to_json(clusters: List[Cluster], snaps: Dict[str, str]) -> str:
    """输出契约的机器可读形态（拿它接你自己的流程，不需要 import 这个包）。"""
    return json.dumps({
        "snapshots": snaps,
        "findings": [{
            "id": i,
            "confidence": c.label(),
            "severity": c.severity,
            "location": c.rows[0].location,
            "problem": c.headline(),
            "reviewers": c.reviewers,
            "vendors": c.vendors,
            "harnesses": c.harnesses,
            "match_reason": c.why,
            "disagreement": c.disagreement,
            "primary_vendors": c.primary_vendors,
            "primary_harnesses": c.primary_harnesses,
            "sources": [{"reviewer": r.reviewer, "evidence": r.evidence} for r in c.rows],
        } for i, c in enumerate(clusters, 1)],
    }, ensure_ascii=False, indent=2)


def dispose_skeleton(cfg: Config, clusters: List[Cluster]) -> str:
    """处置台账骨架——审核的下半场。`check` 列填一条 shell 命令，`quorum verify` 会跑它。"""
    out = ["# %s · 复核处置台账" % cfg.project, "",
           "> 填法：`处置` 写改了什么；`check` 填一条**能失败的**命令（退出 0 才算修好）；",
           "> `status` 填 ⬜/✅/❌。`quorum verify` 会跑所有 check，把 ✅ 变成可证伪的断言。", "",
           "| # | 置信度 | 严重度 | 位置 | 问题 | 处置 | check | status |",
           "|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(clusters, 1):
        out.append("| %d | %s | %s | %s | %s | | | ⬜ |" % (
            i, c.label(), c.severity, clip_cell(c.rows[0].location, 50),
            clip_cell(c.headline(), 100)))
    return "\n".join(out) + "\n"
