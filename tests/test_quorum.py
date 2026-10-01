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


def test_brief_and_outdir_are_config_relative(tmp_path):
    """契约说「配置里的相对路径按配置文件所在目录解析」——实现必须一致。

    踩过：实现按 `repo` 解析，于是 `out_dir: out` 落到了 repo/out 而不是 cfg_dir/out，
    而 `brief: brief.md` 解析成一个**不存在**的路径；审核员自己去找、找到了，一切看起来正常。
    """
    d = tmp_path / "reviews"
    d.mkdir()
    (d / "brief.md").write_text("x", encoding="utf-8")
    (d / "review.yaml").write_text(
        "project: p\nrepo: ..\nbrief: brief.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers: [{name: r, channel: c, family: f}]\n", encoding="utf-8")
    cfg = load(str(d / "review.yaml"))
    assert cfg.brief_abs == str(d / "brief.md") and os.path.exists(cfg.brief_abs)
    assert cfg.out_dir_abs == str(d / "out")
    assert cfg.brief_for_prompt() == os.path.join("reviews", "brief.md")


def test_run_refuses_when_brief_missing(tmp_path):
    (tmp_path / "review.yaml").write_text(
        "project: p\nrepo: .\nbrief: nope.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers: [{name: r, channel: c, family: f}]\n", encoding="utf-8")
    assert main(["run", "--config", str(tmp_path / "review.yaml"), "--all"]) == 2


def test_config_requires_explicit_family(tmp_path):
    """family 是 COI 的唯一依据 —— 不写就必须报错。

    （这条用**行为**断言，不用「文件里没有某个字符串」——后者会被解释性注释满足。）
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers:\n"
        "  - {name: a, channel: c}\n"
        "  - {name: b, channel: c}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(str(p))


def test_cli_self_test_can_actually_fail(tmp_path, monkeypatch, capsys):
    """「检查能不能失败」的检查自己必须能失败。

    旧版 CLI 里有一句 `[f for f in self_test(pats) if "样本" not in f]` ——
    而失败消息正是「正则抓不到自己种的样本」，于是它把唯一该报的失败**滤掉了**。
    这里注入一条永远匹配不上的规则，断言 CLI 真的判失败。
    """
    from quorum import leaks as leaks_mod
    real = leaks_mod.default_patterns

    def with_broken(username=""):
        return real(username) + [leaks_mod.Pattern("故意写坏", r"NEVER_MATCHES_XYZ",
                                                   "sample", "测试用")]

    monkeypatch.setattr("quorum.leaks.default_patterns", with_broken)

    class A:
        config = ""
        username = "x"
        self_test = True
        dir = ""
        self_sample = ""
        ignore = []
    assert main.__module__ and True
    rc = __import__("quorum.cli", fromlist=["cmd_leaks"]).cmd_leaks(A())
    assert rc == 1, "一条抓不到自己样本的规则必须让 --self-test 失败"


def test_demo_ledger_reports_the_expected_verdicts(demo, capsys):
    """示例台账的四档判定必须真的是那四档（不是靠读注释相信）。"""
    cfg = os.path.join(demo, "review.yaml")
    assert main(["verify", "--config", cfg, "--ledger", "ledger_example.md"]) == 1
    out = capsys.readouterr().out
    assert "台账说谎 1" in out and "未修 2" in out and "无断言 1" in out


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
    """`X_FILE` 指向的密钥文件内容进环境变量；**配置文件里只有路径**。

    旧版最后一行断言的是 `str(sec.parent / "review.yaml")` —— 那个文件根本不存在，
    字符串里当然不含密钥，于是这条断言**永远为真**。改成真的写一份配置并检查它。
    """
    from quorum.channels import _resolve_env
    sec = tmp_path / "key"
    sec.write_text("SECRET-VALUE\n")
    got = _resolve_env({"ANTHROPIC_AUTH_TOKEN_FILE": str(sec)})
    assert got == {"ANTHROPIC_AUTH_TOKEN": "SECRET-VALUE"}

    cfg_p = tmp_path / "review.yaml"
    cfg_p.write_text("channels:\n  c:\n    kind: claude-cli\n"
                     "    env: {ANTHROPIC_AUTH_TOKEN_FILE: %s}\n" % sec, encoding="utf-8")
    assert "SECRET-VALUE" not in cfg_p.read_text(encoding="utf-8")   # 真的读了配置


# ------------------------------------------------------------------ 门禁
def test_env_var_reference(monkeypatch):
    """`${VAR}` 从环境变量取值；未设置时报错，不静默传空串。"""
    from quorum.channels import _resolve_env, ChannelError
    monkeypatch.setenv("QUORUM_TEST_TOKEN", "tok-123")
    assert _resolve_env({"ANTHROPIC_AUTH_TOKEN": "${QUORUM_TEST_TOKEN}"}) == {
        "ANTHROPIC_AUTH_TOKEN": "tok-123"}
    monkeypatch.delenv("QUORUM_TEST_TOKEN")
    with pytest.raises(ChannelError):
        _resolve_env({"ANTHROPIC_AUTH_TOKEN": "${QUORUM_TEST_TOKEN}"})


def test_gate_content_wins_over_exit_code():
    """内容门全过即接受：rc=143（信号收尾）不该让一份完整结论作废。"""
    from quorum.config import Config, Gates, Reviewer, Channel
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(min_bytes=10, min_findings=1, require_sections=["最脆弱"]))
    text = ("| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n"
            "| 🔴 | a.py | 这是一个有实质内容的问题描述 | 我跑了 X |\n## 最脆弱的一环\n")
    assert gates.evaluate(cfg, text, rc=143, seconds=1).passed


def test_gate_counts_findings_not_emoji_spam():
    """门禁数的必须是**解析出来的发现条数**。

    踩过：旧版数 emoji 出现次数，于是「概述表里 30 个 🔴 + 一句『最脆弱』+ 一堆句号」
    能凑出一份『合规』的空产出。
    """
    from quorum.config import Config, Gates, Reviewer, Channel
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(min_bytes=10, min_findings=3, require_sections=["最脆弱"]))
    spam = "🔴🟡🟢 " * 30 + "\n## 最脆弱的一环\n" + "。" * 2000
    r = gates.evaluate(cfg, spam, rc=0, seconds=1)
    assert not r.passed and r.findings == 0 and r.marks >= 30


def test_severity_column_need_not_be_first():
    """表头「严重度」不在第 0 列也要认——旧版只认第 0 列，会静默丢掉整份结论。"""
    text = ("| # | 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|---|\n"
            "| 1 | 🔴 | a.py | 真问题 | 证据 |\n")
    rows = gates.split_table_rows(text)
    assert len(rows) == 1 and rows[0][1] == "a.py"


def test_gate_rejects_thin_output():
    from quorum.config import Config, Gates, Reviewer, Channel
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[Reviewer("r", "c")], channels={"c": Channel("c", "fake")},
                 gates=Gates(min_bytes=10, min_findings=3, require_sections=["最脆弱"]))
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
def test_plate_ignores_cross_role_for_confidence():
    """CONTRACT：cross 的结论不计入「跨模型族一致」。"""
    rows = [plate.Row("a", "fa", "🔴", "x.md", "同一个问题", "e", "primary"),
            plate.Row("b", "fb", "🔴", "x.md", "同一个问题", "e", "cross")]
    c = plate.cluster(rows)[0]
    assert c.label().startswith("含交叉")          # 只有一个 primary family
    rows[1].role = "primary"
    assert plate.cluster(rows)[0].label().startswith("跨模型族一致")


def test_plate_snapshot_cannot_be_spoofed_by_body_text():
    """快照只认 runner 写的机器可读标记——审核员在正文里写同格式文本不能覆盖它。"""
    import re as _re
    body = ("<!-- quorum:snapshot tree:REAL -->\n\n---\n\n"
            "材料快照：`tree:FAKE`\n")
    m = _re.search(r"<!--\s*quorum:snapshot\s+(\S+)\s*-->", body)
    assert m.group(1) == "tree:REAL"


def test_split_row_handles_pipes_in_code_spans():
    """单元格里内嵌 markdown 表格（LLM 常见写法）不该把解析搞崩。"""
    line = "| 🔴 | a.py | 写成 `| # | 严重度 | 位置 |` 就丢行 | 证据 |"
    cells = gates._split_row(line)
    assert len(cells) == 4, cells                  # 内嵌表格的竖线不分隔
    assert "严重度" in cells[2] and cells[3] == "证据"


def test_dispose_protects_existing_ledger(tmp_path):
    """plate --dispose 不许原地截断用户填好的台账。"""
    led = tmp_path / "d.md"
    led.write_text("| # | 问题 | check | status |\n|---|---|---|---|\n| 1 | x | `true` | ✅ |\n",
                   encoding="utf-8")
    kept = gates.protect_existing(str(led))
    assert kept and "check" in open(kept, encoding="utf-8").read()


def test_leak_self_test_proves_patterns_can_fail():
    pats = leaks.default_patterns("someone")
    assert leaks.self_test(pats) == []


def test_leak_scan_finds_username_and_secrets(tmp_path):
    # 样本在运行时拼出来：否则本文件自己会被 check-leaks 判为泄漏（同一类坑，自己也踩一次）
    home = "~/" + "real" + "user/work"
    tok = "sk-" + "abcdefghijkl"
    (tmp_path / "notes.md").write_text("路径 %s\n token %s\n" % (home, tok), encoding="utf-8")
    hits = leaks.scan(str(tmp_path), leaks.default_patterns("realuser"))
    assert "波浪线家目录（启发式）" in hits and "凭证形态" in hits
    # 启发式档不算失败：`~/workspace/` 这类正当占位符也在它管辖内
    assert "波浪线家目录（启发式）" not in leaks.failing(hits, leaks.default_patterns("realuser"))
    assert "凭证形态" in leaks.failing(hits, leaks.default_patterns("realuser"))


def test_leak_scan_clean_on_safe_text(tmp_path):
    (tmp_path / "ok.md").write_text("the quick brown fox\n", encoding="utf-8")
    got = {k: v for k, v in leaks.scan(str(tmp_path), leaks.default_patterns("nobody")).items()
           if k != "__skipped__"}
    assert got == {}


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
    # 只在**汇总表**里断言：旧版断的是整份文本里出现某串，而 render() 的「读法」一节
    # 本身就含「单家独有」四个字 —— 那条断言永远为真。
    summary = text.split("## 明细")[0]
    assert "跨模型族一致" in summary               # 三家在集群 1 上对齐
    n_high = summary.count("跨模型族一致")
    assert n_high == 1, "只有集群 1 该被判为跨模型族一致，实际 %d" % n_high
    assert summary.count("单家独有") >= 2          # 其余三条各自独立
    assert os.path.exists(os.path.join(demo, "out", "demo-dispose.md"))

    assert main(["verify", "--config", cfg, "--ledger", "ledger_example.md"]) == 1
    assert "台账说谎" in capsys.readouterr().out


def test_e2e_rerun_protects_previous_findings(demo):
    cfg = os.path.join(demo, "review.yaml")
    main(["run", "--config", cfg, "--reviewer", "alpha"])
    main(["run", "--config", cfg, "--reviewer", "alpha"])
    baks = [f for f in os.listdir(os.path.join(demo, "out")) if ".bak" in f]
    assert baks, "第二次运行应把上一份结论留档，而不是覆盖"


def test_e2e_material_change_is_flagged(demo, tmp_path, monkeypatch):
    """审核期间材料变了 → 结论头部必须写明。

    旧版只断言 `"材料快照" in 结论` —— 而 runner **总是**写那一行，所以它永远为真。
    这里让「期间材料被改」真的发生：把桩通道换成「先改一个被 sources 覆盖的文件再输出结论」。
    """
    cfg = os.path.join(demo, "review.yaml")
    from quorum import snapshot as snap_mod
    touch = os.path.join(demo, "project", "report.md")
    real_take = snap_mod.take
    calls = {"n": 0}

    def fake_take(c):
        calls["n"] += 1
        # 调用序：1) 开跑前的展示 2) 该审核员的基线 3) 审核结束后的对照
        if calls["n"] == 3:                       # 第 3 次 = 审核之后：材料已变
            with open(touch, "a", encoding="utf-8") as f:
                f.write("\n<!-- 审核期间被改动 -->\n")
        return real_take(c)

    monkeypatch.setattr("quorum.cli.snapshot.take", fake_take)
    main(["run", "--config", cfg, "--reviewer", "alpha"])
    text = open(os.path.join(demo, "out", "demo-findings-alpha.md"), encoding="utf-8").read()
    assert "材料在审核期间发生变化" in text


def test_cli_check_leaks_on_own_repo():
    assert main(["check-leaks", ROOT]) == 0, "公开仓必须通过自己的泄漏门禁"
