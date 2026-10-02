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
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# 不再用扩展名白名单：**漏掉的恰恰是最危险的**（`.env` / `.log` / `.pem` / 无扩展名）。
# 改为「读得动就读」——按内容嗅探二进制，读不动就跳过。
MAX_FILE_BYTES = 4 * 1024 * 1024


def _is_text(p: str) -> bool:
    try:
        if os.path.getsize(p) > MAX_FILE_BYTES:
            return False
        with open(p, "rb") as f:
            chunk = f.read(4096)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             "dist", "build", ".pytest_cache"}


@dataclass
class Pattern:
    name: str
    regex: str
    sample: str          # 自检用：这条规则**必须**能抓到自己种的样本
    why: str = ""
    # fail = 判定失败（退出码非零）；warn = 只提示。
    # 分档的理由：像「`~/<任意词>/`」这种启发式规则会把 `~/workspace/`、`~/Documents/`
    # 这类**正当目录**也命中——它没有语法办法区分「人名」和「目录名」。
    # 把启发式规则和确定性规则混在同一档，结果是假警报淹没真警报。
    severity: str = "fail"


def default_patterns(username: str = "") -> List[Pattern]:
    u = username or getpass.getuser()
    return [
        Pattern("绝对家目录", r"/Users/[A-Za-z0-9_.\-]+|/home/[A-Za-z0-9_.\-]+",
                "/Users/someone/notes.md", "macOS/Linux 家目录里的用户名"),
        # 排除 `~/.config/` 这类点开头的标准目录：用户名不可能以点开头，
        # 而 `~/.config/ark_key` 这种写法在配置示例里到处都是（曾经把它误报成泄漏）。
        Pattern("波浪线家目录（启发式）", r"~/(?!\.|proj/|tmp/)[A-Za-z0-9_\-]+/",
                "~/realname/work/x.md",
                "`~/<某个词>/`。**启发式**：分不清人名与目录名（`~/workspace/` 这类正当占位符也会中）",
                severity="warn"),
        # 必须**锚在路径里**：`[/~]name/`。
        # 旧版是裸词匹配 `(?<![\w/])name(?![\w])` —— 于是 CI 上（用户名恰好是 `runner`）
        # 它把英文单词 "runner" 全报成泄漏。**门禁的结果取决于跑它的机器**，这是比误报更糟的事。
        # 而要防的泄漏本来就是「路径里出现本机用户名」，锚在路径上既更准也更稳。
        Pattern("路径里的本机用户名", r"[/~]%s/" % re.escape(u),
                "/home/%s/project/file" % u, "本机用户名出现在路径里"),
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

# ⚠️ 光有路径不够。**跳过必须按内容认，不能按路径认。**
#
# 真实踩到（2026-10-02）：`quorum check-leaks .` 在仓库里 **rc=1**、在 CI 里 **rc=0**。
# 同一份代码、同一份材料，差别只在 **quorum 是怎么被装上去的**：
#   · CI 用 `pip install -e '.[dev]'` → `__file__` 就是仓库里那份 → 路径相等 → 跳过生效；
#   · 本地用 `uv tool install`（**拷贝**到 site-packages）→ `FIXTURE_FILE` 指向 site-packages，
#     而被扫的是源码树 → 路径**不相等** → 仓库自己那份 `leaks.py` 被当成材料，
#     里面那串样例（`sk-abc…` / `13800138000` / `someone@example.com`）全被报成真命中。
#
# 这和 `docs/LESSONS.md` 那条是同一族：「门禁的结果不该取决于它是怎么被装上去的」。
# 现在两条都留着：路径相等（快路径）+ **内容标记**（不依赖装法）。
FIXTURE_MARKER = "quorum-leaks-fixture-table-only-here"


def _is_fixture_file(path: str, text: str) -> bool:
    """这个文件是不是「检测器自己的样例表」？

    两个条件都要：文件名是 `leaks.py`，**且**内容里有 `FIXTURE_MARKER`。
    只看文件名会误伤同名的第三方文件；只看标记则太宽。
    """
    return os.path.basename(path) == "leaks.py" and FIXTURE_MARKER in text


def tracked_files(root: str) -> List[str]:
    """git 仓库 → 返回**被跟踪**的文件；否则返回 []（调用方回落到 os.walk）。

    扫描范围 = **被跟踪的 + 未跟踪但没被忽略的**（`git ls-files --cached --others --exclude-standard`）。
    这个门禁的职责是「**会被发布出去的东西**里有没有泄漏」：构建产物、虚拟环境、结论目录
    都是 gitignore 的，扫它们只会制造假警报（假警报会让真警报被忽略）。
    但**未跟踪且未被忽略**的文件即将被提交，必须扫——新加的 `.env` 正落在这一类。
    """
    try:
        # --others --exclude-standard 把「未跟踪但不被 .gitignore 忽略」的文件也算进来：
        # 新加的 .env / *.pem / 无扩展名密钥正处于这一类，而它们**即将被提交**。
        out = subprocess.run(["git", "-C", root, "ls-files",
                              "--cached", "--others", "--exclude-standard"],
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [os.path.join(root, l) for l in out.stdout.splitlines() if l.strip()]


def scan(root: str, patterns: List[Pattern], max_hits: int = 5,
         skip_files: Tuple[str, ...] = ()) -> Dict[str, List[Tuple[str, int, str]]]:
    """返回 {规则名: [(相对路径, 行号, 命中片段), ...]}

    ``skip_files`` 存绝对路径。默认由 CLI 传入本模块自身（见 ``FIXTURE_FILE``）。
    """
    compiled = _compile(patterns)
    skipped: List[str] = []
    hits: Dict[str, List[Tuple[str, int, str]]] = {}
    hits["__skipped__"] = []
    files = tracked_files(root)
    if files:
        candidates = [(f, os.path.relpath(f, root)) for f in files]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                if _is_text(p):
                    candidates.append((p, os.path.relpath(p, root)))
                else:
                    skipped.append(os.path.relpath(p, root))
    for p, rel in candidates:
        if not os.path.exists(p):
            continue
        if not _is_text(p):
            skipped.append(rel)          # 静默跳过 = 静默盲区：二进制/超大/非 UTF-8 的文件必须报出来
            continue
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                raw = fh.read()          # 有 MAX_FILE_BYTES 兜着，读整份是安全的
        except OSError:
            continue
        # 跳过「检测器自己的样例表」：**按内容认，不按路径**。理由见 FIXTURE_FILE 上面那段。
        if os.path.abspath(p) in skip_files or _is_fixture_file(p, raw):
            continue
        for i, line in enumerate(raw.splitlines(), 1):
            for pat, rx in compiled:
                m = rx.search(line)
                if m:
                    hits.setdefault(pat.name, [])
                    if len(hits[pat.name]) < max_hits:
                        hits[pat.name].append((rel, i, m.group(0)[:60]))
    return hits


def failing(hits: Dict[str, List[Tuple[str, int, str]]], patterns: List[Pattern]) -> Dict[str, List]:
    """只挑出 severity=fail 的命中（决定退出码的就是这些）。"""
    warn_names = {p.name for p in (patterns or []) if p.severity == "warn"}
    return {k: v for k, v in hits.items()
            if k not in warn_names and k != "__skipped__" and v}


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


def render(hits: Dict[str, List[Tuple[str, int, str]]], root: str,
           skipped: Optional[List[str]] = None,
           patterns: Optional[List[Pattern]] = None) -> str:
    real = {k: v for k, v in hits.items() if k != "__skipped__" and v}
    if not real:
        out = ["在 %s 下未发现任何命中。" % root]
    else:
        warn_names = {p.name for p in (patterns or []) if p.severity == "warn"}
    out = ["在 %s 下发现：" % root, ""]
    for name, items in sorted(real.items()):
        tag = "（提示，不判定失败）" if name in warn_names else ""
        out.append("- **%s**%s：%d 处（最多显示 5）" % (name, tag, len(items)))
        for rel, ln, frag in items:
            out.append("  - `%s:%d` → `%s`" % (rel, ln, frag))
    if skipped:
        out += ["", "⚠️ 有 %d 个文件**跳过未扫**（二进制 / >%dMB / 非 UTF-8）——跳过即盲区，不是「干净」："
                % (len(skipped), MAX_FILE_BYTES // (1024 * 1024))]
        out += ["  - `%s`" % s for s in skipped[:10]]
        if len(skipped) > 10:
            out.append("  - …其余 %d 个" % (len(skipped) - 10))
    return "\n".join(out)
