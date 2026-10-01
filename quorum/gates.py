"""门禁：判一份审核结论「能不能算数」。

三条从实战里换来的规则（`docs/LESSONS.md` 有完整来龙去脉）：

1. **内容优先于退出码。** 进程退出码描述的是进程，不是材料。我们真实吃过：
   两份结构完整、内容齐全的结论因为收尾时收到 SIGTERM（rc=143）被判「失败」而改名。
2. **损坏一份已有结论，比不产出更糟。** 结论一律先写临时文件、四门全过再原子落位；
   已有非空结论先自动留档，绝不原地覆盖。（我们在测试看门狗时截断过一份真结论。）
3. **必须有超时看门狗。** 没有它，「审核员挂了」与「审核员还在想」在外部看起来完全一样。
   （我们真实吃过：一次连接死等，空跑 5 小时。）
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from .config import Config

SEVERITY_RE = re.compile(r"🔴|🟡|🟢|\[高\]|\[中\]|\[低\]")


@dataclass
class GateResult:
    passed: bool
    size: int
    marks: int
    missing_sections: List[str]
    rc: int
    seconds: int

    def summary(self) -> str:
        return ("%dB · 严重度标记 %d · 缺章节 %s · rc=%d · %ds"
                % (self.size, self.marks, self.missing_sections or "无", self.rc, self.seconds))


def evaluate(cfg: Config, text: str, rc: int, seconds: int) -> GateResult:
    marks = len(SEVERITY_RE.findall(text))
    missing = [s for s in cfg.gates.require_sections if s not in text]
    passed = (len(text.encode()) >= cfg.gates.min_bytes
              and marks >= cfg.gates.min_severity_marks
              and not missing)
    return GateResult(passed, len(text.encode()), marks, missing, rc, seconds)


def run_with_timeout(argv: List[str], env: Dict[str, str], timeout_s: int,
                     stdout_path: str, stderr_path: str, cwd: str = "") -> int:
    """起进程 + 看门狗。返回退出码（信号也算，由调用方判断是否影响「内容」）。

    ``cwd`` 一律传**项目根**：审核员的工作目录就是被审项目本身。
    （也顺带让配置里的相对路径与命令行参数在任何 CWD 下都成立。）"""
    full_env = os.environ.copy()
    full_env.update(env)
    with open(stdout_path, "wb") as so, open(stderr_path, "wb") as se:
        proc = subprocess.Popen(argv, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                env=full_env, cwd=cwd or None)
        deadline = time.time() + timeout_s
        while proc.poll() is None:
            if time.time() > deadline:
                with open(stderr_path, "ab") as f:
                    f.write(("\n[看门狗] 超过 %ds 未返回，杀掉 pid %d\n" % (timeout_s, proc.pid)).encode())
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                return -9
            time.sleep(0.5)
        return proc.returncode


def protect_existing(path: str) -> str:
    """已有非空结论 → 先留档，返回留档路径（空串表示无需留档）。"""
    if os.path.exists(path) and os.path.getsize(path) > 0:
        keep = "%s.%s.bak" % (path, datetime.now().strftime("%H%M%S"))
        shutil.move(path, keep)
        return keep
    return ""


def header(cfg: Config, reviewer_name: str, snapshot_line: str, extra: str = "") -> str:
    r = cfg.reviewer(reviewer_name)
    lines = [
        "# %s · 独立复核结论 · %s · %s" % (cfg.project, reviewer_name, datetime.now().strftime("%Y-%m-%d")),
        "",
        "> 工单: `%s` · 模型族: `%s` · 角色: `%s`%s"
        % (cfg.brief, r.family, r.role, (" · " + r.label) if r.label else ""),
        "> 方式: 独立进程 headless（干净上下文，与作者会话无共享记忆）",
        snapshot_line,
    ]
    if extra:
        lines.append("> %s" % extra)
    lines += ["", "---", ""]
    return "\n".join(lines)


def atomic_write(path: str, text: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def log(cfg: Config, reviewer: str, result: GateResult, label: str) -> None:
    """记账：唯一入口。失败也要记（否则失败会从账上消失）。"""
    os.makedirs(cfg.out_dir_abs, exist_ok=True)
    with open(cfg.log_path(), "a", encoding="utf-8") as f:
        f.write("%s | %s | %s | %s | %s\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M"), cfg.project, reviewer,
            "ok" if result.passed else "FAILED", result.summary() + ((" | " + label) if label else "")
        ))


def read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    return open(path, encoding="utf-8", errors="replace").read()


def split_table_rows(text: str) -> List[Tuple[str, str, str, str]]:
    """从结论里抽出「严重度 | 位置 | 问题 | 证据」四列。交叉表与处置台账都用它。

    刻意只认**表头含「严重度」的那张表**，避免把概述表也当成发现（我们真实踩过：
    概述表里的 🟡 行会被误当成一条发现）。
    """
    rows: List[Tuple[str, str, str, str]] = []
    in_table = False
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 3:
            continue
        if "严重度" in cells[0]:
            in_table = True
            continue
        if set(cells[0]) <= set("-: "):
            continue
        if not in_table:
            continue
        sev = cells[0]
        if not SEVERITY_RE.search(sev):
            continue
        rows.append((sev, cells[1], cells[2], cells[3] if len(cells) > 3 else ""))
    return rows


def severity_of(sev: str) -> int:
    if "🔴" in sev or "[高]" in sev:
        return 3
    if "🟡" in sev or "[中]" in sev:
        return 2
    return 1
