"""材料快照：这份结论审的是**哪一版**材料。

为什么需要：审核的前提是材料静止，但现实里作者往往边审边改。没有快照指纹时，
「这份结论审的是哪一版」在事后无法回答——你只能像我们那次一样，在结论里手写一句
「本结论以 21:38–21:44 的工作区状态为准」，而那句话无法被验证。

做法：
* git 仓库 → ``git:<HEAD>`` + 工作区是否脏（脏的话把 ``git status --porcelain`` 也哈希进去）
* 非 git  → 对 ``sources`` 列出的路径做文件树指纹（相对路径 + 大小 + 内容哈希）

大文件（> ``max_hash_bytes``）只计 (大小, mtime)，不算内容——避免为了算指纹去读几百 MB 的权重。
这一取舍写进 detail，别让读者以为它是全内容哈希。
"""
from __future__ import annotations

import glob
import hashlib
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional

from .config import Config

MAX_HASH_BYTES = 8 * 1024 * 1024


@dataclass
class Snapshot:
    kind: str          # git | tree
    digest: str        # 短指纹
    detail: str        # 人读的一行
    files: int = 0

    def header_line(self) -> str:
        return "> 材料快照：`%s`（%s）" % (self.digest, self.detail)


def _git(repo: str, *args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", repo] + list(args),
                             capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def take(cfg: Config) -> Snapshot:
    """材料指纹。

    git 仓库里**不能只看 HEAD**：`sources` / `snapshot_exclude` 会变成死配置，
    而且同一份材料在「首次 commit 之前」是 `tree:…`、之后变成 `git:HEAD` —— 指纹算法随环境静默翻转。
    现在两种模式都包含 **sources 的文件树哈希**；git 模式额外带上 HEAD 与工作区脏标记作为身份。
    """
    tree = _tree(cfg)
    head = _git(cfg.repo, "rev-parse", "HEAD")
    if not head:
        return tree
    status = _git(cfg.repo, "status", "--porcelain") or ""
    h = hashlib.sha256(("%s\n%s\n%s" % (head, status, tree.digest)).encode()).hexdigest()[:12]
    detail = "git %s%s + 材料树 %s（%d 个文件）" % (
        head[:12], "，工作区有未提交改动" if status else "，工作区干净", tree.digest, tree.files)
    return Snapshot("git", "git:%s" % h, detail, tree.files)


def _tree(cfg: Config) -> Snapshot:
    paths: List[str] = []
    roots = cfg.sources or ["."]
    for pat in roots:
        full = os.path.join(cfg.repo, pat)
        if any(ch in pat for ch in "*?["):
            paths += [p for p in glob.glob(full, recursive=True) if os.path.isfile(p)]
        elif os.path.isfile(full):
            paths.append(full)
        elif os.path.isdir(full):
            for dirpath, dirnames, filenames in os.walk(full):
                rel_dir = os.path.relpath(dirpath, cfg.repo)
                dirnames[:] = [d for d in dirnames
                               if not any(rel_dir.startswith(x.rstrip("/")) for x in cfg.snapshot_exclude)]
                paths += [os.path.join(dirpath, f) for f in filenames]

    h = hashlib.sha256()
    n = 0
    skipped = 0
    for p in sorted(set(paths)):
        rel = os.path.relpath(p, cfg.repo)
        if any(rel.startswith(x.rstrip("/")) for x in cfg.snapshot_exclude):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        h.update(rel.encode())
        h.update(str(st.st_size).encode())
        if st.st_size <= MAX_HASH_BYTES:
            try:
                h.update(hashlib.sha256(open(p, "rb").read()).hexdigest().encode())
            except OSError:
                pass
        else:
            h.update(str(int(st.st_mtime)).encode())
            skipped += 1
        n += 1
    detail = "非 git，文件树指纹（%d 个文件）" % n
    if skipped:
        detail += "；其中 %d 个 >%dMB 仅按 (大小, mtime) 计入" % (skipped, MAX_HASH_BYTES // (1024 * 1024))
    return Snapshot("tree", "tree:%s" % h.hexdigest()[:12], detail, n)
