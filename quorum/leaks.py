"""泄漏自检：公开仓的守门人。

**自检的 pattern 必须从规则表派生，不许重写一份窄的。** 这条是真实教训换来的：
曾有项目的脱敏自检只查三类形态，比它自己的脱敏规则少了四类，于是它对着一份
含 585 处本机用户名的文件打印「残留：无 ✓」——**一句读起来像「已验证」的输出**。

所以本模块：
1. 规则只有一个来源（``PATTERNS`` + 配置追加），扫描用哪套、自检也用哪套；
2. ``--self-test`` 给每条规则**种一个样本**并断言它能被抓到——自检本身**必须能失败**。
   不能失败的检查不是检查，是装饰。
"""
from __future__ import annotations

import getpass
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple

TEXT_EXT = (".py", ".md", ".json", ".jsonl", ".yaml", ".yml", ".ipynb", ".sh",
            ".txt", ".toml", ".cfg", ".ini", ".html", ".js", ".ts")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             "dist", "build", ".pytest_cache"}


@dataclass
class Pattern:
    name: str
    regex: str
    sample: str          # 自检用：这条规则**必须**能抓到自己种的样本
    why: str = ""


def default_patterns(username: str = "") -> List[Pattern]:
    u = username or getpass.getuser()
    return [
        Pattern("绝对家目录", r"/Users/[A-Za-z0-9_.\-]+|/home/[A-Za-z0-9_.\-]+",
                "/Users/someone/notes.md", "macOS/Linux 家目录里的用户名"),
        # 排除 `~/.config/` 这类点开头的标准目录：用户名不可能以点开头，
        # 而 `~/.config/ark_key` 这种写法在配置示例里到处都是（曾经把它误报成泄漏）。
        Pattern("波浪线家目录", r"~/(?!\.|proj/|tmp/)[A-Za-z0-9_\-]+/",
                "~/realname/work/x.md", "`~/<用户名>/` 形态——脱敏最常漏的一类"),
        Pattern("本机用户名", r"(?<![\w/])%s(?![\w])" % re.escape(u),
                "由 %s 自己构成的串" % u, "当前机器的用户名出现在材料里"),
        Pattern("凭证形态", r"(sk-[A-Za-z0-9_\-]{8,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,}"
                        r"|Bearer\s+[A-Za-z0-9._\-]{12,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
                "sk-abcdefghijklmnop", "API key / token / 私钥"),
        Pattern("邮箱", r"[\w.\-]+@[\w\-]+\.[A-Za-z]{2,}", "someone@example.com", "邮箱"),
        Pattern("手机号", r"(?<!\d)1[3-9]\d{9}(?!\d)", "13800138000", "中国大陆手机号"),
        Pattern("IPv4", r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])", "10.20.30.40", "内网/公网 IP"),
        Pattern("内部版本目录", r"\b\w+_v\d+_(?:out|output|result|dump)\b",
                "experiment_v2_out", "看起来是内部产物目录名"),
    ]


def _compile(patterns: List[Pattern]) -> List[Tuple[Pattern, "re.Pattern"]]:
    return [(p, re.compile(p.regex)) for p in patterns]


# 本文件**故意**含有每条规则的自检样本（`Pattern.sample`）——它们是测试夹具，不是泄漏。
# 扫描时默认跳过它，否则公开仓永远过不了自己的门禁。这是唯一一处豁免，理由写在这里。
FIXTURE_FILE = os.path.abspath(__file__)


def scan(root: str, patterns: List[Pattern], max_hits: int = 5,
         skip_files: Tuple[str, ...] = ()) -> Dict[str, List[Tuple[str, int, str]]]:
    """返回 {规则名: [(相对路径, 行号, 命中片段), ...]}

    ``skip_files`` 存绝对路径。默认由 CLI 传入本模块自身（见 ``FIXTURE_FILE``）。
    """
    compiled = _compile(patterns)
    hits: Dict[str, List[Tuple[str, int, str]]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(TEXT_EXT):
                continue
            p = os.path.join(dirpath, fn)
            if os.path.abspath(p) in skip_files:
                continue
            rel = os.path.relpath(p, root)
            try:
                for i, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
                    for pat, rx in compiled:
                        m = rx.search(line)
                        if m:
                            hits.setdefault(pat.name, [])
                            if len(hits[pat.name]) < max_hits:
                                hits[pat.name].append((rel, i, m.group(0)[:60]))
            except OSError:
                continue
    return hits


def self_test(patterns: List[Pattern]) -> List[str]:
    """给每条规则种样本、断言能抓到。返回失败清单（空 = 通过）。

    **这是这个模块存在的理由**：一份不能失败的检查，等于没有检查。
    """
    failures = []
    for p in patterns:
        rx = re.compile(p.regex)
        if not rx.search(p.sample):
            failures.append("%s：正则抓不到自己种的样本 %r" % (p.name, p.sample))
    # 反向：也要能证明"该漏的没漏"——用一个明显安全的串，任何规则都不该命中
    safe = "the quick brown fox jumps over the lazy dog"
    for p, rx in _compile(patterns):
        if rx.search(safe):
            failures.append("%s：命中了明显安全的文本（误报）" % p.name)
    return failures


def render(hits: Dict[str, List[Tuple[str, int, str]]], root: str) -> str:
    if not hits:
        return "在 %s 下未发现任何命中。" % root
    out = ["在 %s 下发现：" % root, ""]
    for name, items in sorted(hits.items()):
        out.append("- **%s**：%d 处（最多显示 5）" % (name, len(items)))
        for rel, ln, frag in items:
            out.append("  - `%s:%d` → `%s`" % (rel, ln, frag))
    return "\n".join(out)
