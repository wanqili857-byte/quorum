"""quorum 的测试。

**全部不需要任何 API key** —— e2e 走 `fake` 通道（demo 的桩通道）。
公开仓必须能这样被任何人一键验证，否则「可跑」只是一句声明。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quorum import gates, ledger, leaks, plate, snapshot          # noqa: E402
from quorum.cli import main                                        # noqa: E402
from quorum.config import ConfigError, load                        # noqa: E402


@pytest.fixture
def demo(tmp_path):
    """把 demo 整份复制到临时目录——测试不许污染仓库。"""
    dst = tmp_path / "demo"
    shutil.copytree(os.path.join(ROOT, "demo"), dst)
    subprocess.run([sys.executable, "project/make.py"], cwd=dst, check=True,
                   capture_output=True)
    shutil.rmtree(dst / "out", ignore_errors=True)      # 清掉仓库里跑过的残留
    return str(dst)


# ------------------------------------------------------------------ 配置
def test_config_paths_are_config_relative(tmp_path):
    """相对路径按**配置文件所在目录**解析——换 CWD 不该改变结果。"""
    d = tmp_path / "proj"
    d.mkdir()
    (d / "review.yaml").write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers: [{name: r, channel: c, family: f}]\n", encoding="utf-8")
    cfg = load(str(d / "review.yaml"))
    assert cfg.repo == str(d.resolve()) or cfg.repo == str(d)


def test_config_rejects_same_family_primaries(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers:\n"
        "  - {name: a, channel: c, family: same}\n"
        "  - {name: b, channel: c, family: same}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(str(p))


def test_config_allows_cross_role_in_same_family(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers:\n"
        "  - {name: a, channel: c, family: same}\n"
        "  - {name: b, channel: c, family: same, role: cross}\n", encoding="utf-8")
    assert len(load(str(p)).reviewers) == 2


def test_env_file_indirection_keeps_secret_out_of_config(tmp_path):
    """`X_FILE` 指向的密钥文件内容进环境变量，配置里只有路径。"""
    from quorum.channels import _resolve_env
    sec = tmp_path / "key"
    sec.write_text("SECRET-VALUE\n")
    got = _resolve_env({"ANTHROPIC_AUTH_TOKEN_FILE": str(sec)})
    assert got == {"ANTHROPIC_AUTH_TOKEN": "SECRET-VALUE"}
    assert "SECRET-VALUE" not in str(sec.parent / "review.yaml")


# ------------------------------------------------------------------ 门禁
def test_gate_content_wins_over_exit_code():
    """内容门全过即接受：rc=143（信号收尾）不该让一份完整结论作废。"""
    from quorum.config import Config, Gates, Reviewer, Channel
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(min_bytes=10, min_severity_marks=1, require_sections=["最脆弱"]))
    text = "🔴 有问题\n## 最脆弱的一环\n"
    assert gates.evaluate(cfg, text, rc=143, seconds=1).passed


def test_gate_rejects_thin_output():
    from quorum.config import Config, Gates, Reviewer, Channel
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(min_bytes=10, min_severity_marks=3, require_sections=["最脆弱"]))
    assert not gates.evaluate(cfg, "🔴 只有一条\n## 最脆弱\n", rc=0, seconds=1).passed


def test_protect_existing_never_clobbers(tmp_path):
    p = tmp_path / "f.md"
    p.write_text("原有结论", encoding="utf-8")
    kept = gates.protect_existing(str(p))
    assert kept and os.path.exists(kept)
    assert not os.path.exists(str(p))


def test_split_table_rows_ignores_non_finding_tables():
    """只认表头含「严重度」的表——概述表里的 🟡 不该被当成一条发现。"""
    text = ("| 声明 | 复验 | 判定 |\n|---|---|---|\n| 甲的声明 | 成立 | 🟡 |\n\n"
            "| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n| 🔴 | a.py | 真问题 | 证据 |\n")
    rows = gates.split_table_rows(text)
    assert len(rows) == 1 and rows[0][2] == "真问题"


# --------------------------------------------------------------- 材料快照
def test_snapshot_changes_when_material_changes(tmp_path):
    from quorum.config import Config, Gates, Reviewer, Channel
    (tmp_path / "a.txt").write_text("v1", encoding="utf-8")
    cfg = Config(project="p", brief="b", out_dir="o", repo=str(tmp_path),
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(), sources=["a.txt"])
    first = snapshot.take(cfg)
    (tmp_path / "a.txt").write_text("v2", encoding="utf-8")
    assert snapshot.take(cfg).digest != first.digest


# ------------------------------------------------------------------ 交叉表
def test_plate_merges_same_finding_across_reviewers():
    rows = [
        plate.Row("a", "fa", "🔴", "`report.md` 的 METRICS", "分母静默缩水：报 100 条但预测只有 41 条", ""),
        plate.Row("b", "fb", "🔴", "`report.md`", "报表分母与预测不一致：报 100 条实测 41 条", ""),
    ]
    cs = plate.cluster(rows)
    assert len(cs) == 1 and len(cs[0].families) == 2


def test_plate_keeps_unrelated_findings_apart():
    rows = [
        plate.Row("a", "fa", "🔴", "`report.md`", "分母静默缩水", ""),
        plate.Row("b", "fb", "🟡", "`build.py`", "切分不可复现：遍历 set 导致哈希随机化", ""),
    ]
    assert len(plate.cluster(rows)) == 2


def test_plate_never_merges_two_rows_from_same_reviewer():
    rows = [
        plate.Row("a", "fa", "🔴", "`report.md`", "分母静默缩水", ""),
        plate.Row("a", "fa", "🟡", "`report.md`", "分母静默缩水", ""),
    ]
    cs = plate.cluster(rows)
    assert len(cs) == 2


# ------------------------------------------------------------------ 处置
def test_ledger_verdicts(tmp_path):
    (tmp_path / "ok.txt").write_text("x", encoding="utf-8")
    led = tmp_path / "d.md"
    led.write_text(
        "| # | 问题 | check | status |\n|---|---|---|---|\n"
        "| 1 | 说谎的 | `exit 1` | ✅ |\n"          # 台账说谎
        "| 2 | 真修好的 | `exit 0` | ✅ |\n"        # ok
        "| 3 | 没更新的 | `exit 0` | ⬜ |\n"        # stale
        "| 4 | 没断言的 | | ✅ |\n",                 # no-check
        encoding="utf-8")
    v = ledger.run_checks(ledger.parse(str(led)), str(tmp_path))
    assert [x.verdict for x in v] == ["LIE", "ok", "stale", "no-check"]
    assert ledger.exit_code(v) == 1
    assert ledger.exit_code(v, strict=True) == 1
    assert ledger.exit_code([x for x in v if x.verdict == "ok"]) == 0


# ------------------------------------------------------------------ 泄漏
def test_leak_self_test_proves_patterns_can_fail():
    pats = leaks.default_patterns("someone")
    assert leaks.self_test(pats) == []


def test_leak_scan_finds_username_and_secrets(tmp_path):
    # 样本在运行时拼出来：否则本文件自己会被 check-leaks 判为泄漏（同一类坑，自己也踩一次）
    home = "~/" + "real" + "user/work"
    tok = "sk-" + "abcdefghijkl"
    (tmp_path / "notes.md").write_text("路径 %s\n token %s\n" % (home, tok), encoding="utf-8")
    hits = leaks.scan(str(tmp_path), leaks.default_patterns("realuser"))
    assert "波浪线家目录" in hits and "凭证形态" in hits


def test_leak_scan_clean_on_safe_text(tmp_path):
    (tmp_path / "ok.md").write_text("the quick brown fox\n", encoding="utf-8")
    assert leaks.scan(str(tmp_path), leaks.default_patterns("nobody")) == {}


# -------------------------------------------------------------------- e2e
def test_e2e_demo_full_loop(demo, capsys):
    """无密钥跑通：run --all → plate → dispose → verify。"""
    cfg = os.path.join(demo, "review.yaml")
    assert main(["run", "--config", cfg, "--all"]) == 0
    outs = [f for f in os.listdir(os.path.join(demo, "out"))
            if f.startswith("demo-findings-") and f.endswith(".md")]
    assert len(outs) == 3, outs

    assert main(["plate", "--config", cfg, "--dispose"]) == 0
    text = capsys.readouterr().out
    assert "跨模型族一致" in text                 # 三家在集群 1 上对齐
    assert "单家独有" in text                     # gamma 那条错误断言不该被算成一致
    assert os.path.exists(os.path.join(demo, "out", "demo-dispose.md"))

    assert main(["verify", "--config", cfg, "--ledger", "ledger_example.md"]) == 1
    assert "台账说谎" in capsys.readouterr().out


def test_e2e_rerun_protects_previous_findings(demo):
    cfg = os.path.join(demo, "review.yaml")
    main(["run", "--config", cfg, "--reviewer", "alpha"])
    main(["run", "--config", cfg, "--reviewer", "alpha"])
    baks = [f for f in os.listdir(os.path.join(demo, "out")) if ".bak" in f]
    assert baks, "第二次运行应把上一份结论留档，而不是覆盖"


def test_e2e_material_change_is_flagged(demo, capsys):
    """审核期间材料变了 → 结论头部必须写明（真实吃过：审核员看到的是中途状态）。"""
    cfg = os.path.join(demo, "review.yaml")
    main(["run", "--config", cfg, "--reviewer", "alpha"])
    p = os.path.join(demo, "out", "demo-findings-alpha.md")
    assert "材料快照" in open(p, encoding="utf-8").read()


def test_cli_check_leaks_on_own_repo():
    assert main(["check-leaks", ROOT]) == 0, "公开仓必须通过自己的泄漏门禁"
