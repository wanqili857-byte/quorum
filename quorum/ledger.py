"""处置台账的**可执行化**：把「✅ 已修」从声明变成断言。

痛点（真实）：复核处置台账里每一行都是手写的「✅ 已修」，而没有任何东西验证过它。
下一轮复核去做这件事时，会发现相当一部分 ✅ 站不住。台账越厚，这个缺口越大。

做法：每行可以挂一条 `check` —— 一条**能失败的** shell 命令。``quorum verify`` 全部跑一遍，
最要命的输出不是「失败」，而是 **status=✅ 而 check 失败**（= 台账在说谎）。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

OK_MARKS = ("✅", "☑", "✔")
TODO_MARKS = ("⬜", "❌", "🚧")


@dataclass
class Entry:
    index: str
    status: str
    check: str
    problem: str = ""
    location: str = ""


@dataclass
class Verdict:
    entry: Entry
    ran: bool
    rc: Optional[int]
    output: str

    @property
    def is_ok_status(self) -> bool:
        return any(m in self.entry.status for m in OK_MARKS)

    @property
    def verdict(self) -> str:
        if not self.entry.check.strip():
            return "no-check"                    # 无法验证
        if not self.ran:
            return "error"
        if self.is_ok_status and self.rc != 0:
            return "LIE"                         # 台账说已修，断言说没修 —— 唯一不可接受的档
        if not self.is_ok_status and self.rc == 0:
            return "stale"                       # 其实已经好了，台账没更新
        return "ok" if self.rc == 0 else "pending"


def parse(path: str) -> List[Entry]:
    if not os.path.exists(path):
        return []
    entries: List[Entry] = []
    header: List[str] = []
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if any(c in ("check", "check 命令", "断言") for c in cells):
            header = [c.lower() for c in cells]
            continue
        if not header or set("".join(cells)) <= set("-: "):
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        row = dict(zip(header, cells))
        check = row.get("check") or row.get("check 命令") or row.get("断言") or ""
        check = check.strip()
        if check.startswith("`") and check.endswith("`"):
            check = check[1:-1]
        entries.append(Entry(
            index=row.get(" #") or row.get("#") or str(len(entries) + 1),
            status=row.get("status") or row.get("状态") or "",
            check=check,
            problem=row.get("问题", ""),
            location=row.get("位置", ""),
        ))
    return entries


def run_checks(entries: List[Entry], cwd: str, timeout_s: int = 120) -> List[Verdict]:
    out: List[Verdict] = []
    for e in entries:
        if not e.check.strip():
            out.append(Verdict(e, False, None, ""))
            continue
        try:
            p = subprocess.run(["bash", "-lc", e.check], cwd=cwd, capture_output=True,
                               text=True, timeout=timeout_s)
            out.append(Verdict(e, True, p.returncode, (p.stdout + p.stderr).strip()[-600:]))
        except subprocess.TimeoutExpired:
            out.append(Verdict(e, False, None, "超时 %ds" % timeout_s))
        except OSError as ex:
            out.append(Verdict(e, False, None, str(ex)))
    return out


def render(verdicts: List[Verdict]) -> str:
    lines = ["| # | status | check | 判定 | 输出（截断） |", "|---|---|---|---|---|"]
    for v in verdicts:
        mark = {"LIE": "🔴 台账说谎", "stale": "🟡 台账未更新", "no-check": "⚪ 无断言",
                "ok": "✅", "pending": "⬜ 未修", "error": "🔴 执行失败"}[v.verdict]
        out = (v.output or "").replace("\n", " ").replace("|", "\\|")[:160]
        lines.append("| %s | %s | `%s` | %s | %s |" % (
            v.entry.index, v.entry.status or "-", (v.entry.check or "-")[:70], mark, out))
    n_lie = sum(1 for v in verdicts if v.verdict == "LIE")
    n_nocheck = sum(1 for v in verdicts if v.verdict == "no-check")
    lines += ["", "合计 %d 条：**台账说谎 %d** · 无断言 %d · 未修 %d · 已修 %d"
              % (len(verdicts), n_lie, n_nocheck,
                 sum(1 for v in verdicts if v.verdict == "pending"),
                 sum(1 for v in verdicts if v.verdict == "ok"))]
    if n_nocheck:
        lines.append("（无断言的行不算修好——它们只是「作者说修好了」）")
    return "\n".join(lines)


def exit_code(verdicts: List[Verdict], strict: bool = False) -> int:
    """默认只在「台账说谎」时非零。`--strict` 把「无断言」也算失败。"""
    if any(v.verdict in ("LIE", "error") for v in verdicts):
        return 1
    if strict and any(v.verdict == "no-check" for v in verdicts):
        return 1
    return 0
