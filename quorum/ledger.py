"""处置台账的**可执行化**：把「✅ 已修」从声明变成断言。

痛点（真实）：复核处置台账里每一行都是手写的「✅ 已修」，而没有任何东西验证过它。
下一轮复核去做这件事时，会发现相当一部分 ✅ 站不住。台账越厚，这个缺口越大。

做法：每行可以挂一条 `check` —— 一条**能失败的** shell 命令。``quorum verify`` 全部跑一遍，
最要命的输出不是「失败」，而是 **status=✅ 而 check 失败**（= 台账在说谎）。
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

from .gates import clip_cell          # markdown 单元格裁剪（防未闭合代码段把行切错位）

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
    r"""解析台账表。

    **不重写切分逻辑**：与发现表共用 `gates._split_row`（转义 `\|`、反引号内竖线都不分隔）。
    这里曾经是裸 `split("|")` —— 同一份输出契约的两处解析各写一套，是下一类静默错位。
    """
    if not os.path.exists(path):
        return []
    from .gates import _split_row          # 单一实现
    entries: List[Entry] = []
    header: List[str] = []
    for line in open(path, encoding="utf-8"):
        if not line.strip().startswith("|"):
            header = []                     # 表格结束 → 表头作废
            continue
        cells = _split_row(line)
        if any(c.strip("*` ").lower() in ("check", "check 命令", "断言") for c in cells):
            header = [c.strip("*` ").lower() for c in cells]
            continue
        if not header or set("".join(cells)) <= set("-: "):
            continue
        # 说明性表格（没有 status/状态 列）不该被当成台账行——台账的列是有契约的
        if not any(c in header for c in ("status", "状态")):
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        row = dict(zip(header, cells))
        raw_check = (row.get("check") or row.get("check 命令") or row.get("断言") or "").strip()
        check = raw_check[1:-1] if raw_check.startswith("`") and raw_check.endswith("`") else raw_check
        entries.append(Entry(
            index=row.get(" #") or row.get("#") or str(len(entries) + 1),
            status=row.get("status") or row.get("状态") or "",
            check=check,
            problem=row.get("问题", ""),
            location=row.get("位置", ""),
        ))
    return entries


def _check_env(cwd: str = "") -> dict:
    r"""跑 check 用的环境。

    事故一：`verify` 从头到尾没报错，却把 11 条 ✅ 判成「台账说谎」。真因不是台账说谎，
    是 `bash -lc` 继承的 PATH 里没有 `pytest`（quorum 装在 venv 里，venv 没 activate）。
    **同一个仓库、同一份台账，换台机器结论就变**——正是 docs/LESSONS.md 里
    「门禁的结果不该取决于跑它的机器」那一条，只不过这次踩的是自己的 `verify`。

    当时的改法是「把**跑 quorum 的那个解释器**的 bin 放到 PATH 最前」。**那只堵了一半**：
    quorum 以 `uv tool`（隔离 env）安装时，那个 bin 里没有 pytest；
    而以 `pip install -e '.[dev]'`（CI 的装法）安装时，pytest 恰好同 env，于是 CI 绿、本地红。
    **同一份台账，CI 判 0 说谎、本地判 12 说谎。**

    现在按优先级拼三段，缺哪段就跳过哪段：

    1. **被审项目自己的** `.venv/bin`——check 要跑的是**项目**的工具（pytest、ruff…），
       它们该由项目的环境提供，不是由 quorum 的环境提供；
    2. 跑 quorum 的那个解释器的 bin（`sys.executable`）——保住原来的语义；
    3. 继承来的 PATH。

    环境仍然可能缺工具，但**缺哪一段是可解释的**：check 写 `pytest`，就该能在
    项目 venv 里找到；找不到说明这个项目没装 dev 依赖，而不是「门禁看运气」。
    """
    env = dict(os.environ)
    parts: List[str] = []
    if cwd:
        venv = os.path.join(cwd, ".venv", "bin")
        if os.path.isdir(venv):
            parts.append(venv)
    parts.append(os.path.dirname(os.path.abspath(sys.executable)))
    env["PATH"] = os.pathsep.join(parts + [env.get("PATH", "")])
    return env


def run_checks(entries: List[Entry], cwd: str, timeout_s: int = 120) -> List[Verdict]:
    out: List[Verdict] = []
    env = _check_env(cwd)
    for e in entries:
        if not e.check.strip():
            out.append(Verdict(e, False, None, ""))
            continue
        try:
            p = subprocess.run(["bash", "-lc", e.check], cwd=cwd, capture_output=True,
                               text=True, timeout=timeout_s, env=env)
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
        out = clip_cell((v.output or "").replace("\n", " "), 160)
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
    if n_nocheck == len(verdicts) and verdicts:
        lines.append("⚠️ **这份台账一条断言都没有**：`verify` 在这种情况下的绿灯**什么都不证明**。"
                     "跑 `verify --strict` 会把它判失败。")
    return "\n".join(lines)


def exit_code(verdicts: List[Verdict], strict: bool = False) -> int:
    """默认只在「台账说谎」时非零。`--strict` 把「无断言」也算失败。"""
    if any(v.verdict in ("LIE", "error") for v in verdicts):
        return 1
    if strict and any(v.verdict == "no-check" for v in verdicts):
        return 1
    return 0
