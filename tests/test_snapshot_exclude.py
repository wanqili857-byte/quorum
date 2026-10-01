"""`snapshot_exclude` 的路径段匹配（独立文件，便于单独提交）。

背景：`_excluded` 对非 glob 模式原先只按**仓库根前缀**匹配，于是
`__pycache__` 这种「到处都有」的名字只能命中根目录那一个，嵌套的全部漏网。
实测后果：19 个 `.pyc` 被算进材料指纹 → 同一天两次快照 digest 不同 →
quorum 自己报出「材料快照不一致」的**假警报**（canonbench 第二轮）。
假警报和真警报长得一模一样，只能人肉查——所以这个洞值得单独钉住。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quorum import snapshot                                      # noqa: E402
from quorum.config import Channel, Config, Gates, Reviewer       # noqa: E402


def test_snapshot_exclude_matches_nested_path_segments(tmp_path):
    """`snapshot_exclude` 里的名字必须命中**任意深度**的同名目录。

    曾经的洞：非 glob 模式只按仓库根前缀匹配，`__pycache__` 只命中根目录那一个，
    嵌套的 `bench/universe/__pycache__` 全部漏网——生成物（.pyc）进了材料指纹，
    同一天两次快照 digest 不同，quorum 报出「材料快照不一致」的假警报。
    """
    import os
    from quorum.config import Config, Gates, Reviewer, Channel
    (tmp_path / "bench" / "universe" / "__pycache__").mkdir(parents=True)
    (tmp_path / "bench" / "universe" / "__pycache__" / "g.pyc").write_bytes(b"x")
    (tmp_path / "bench" / "universe" / "generator.py").write_text("v1", encoding="utf-8")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "r.json").write_text("{}", encoding="utf-8")
    cfg = Config(project="p", brief="b", out_dir="o", repo=str(tmp_path),
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(), sources=["bench", "runs"],
                 snapshot_exclude=["__pycache__", "runs"])

    # 路径段匹配本身
    assert snapshot._excluded("bench/universe/__pycache__", ["__pycache__"])
    assert snapshot._excluded(os.path.join("bench", "universe", "__pycache__", "g.pyc"),
                              ["__pycache__"])
    assert snapshot._excluded("a/b/runs", ["runs"])
    # 不许误伤前缀相同的兄弟名
    assert not snapshot._excluded("bench/runsheet", ["runs"])
    assert not snapshot._excluded("bench/universe/__pycache__x", ["__pycache__"])

    # 端到端：改一个 .pyc **不得**改变材料指纹
    first = snapshot.take(cfg)
    (tmp_path / "bench" / "universe" / "__pycache__" / "g.pyc").write_bytes(b"yy")
    assert snapshot.take(cfg).digest == first.digest
    # 改真正的材料**必须**改变指纹（否则上面的相等是空真）
    (tmp_path / "bench" / "universe" / "generator.py").write_text("v2", encoding="utf-8")
    assert snapshot.take(cfg).digest != first.digest


def test_snapshot_exclude_still_excludes_by_root_prefix(tmp_path):
    """旧的根前缀行为不能因为这次改动而丢（`reviews/out` 这种多段路径）。"""
    assert snapshot._excluded("reviews/out/x.md", ["reviews/out"])
    assert snapshot._excluded("reviews/out", ["reviews/out"])
    assert not snapshot._excluded("reviews/output.md", ["reviews/out"])
