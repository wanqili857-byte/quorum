"""台账说谎记录：``verify`` 判出 🔴 时自动落盘的**事实**档案。

与 ``docs/LESSONS.md`` 的分工（重要，别混成一个）：

- ``LESSONS.md`` = **判断** —— 这条事故是什么、叫什么、跟哪条旧教训是同一类。**人写**。
- 本模块产出的档案 = **事实** —— 哪一行、哪条命令、真实输出、材料快照。**机器写**。

**事实自动落盘，判断留给人。** 这正是 quorum 自己的取向：机器负责"一定会留痕"，
人负责"这条算不算一件事"。

⚠️ **只记 ``LIE``**（status 写着 ✅ 而 check 跑不过 —— 唯一不可接受的一档）。
``error`` 档（命令根本没跑起来：超时、环境缺工具）**默认不记**：它常常属于
「门禁的结果取决于跑它的机器」那一类，混进事故档案会把真事故淹掉 ——
同 ``docs/LESSONS.md``「假警报淹没真警报」。要记就显式开 ``--incidents-include-error``。

⚠️ 写入必须走 ``gates.atomic_write``，**不许裸 ``open(path, "w")``**：那正是
``docs/LESSONS.md`` 事故二的写法，而 ``plate --dispose`` 已经栽过一次。
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from typing import Dict, List, Tuple

from . import gates
from .gates import clip_cell
from .ledger import Verdict

COLUMNS = ["key", "首次", "最近", "次数", "台账", "行", "status", "check", "rc", "输出", "快照"]

TITLE = "台账说谎记录"
NOTE = ("本文件由 `quorum verify` 自动写入：每一条 = 一次「status 写着 ✅，`check` 却跑不过」。\n"
        "这里只放**事实**（哪一行、哪条命令、真实输出、材料快照）；**判断**（这条算不算一次事故、"
        "叫什么名字、跟哪条旧教训同类）仍写在 `docs/LESSONS.md`。\n"
        "同一行反复红**不追加新行**，只更新「最近」与「次数」——避免假警报淹没真警报。")


def _cell(s: str, limit: int = 160) -> str:
    """写进 markdown 单元格：换行压平、竖线转义、按显示宽度裁剪。

    竖线不转义会把一行切成两行（表格错位），而错位是静默的 —— 解析回来的列会串位。
    """
    s = clip_cell((s or "").replace("\r", " ").replace("\n", " "), limit)
    return s.replace("|", "\\|")


def key_for(ledger_path: str, entry, repo: str = "") -> str:
    """稳定标识：**台账 + 命令原文**。

    **行号不参与哈希**（只作显示，并在每次更新时刷新）。行号会随台账增删整体漂移——
    把它算进 key，中间插一行就会让下面每一条都变成"新事故"，去重立刻失效、档案变流水账。
    命令是这一行的**语义**：命令改了就是另一条断言，理应算新的一条。

    台账路径先转成相对 ``repo`` 的形式：换台机器、换挂载点，同一份台账仍得到同一个 key。
    """
    led = ledger_path
    if repo:
        try:
            rel = os.path.relpath(os.path.abspath(led), repo)
            if not rel.startswith(".."):
                led = rel
        except ValueError:
            pass
    raw = "%s\x00%s" % (led, entry.check.strip())
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def _load(path: str) -> Dict[str, Dict[str, str]]:
    """读回已有档案。**复用 `gates._split_row`**，不另写一套切分。"""
    rows: Dict[str, Dict[str, str]] = {}
    if not os.path.exists(path):
        return rows
    header: List[str] = []
    for line in open(path, encoding="utf-8"):
        if not line.strip().startswith("|"):
            header = []
            continue
        cells = gates._split_row(line)
        if any(c.strip("*` ").lower() == "key" for c in cells):
            header = [c.strip("*` ").lower() for c in cells]
            continue
        if not header or set("".join(cells)) <= set("-: "):
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        row = dict(zip(header, cells))
        k = (row.get("key") or "").strip("` ")
        if k:
            rows[k] = row
    return rows


def _output_of(v: Verdict) -> str:
    head = "" if v.rc is None else "rc=%d " % v.rc
    return (head + (v.output or "")).strip()


def record(verdicts: List[Verdict], ledger_path: str, path: str,
           repo: str = "", snapshot_fp: str = "",
           include_error: bool = False) -> Tuple[int, int]:
    """把这一轮判出的 🔴 落进档案。返回 (新增, 更新)。

    **没有 🔴 时不建文件、不写文件** —— 一个空的"事故档案"会让人以为"今天没事故"，
    而它其实只说明"这条路径没被写过"。同 §「没查到问题」和「没查」必须长得不一样。
    """
    rows = _load(path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    new = upd = 0
    for v in verdicts:
        if v.verdict != "LIE" and not (include_error and v.verdict == "error"):
            continue
        k = key_for(ledger_path, v.entry, repo)
        rc = "" if v.rc is None else str(v.rc)
        if k in rows:
            r = rows[k]
            try:
                r["次数"] = str(int(r.get("次数") or "1") + 1)
            except ValueError:                       # 档案被手改坏了也别炸
                r["次数"] = "2"
            r["最近"] = now
            # 行号会漂移（台账增删），所以每次都按**当前**这一份刷新它，别留着旧行号骗人
            r["行"] = _cell(str(v.entry.index), 20)
            r["台账"] = _cell(ledger_path, 80)
            r["status"] = _cell(v.entry.status or "-", 20)
            r["rc"] = rc
            r["输出"] = _cell(_output_of(v))
            if snapshot_fp:
                r["快照"] = _cell(snapshot_fp, 80)
            upd += 1
        else:
            rows[k] = {
                "key": "`%s`" % k, "首次": now, "最近": now, "次数": "1",
                "台账": _cell(ledger_path, 80), "行": _cell(str(v.entry.index), 20),
                "status": _cell(v.entry.status or "-", 20),
                "check": "`%s`" % _cell(v.entry.check, 120),
                "rc": rc, "输出": _cell(_output_of(v)),
                "快照": _cell(snapshot_fp, 80),
            }
            new += 1
    if new or upd:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        gates.atomic_write(path, render(rows))
    return new, upd


def render(rows: Dict[str, Dict[str, str]]) -> str:
    lines = ["# %s" % TITLE, "", "> " + NOTE.replace("\n", "\n> "), "", "| " + " | ".join(COLUMNS) + " |",
             "|" + "|".join(["---"] * len(COLUMNS)) + "|"]
    for r in rows.values():
        lines.append("| " + " | ".join(r.get(c, "") for c in COLUMNS) + " |")
    lines += ["", "合计 %d 条。" % len(rows)]
    return "\n".join(lines) + "\n"
