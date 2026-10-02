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
        "reviewers: [{name: r, channel: c, vendor: v}]\n", encoding="utf-8")
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
        "reviewers: [{name: r, channel: c, vendor: v}]\n", encoding="utf-8")
    cfg = load(str(d / "review.yaml"))
    assert cfg.brief_abs == str(d / "brief.md") and os.path.exists(cfg.brief_abs)
    assert cfg.out_dir_abs == str(d / "out")
    assert cfg.brief_for_prompt() == os.path.join("reviews", "brief.md")


def test_run_refuses_when_brief_missing(tmp_path):
    (tmp_path / "review.yaml").write_text(
        "project: p\nrepo: .\nbrief: nope.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers: [{name: r, channel: c, vendor: v}]\n", encoding="utf-8")
    assert main(["run", "--config", str(tmp_path / "review.yaml"), "--all"]) == 2


def test_config_requires_explicit_vendor(tmp_path):
    """vendor 是 COI 的唯一依据 —— 不写就必须报错。

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
    # ⚠️ 这里原本有一行 `assert main.__module__ and True` —— **恒真**，撤掉。
    # 一个非空字符串永远是真值，所以那行断言的判据与被测对象无关。
    # 讽刺的是它长在一个专讲「修饰性断言」的测试里（2026-10-02，kimi 与 luna 都点到）。
    # 真正的检查是下一行。
    rc = __import__("quorum.cli", fromlist=["cmd_leaks"]).cmd_leaks(A())
    assert rc == 1, "一条抓不到自己样本的规则必须让 --self-test 失败"


def test_demo_ledger_reports_the_expected_verdicts(demo, capsys):
    """示例台账的四档判定必须真的是那四档（不是靠读注释相信）。"""
    cfg = os.path.join(demo, "review.yaml")
    assert main(["verify", "--config", cfg, "--ledger", "ledger_example.md"]) == 1
    out = capsys.readouterr().out
    assert "台账说谎 1" in out and "未修 2" in out and "无断言 1" in out


def test_config_rejects_same_vendor_primaries(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers:\n"
        "  - {name: a, channel: c, vendor: same}\n"
        "  - {name: b, channel: c, vendor: same}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(str(p))


def test_config_allows_cross_role_in_same_vendor(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers:\n"
        "  - {name: a, channel: c, vendor: same}\n"
        "  - {name: b, channel: c, vendor: same, role: cross}\n", encoding="utf-8")
    assert len(load(str(p)).reviewers) == 2


def test_family_is_accepted_as_legacy_alias_for_vendor(tmp_path):
    """`family` 是 vendor 的旧名。老配置不能因为改名就跑不起来。"""
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels: {c: {kind: fake, argv: ['true']}}\n"
        "reviewers: [{name: a, channel: c, family: moonshot}]\n", encoding="utf-8")
    assert load(str(p)).reviewers[0].vendor == "moonshot"


def test_harness_is_derived_from_channel_not_declared(tmp_path):
    """harness 是**事实**（从通道推出），不是审核员自己声明的。

    这条是本次改动的核心：两个轴必须能分开。同一 vendor 挂两个通道 = 两个 harness；
    同一通道挂两个 vendor = 一个 harness。
    """
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels:\n"
        "  c1: {kind: exec, argv: ['x', '{prompt}']}\n"
        "  c2: {kind: exec, argv: ['y', '{prompt}'], harness: wrapped-y}\n"
        "reviewers:\n"
        "  - {name: a, channel: c1, vendor: va}\n"
        "  - {name: b, channel: c1, vendor: vb}\n"
        "  - {name: c, channel: c2, vendor: vb, role: cross}\n", encoding="utf-8")
    rs = {r.name: r for r in load(str(p)).reviewers}
    assert rs["a"].harness == "exec" and rs["b"].harness == "exec"   # 同通道 → 同 harness
    assert rs["c"].harness == "wrapped-y"                            # 可覆盖
    assert rs["a"].vendor == "va" and rs["b"].vendor == "vb"         # vendor 各自独立
    # harness 不是从 vendor 推的：a/b 同 harness 不同 vendor，b/c 同 vendor 不同 harness
    assert rs["a"].harness == rs["b"].harness and rs["a"].vendor != rs["b"].vendor
    assert rs["b"].vendor == rs["c"].vendor and rs["b"].harness != rs["c"].harness


def test_exec_channel_lets_you_plug_in_any_cli(tmp_path):
    """`exec` 是 DIY 的入口：任何 CLI 都能接，不需要改库源码。

    只有 claude-cli / codex-cli 两种内置起法时，harness 维度就是封闭枚举 ——
    想接 aider / gemini-cli / 自己写的脚本必须改源码，那样「harness 可自定义」是空话。
    """
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    ch = Channel("c", "exec", argv=["my-agent", "--read-only", "-C", "{repo}",
                                    "-o", "{out}", "{prompt}"])
    cfg = Config(project="p", brief="b", out_dir="o", repo="/tmp/repo",
                 reviewers=[], channels={}, gates=None)
    argv, env, writes = channels.build(ch, Reviewer("r", "c"), cfg, "PROMPT")
    assert argv == ["my-agent", "--read-only", "-C", "/tmp/repo",
                    "-o", "{out}", "PROMPT"]
    assert writes is True                      # argv 里有 {out} → CLI 自己写结论文件
    assert "exec" in channels.READONLY         # 只读强度必须显式说明（这里是「未知」）


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

    # ⚠️ 这里原来断言的是**测试自己刚写下去的那份配置**里没有密钥 —— 同义反复：
    # 测试写的就是只有路径的那一行，它当然不含密钥。（2026-10-02，kimi 独立发现。）
    # 真正要证的是「密钥不进**命令行**」——命令行会进 `ps` 和 shell 历史，是真正会外泄的那一处。
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    cfg = Config(project="p", brief="b", out_dir="o", repo=str(tmp_path),
                 reviewers=[], channels={}, gates=None)
    argv, env2, _ = channels.build(
        Channel("c", "claude-cli", model="m",
                env={"ANTHROPIC_AUTH_TOKEN_FILE": str(sec)}),
        Reviewer("r", "c"), cfg, "PROMPT")
    assert env2["ANTHROPIC_AUTH_TOKEN"] == "SECRET-VALUE", "密钥没进 env，通道根本用不了"
    assert not any("SECRET-VALUE" in a for a in argv), \
        "密钥进了命令行——`ps` 上所有人都看得到：%r" % (argv,)


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
# Row 的签名是 (reviewer, vendor, harness, severity, location, problem, evidence, role)。
# 两条轴都必填——旧版只有 vendor 一条，于是「两家同一个 harness」和「两家同一个模型来源」
# 在数据上长得一模一样，读表的人分不出来。
def test_plate_merges_same_finding_across_reviewers():
    rows = [
        plate.Row("a", "fa", "h1", "🔴", "`report.md` 的 METRICS", "分母静默缩水：报 100 条但预测只有 41 条", ""),
        plate.Row("b", "fb", "h2", "🔴", "`report.md`", "报表分母与预测不一致：报 100 条实测 41 条", ""),
    ]
    cs = plate.cluster(rows)
    assert len(cs) == 1 and len(cs[0].vendors) == 2 and len(cs[0].harnesses) == 2


def test_plate_keeps_unrelated_findings_apart():
    rows = [
        plate.Row("a", "fa", "h1", "🔴", "`report.md`", "分母静默缩水", ""),
        plate.Row("b", "fb", "h2", "🟡", "`build.py`", "切分不可复现：遍历 set 导致哈希随机化", ""),
    ]
    assert len(plate.cluster(rows)) == 2


def test_plate_never_merges_two_rows_from_same_reviewer():
    rows = [
        plate.Row("a", "fa", "h1", "🔴", "`report.md`", "分母静默缩水", ""),
        plate.Row("a", "fa", "h1", "🟡", "`report.md`", "分母静默缩水", ""),
    ]
    cs = plate.cluster(rows)
    assert len(cs) == 2


def test_plate_annotates_shared_harness():
    """两家 vendor 不同但同走一个 harness：一致可能来自 harness，必须注记。

    这是本次改动的**核心理由**。真实配置里 kimi 与 qwen 是两个 vendor，
    但都走 claude-cli —— 旧版打出「跨模型族一致 · 高置信」，读者会以为买到了两维独立。
    注记**不降级**：模型层的独立是真的，抹掉是过度惩罚。
    """
    rows = [plate.Row("a", "moonshot", "claude-cli", "🔴", "x.md", "同一个问题", ""),
            plate.Row("b", "qwen", "claude-cli", "🔴", "x.md", "同一个问题", "")]
    lab = plate.cluster(rows)[0].label()
    assert lab.startswith("跨模型族一致")            # 不降级
    assert "claude-cli" in lab and "共识可能来自 harness" in lab   # 但注记


def test_plate_annotates_same_vendor_two_harnesses():
    """反向的不独立：换 harness 不换模型 —— 盲区还是共享的。"""
    rows = [plate.Row("a", "moonshot", "claude-cli", "🔴", "x.md", "同一个问题", ""),
            plate.Row("b", "moonshot", "codex-cli", "🔴", "x.md", "同一个问题", "")]
    lab = plate.cluster(rows)[0].label()
    assert "同一 vendor" in lab and "同权重同盲区" in lab


def test_plate_reports_full_independence_when_both_axes_span():
    """两轴都跨才是真的「两个独立来源互相印证」。"""
    rows = [plate.Row("a", "moonshot", "claude-cli", "🔴", "x.md", "同一个问题", ""),
            plate.Row("b", "qwen", "codex-cli", "🔴", "x.md", "同一个问题", "")]
    lab = plate.cluster(rows)[0].label()
    assert "两轴皆跨" in lab


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
    rows = [plate.Row("a", "fa", "h1", "🔴", "x.md", "同一个问题", "e", "primary"),
            plate.Row("b", "fb", "h2", "🔴", "x.md", "同一个问题", "e", "cross")]
    c = plate.cluster(rows)[0]
    assert c.label().startswith("含交叉")          # 只有一个 primary vendor
    rows[1].role = "primary"
    assert plate.cluster(rows)[0].label().startswith("跨模型族一致")


def test_plate_snapshot_cannot_be_spoofed_by_body_text():
    """快照只认 runner 写的机器可读标记——审核员在正文里写同格式文本不能覆盖它。

    ⚠️ 这条测试原来**把生产代码的两条正则抄了一遍**再断言。抄本的问题不是抽象的「会漂」：
    它只抄了第一条（机器可读标记），**第二条回退（`材料快照：\\`…\\``）从来没被测过**——
    而回退恰好是审核员能伪造的那一半。现在两条都走 `plate.snapshot_of`，没有第二份可以漂。
    """
    body = ("<!-- quorum:snapshot tree:REAL -->\n\n---\n\n"
            "材料快照：`tree:FAKE`\n")
    assert plate.snapshot_of(body) == "tree:REAL", "正文里的伪造标记盖掉了真标记"

    # 回退那一半也要覆盖：没有机器标记时，才轮到正文里的 `材料快照：`
    fallback = "材料快照：`tree:FROM-BODY`\n\n---\n\n后面的不算\n"
    assert plate.snapshot_of(fallback) == "tree:FROM-BODY"
    # 而 `---` 之后的同格式文本**不算**（那是审核员正文区，不该影响 runner 的记录）
    assert plate.snapshot_of("前言\n\n---\n\n材料快照：`tree:LATE`\n") == "（该结论无快照标记）"


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
    """自检必须**能红**，不只是全绿。

    ⚠️ 原来这条只断言 `self_test(pats) == []` —— 那是「这次没发现问题」，
    不是「这条检查能失败」。（2026-10-02，kimi 与 luna 各自独立点到同一处。）
    补一条阴性对照：给一条**永远匹配不上自己样本**的规则，自检必须报出来。
    """
    pats = leaks.default_patterns("someone")
    assert leaks.self_test(pats) == []

    broken = leaks.Pattern("坏规则", r"这串在样本里根本不存在", "完全不同的样本串", "测试")
    fails = leaks.self_test(pats + [broken])
    assert fails and any("坏规则" in f for f in fails), \
        "自检对一条抓不到自己样本的规则保持沉默——那它证明不了任何事：%r" % (fails,)


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


def test_channel_args_reach_builtin_kinds(tmp_path):
    """内置起法也要能传标志（`args`）——否则「给审核员放行只读命令」只能绕 exec，
    而 exec 要求手写 argv 与 harness 名，容易把两个 CLI 记成同一个 harness。

    真实事故：三家审核员里两家被权限白名单挡住跑不了代码，最强的可执行验证全没拿到。
    """
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    cfg = Config(project="p", brief="b", out_dir="o", repo="/tmp/repo",
                 reviewers=[], channels={}, gates=None)
    extra = ["--allowedTools", "Bash(python3:*),Read"]

    cl = Channel("c", "claude-cli", model="m1", args=extra)
    argv, _, writes = channels.build(cl, Reviewer("r", "c"), cfg, "PROMPT")
    assert argv[:3] == ["claude", "-p", "PROMPT"]
    assert "--model" in argv and argv[argv.index("--model") + 1] == "m1"
    assert argv[-2:] == extra, "claude-cli：额外标志拼在末尾"
    assert writes is False

    cx = Channel("c", "codex-cli", args=extra)
    argv2, _, writes2 = channels.build(cx, Reviewer("r", "c"), cfg, "PROMPT")
    assert argv2[-2:] == ["-o", "__OUT__"] or "__OUT__" in argv2
    # codex 的 prompt 是**位置参数**：标志必须插在它之前，否则会被当成 prompt 内容
    assert argv2.index(extra[0]) < len(argv2) - 1
    assert argv2[-1] == "PROMPT"
    assert writes2 is True


def test_exec_channel_rejects_args(tmp_path):
    """exec 已经把 argv 完全交给你了——再配 args 只会让人猜哪一处生效，直接报错。"""
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    cfg = Config(project="p", brief="b", out_dir="o", repo="/tmp/repo",
                 reviewers=[], channels={}, gates=None)
    ch = Channel("c", "exec", argv=["x", "{prompt}"], args=["--flag"])
    with pytest.raises(channels.ChannelError):
        channels.build(ch, Reviewer("r", "c"), cfg, "PROMPT")


def test_channel_args_loaded_from_config(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text(
        "project: p\nrepo: .\nbrief: b.md\nout_dir: out\n"
        "channels:\n"
        "  c1: {kind: claude-cli, model: m, args: ['--allowedTools', 'Read']}\n"
        "reviewers: [{name: a, channel: c1, vendor: va}]\n", encoding="utf-8")
    ch = load(str(p)).channels["c1"]
    assert ch.args == ["--allowedTools", "Read"]


def test_gate_hint_explains_zero_findings():
    """0 条发现必须说清**是哪一种 0**。

    真实事故：审核员交了 21KB 有内容的结论，全写成标题式（`### F1 …`），
    门禁按列名解析 → 0 条 → 整轮白跑；而当时的诊断只有「发现 0 条（标记 0）」，
    使用者不知道该改什么。
    """
    from quorum.config import Config, Gates
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[], channels={},
                 gates=Gates(min_bytes=10, min_findings=1,
                             require_sections=["最脆弱"]))
    heading_style = ("# 结论\n\n## 1. 严重度表\n\n### F1 · 某处不对\n"
                     "问题描述足够长足够长。\n\n## 最脆弱\n状态轴没有正例。\n")
    g = gates.evaluate(cfg, heading_style, rc=0, seconds=10)
    assert g.findings == 0
    assert "严重度" in g.hint and "表格" in g.hint      # 说清是「不是表格」
    assert "严重度" in g.summary()

    # 另一种 0：表在，但每行问题列是空话
    thin = ("| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n| 🔴 | a.py | 不行 | x |\n"
            "\n## 最脆弱\n无。\n")
    g2 = gates.evaluate(cfg, thin, rc=0, seconds=10)
    assert g2.findings == 0 and "不足 8 字" in g2.hint


def test_prompt_states_output_contract():
    """工单提示里必须写明输出契约——让格式要求**难以违反**，而不是事后判它违规。"""
    from quorum.channels import DEFAULT_PROMPT
    assert "严重度" in DEFAULT_PROMPT and "表格" in DEFAULT_PROMPT


def test_ledger_row_survives_unclosed_code_span():
    """台账骨架生成的行，单元格数必须等于列数。

    事故（2026-10-01 真实踩到）：headline 里一个**未闭合的反引号**跨过截断点
    （``…，且 `--top`` 正好在第 100 个字符处被切），于是 `_split_row` 按 markdown 规则
    把代码段内的 `|` 当成字面竖线，**8 列的行被切成 5 格**——`status` / `check`
    落到别的格子里：那一行明明填了 ✅，`verify` 却报「无断言」。
    看报告的人会以为是自己没填。

    断言用**列数**，不用「某个字符串在不在」——后者被解释性注释满足过。
    """
    hl = ("注释 `top 13：12 个内容组件 + 教育背景` 与实际不符：实际入选 11"
          "（project 5 + experience 3 + skill 2 + education 1），且 `--top 根本没生效")

    class _C:
        project = "t"
    c = plate.Cluster(rows=[plate.Row("x", "v", "h", "🟢", "`build.sh:45`", hl, "")])
    c.members = [0]

    row = [l for l in plate.dispose_skeleton(_C(), [c]).split("\n") if l.startswith("| 1 |")][0]
    header_cols = len(plate.dispose_skeleton(_C(), [c]).split("\n")[6].split("|")) - 2
    assert len(gates._split_row(row)) == header_cols, \
        "骨架行被切成 %d 格，应为 %d 格：%r" % (len(gates._split_row(row)), header_cols, row[-60:])


def test_location_column_is_clipped_too_not_just_headline():
    """`位置` 列也必须走 `clip_cell` —— 它和「问题」列一样是表格单元格。

    上面那条只保住了 **headline** 那一列；位置列当时还是裸切片 `[:50]`，于是同一类事故
    换个列又发生了一次：位置写成
    `` `assemble.py:257-260, 496-509`（`MUST_TONES`/`NICE_ ``（第 50 字正好落在代码段里），
    未被闭合的反引号让 `_split_row` 把后面全吞进同一格 —— **那两行的 `status` 直接消失**，
    `verify` 报「无断言 6 条」而作者以为自己填了 5 条。

    教训：上一轮修了「一处」，就以为修了「一类」。**同类的第二列没人去看。**
    """
    loc = "`assemble.py:257-260, 496-509`（`MUST_TONES`/`NICE_TONES` 这两个判定表）"

    class _C:
        project = "t"
    c = plate.Cluster(rows=[plate.Row("x", "v", "h", "🟢", loc, "问题正文足够长" * 4, "")])
    c.members = [0]

    txt = plate.dispose_skeleton(_C(), [c])
    row = [l for l in txt.split("\n") if l.startswith("| 1 |")][0]
    header_cols = len(txt.split("\n")[6].split("|")) - 2
    assert len(gates._split_row(row)) == header_cols, \
        "位置列被切断代码段 → 行被切成 %d 格，应为 %d 格：%r" % (
            len(gates._split_row(row)), header_cols, row[-60:])


# ------------------------------------------------------------------ 并发
# 「并发」不能靠读代码断言，得让进程自己留证据：每个桩把 (起, 止) 写进同一个文件，
# 跑完看这些区间有没有重叠。串行 → 永不相交；并发 → 必有相交。
# **两个方向都要测**：只测「并发时相交」的话，那条断言可能只是因为「进程启动本来就重叠」
# 而通过，而那样它什么都没证明。
PROBE_PY = '''\
import os, sys, time
name = os.environ["PROBE_NAME"]
t0 = time.time()
time.sleep(1.0)
t1 = time.time()
with open(os.environ["PROBE_TRACE"], "a") as f:
    f.write("%s %.4f %.4f\\n" % (name, t0, t1))
sys.stdout.write("""## 第二节 · 逐条发现

| 严重度 | 位置 | 问题 | 证据 |
|---|---|---|---|
| 🟡 | `x.py:1` | 探针 %s 报的发现 | 自证 |

## 最脆弱的一环

- 探针
""" % name)
'''


def _probe_cfg(tmp_path, n=3):
    """一套最小配置：n 个审核员全走同一个「会留时间戳」的桩。"""
    d = tmp_path / "j"
    d.mkdir()
    (d / "b.md").write_text("# 工单\n\n随便。\n", encoding="utf-8")
    (d / "probe.py").write_text(PROBE_PY, encoding="utf-8")
    trace = d / "trace.txt"
    lines = ["project: j", "repo: .", "brief: b.md", "out_dir: out", 'sources: ["."]',
             "channels:", "  probe:", "    kind: fake", '    argv: ["python3", "probe.py"]',
             "reviewers:"]
    for i in range(n):
        lines.append("  - {name: r%d, channel: probe, vendor: v%d, role: primary,"
                     " env: {PROBE_NAME: r%d, PROBE_TRACE: %s}}" % (i, i, i, trace))
    lines.append('gates: {min_bytes: 10, min_findings: 1, require_sections: ["最脆弱"]}')
    (d / "review.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(d / "review.yaml"), str(trace)


def _intervals(trace):
    out = []
    for line in open(trace):
        p = line.split()
        if len(p) == 3:
            out.append((p[0], float(p[1]), float(p[2])))
    return out


def _overlaps(iv):
    return [(iv[i], iv[j]) for i in range(len(iv)) for j in range(i + 1, len(iv))
            if iv[i][1] < iv[j][2] and iv[j][1] < iv[i][2]]


def test_jobs_runs_concurrently(tmp_path):
    """`--jobs 0`（= 全部并发）必须**真的**并发跑。"""
    cfg, trace = _probe_cfg(tmp_path)
    main(["run", "--config", cfg, "--all", "--jobs", "0"])
    iv = _intervals(trace)
    assert len(iv) == 3, "三个审核员都该留下时间戳，实际 %r" % (iv,)
    assert _overlaps(iv), "三家之间没有任何执行区间重叠——它们其实是串行跑完的：%r" % (iv,)


def test_jobs_1_is_serial_negative_control(tmp_path):
    """阴性对照：`--jobs 1` 时**不许**有时间重叠。

    没有这一条，上面那个测试可能只是因为「进程启动本来就重叠」而通过，什么都证明不了。
    """
    cfg, trace = _probe_cfg(tmp_path)
    main(["run", "--config", cfg, "--all", "--jobs", "1"])
    iv = _intervals(trace)
    assert len(iv) == 3
    assert not _overlaps(iv), "声称串行，却出现了时间重叠：%r" % (_overlaps(iv),)


def test_jobs_keeps_each_reviewers_output_separate(demo):
    """并发不许串味：每个审核员的结论里只有**它自己**的内容。

    「上下文干净」在 quorum 里是两层：进程之间靠「各起独立进程」；进程内靠
    「临时文件 / 结论路径 / env 都不共享」。这条测的是后者在产物上留下的痕迹。
    """
    cfg = os.path.join(demo, "review.yaml")
    main(["run", "--config", cfg, "--all", "--jobs", "0"])
    mine = {"alpha": "分母不是 100", "beta": "重跑可复现", "gamma": "报告数字可重算"}
    for n, marker in mine.items():
        text = open(os.path.join(demo, "out", "demo-findings-%s.md" % n), encoding="utf-8").read()
        assert marker in text, "%s 的结论里没有它自己的内容（%r）" % (n, marker)
        for other, om in mine.items():
            if other != n:
                assert om not in text, "%s 的结论里混进了 %s 的内容（%r）" % (n, other, om)


def test_jobs_does_not_change_the_conclusions(demo):
    """并发只改**怎么跑**，不改**跑出什么**：同一份材料，串行与并发逐字节相同。"""
    cfg = os.path.join(demo, "review.yaml")
    names = ["alpha", "beta", "gamma"]
    paths = {n: os.path.join(demo, "out", "demo-findings-%s.md" % n) for n in names}

    main(["run", "--config", cfg, "--all", "--jobs", "1"])
    serial = {n: open(paths[n], encoding="utf-8").read() for n in names}
    for n in names:
        os.unlink(paths[n])

    main(["run", "--config", cfg, "--all", "--jobs", "0"])
    for n in names:
        assert open(paths[n], encoding="utf-8").read() == serial[n], \
            "%s：串行与并发产出不一致——并发改变了结果，而不只是速度" % n


def test_jobs_negative_warns_without_attribution(tmp_path):
    """`--jobs>1` 时材料被改：告警**照发**，但必须注明归不到具体某一家。

    并发拿「谁改的」换来了「三家审的是同一时刻的材料」。那就得把这笔账说出来——
    不能悄悄退化成「什么都没发生」，那是本项目最反对的那种静默。
    """
    cfg, _ = _probe_cfg(tmp_path)
    d = os.path.dirname(cfg)
    with open(os.path.join(d, "probe.py"), "w", encoding="utf-8") as f:
        f.write(PROBE_PY.replace(
            "t1 = time.time()",
            't1 = time.time()\n'
            'open(os.path.join(os.path.dirname(os.environ["PROBE_TRACE"]), "b.md"),'
            ' "a").write("\\n<!-- 改动 -->\\n")'))
    main(["run", "--config", cfg, "--all", "--jobs", "0"])
    text = open(os.path.join(d, "out", "j-findings-r0.md"), encoding="utf-8").read()
    assert "材料在审核期间发生变化" in text, "材料被改了却没告警"
    assert "归不到具体某一家" in text, \
        "并发下必须说明归因已失效，而不是照抄串行那句「该审核员」"


# ------------------------------------------------------------ verify 的环境
def test_check_env_prefers_the_project_venv(tmp_path, monkeypatch):
    """check 的环境必须认**被审项目**的 venv，不能只认 quorum 自己的。

    真实事故：同一份台账，CI 判「说谎 **0**」、本地判「说谎 **12**」——
    差别只在 quorum 是**怎么装上去的**（CI 是 `pip install -e '.[dev]'`，pytest 与 quorum
    同 env；本地是 `uv tool install`，隔离 env 里没有 pytest）。两个都不是真相。
    """
    d = tmp_path / "proj"
    (d / ".venv" / "bin").mkdir(parents=True)
    first = ledger._check_env(str(d))["PATH"].split(os.pathsep)[0]
    assert first == str(d / ".venv" / "bin"), "项目自己的 venv 必须排在 PATH 最前"

    bare = tmp_path / "bare"
    bare.mkdir()

    # ⚠️ 把「跑 quorum 的那个解释器」**假装**成住在某个 .venv/bin 里。
    #
    # 为什么必须假装，而不能靠跑测试时真实的环境：下面那条断言要区分
    # 「**项目自己的** .venv/bin（不存在，不许塞）」和
    # 「**跑 quorum 的解释器自己**所在的 .venv/bin（合法）」。
    # 只有当天跑 pytest 的那个解释器碰巧住在 .venv/bin 里时，这个区分才被考到——
    # 而那样**同一条测试的结果就取决于用哪个解释器跑它**：
    #   `./.venv/bin/python -m pytest` → 红；`python3 -m pytest` → 绿；CI 用 setup-python → 绿。
    # 也就是说：那个「不许按路径结尾判」的守卫，自己会变成「按跑它的机器判」。
    # （2026-10-02，luna 的原始日志里露出来的副产品：它用 `.venv/bin/python` 跑 pytest，
    #   70 passed / 1 failed，而它没来得及把这条写进结论。）
    #
    # monkeypatch 之后，考的是**行为**而不是**环境**——换哪个解释器跑都考同一件事。
    fake = str(tmp_path / "somewhere" / ".venv" / "bin" / "python")
    monkeypatch.setattr(sys, "executable", fake)
    parts = ledger._check_env(str(bare))["PATH"].split(os.pathsep)

    assert str(bare / ".venv" / "bin") not in parts, \
        "没有 .venv 时把**项目自己的** .venv/bin 塞进了 PATH（那个目录不存在）"
    assert parts[0] == os.path.dirname(fake), \
        "没有项目 venv 时退回旧语义：用跑 quorum 的那个解释器"
    # 正例：那个目录**以 .venv/bin 结尾**，而它是合法的——旧断言正是在这里判错的。
    assert parts[0].endswith(os.path.join(".venv", "bin")), \
        "这个用例的前提是解释器所在目录以 .venv/bin 结尾，否则它考不到那条区分"


def test_check_leaks_skips_its_fixture_by_content_not_path(tmp_path):
    """自跳过必须**按内容认**，不能按路径认。

    真实事故（2026-10-02）：同一份仓库，`quorum check-leaks .` **本地 rc=1、CI rc=0**。
    差别只在 quorum 是**怎么被装上去的**：CI 是 `pip install -e`（`__file__` 就是仓库里那份），
    本地是 `uv tool install`（**拷贝**到 site-packages）→ `FIXTURE_FILE` 指向 site-packages，
    而被扫的是源码树 → 路径不相等 → 仓库自己那份 `leaks.py` 里的样例串全被报成真命中。

    这里直接模拟那场景：把模块源码**复制到别处**再扫——必须仍然跳过，
    同时**真的泄漏必须照样被扫出来**（否则就是把门禁整个关掉了）。
    """
    dst = tmp_path / "quorum"
    dst.mkdir()
    shutil.copy(os.path.join(ROOT, "quorum", "leaks.py"), dst / "leaks.py")
    # 邮箱**拼出来**，不写字面量——否则这行本身会被仓库自己的 check-leaks 扫到，
    # 而这个仓库唯一的豁免是「leaks.py 自己」。（我第一版就踩了：改完 rc 从 0 变 1。）
    fake_mail = "someone" + "@" + "realmail.com"
    (tmp_path / "real.txt").write_text("联系 %s\n" % fake_mail, encoding="utf-8")

    pats = leaks.default_patterns("someoneelse")
    hits = leaks.scan(str(tmp_path), pats, skip_files=(leaks.FIXTURE_FILE,))

    assert "邮箱" in hits, "真的泄漏没被扫出来——跳过范围过宽了，等于把门禁关掉"
    rows = hits["邮箱"]
    # 元组是 (相对路径, 行号, 命中片段) —— 中间那个是**行号**，别拿它当路径
    assert any(r[0].endswith("real.txt") for r in rows), "real.txt 的邮箱没被扫到"
    assert not any("leaks.py" in r[0] for r in rows), \
        "复制到别处的 leaks.py 没被跳过（这正是本地 rc=1 的原因）：%r" % (rows,)


# ------------------------------------------------------- 通道 · opencode-cli
# ------------------------------------------------ 通道 · opencode-cli
# 「够严」的那一组：三条底线（兜底 deny / 外部目录 deny / 编辑 deny）。
# 测试里反复用，所以提出来——写死三遍的话，将来改底线会漏改一处。
_GOOD_OPENCODE_PERM = ('{"permission": {"*": "deny", "external_directory": "deny",'
                       ' "edit": "deny", "read": "allow", "bash": "allow"}}')


def test_opencode_channel_is_a_real_third_harness():
    """`opencode-cli` 存在的理由是**保住 harness 那一轴**，不是多接一个厂商。

    背景：编码套餐（火山 AgentPlan 等）只吃 chat/completions，而 codex 只认 responses。
    只有 claude-cli / codex-cli 两种内置起法时，「全用订阅跑」与「harness 跨开」二选一
    ——而那是个假两难：opencode 自带协议适配，两样都能要。
    """
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    cfg = Config(project="p", brief="b", out_dir="o", repo="/tmp/repo",
                 reviewers=[], channels={}, gates=None)
    ch = Channel("c", "opencode-cli", model="ark/deepseek-v4-pro-260425",
                 env={"OPENCODE_CONFIG_CONTENT": _GOOD_OPENCODE_PERM})
    argv, env, writes = channels.build(ch, Reviewer("r", "c"), cfg, "PROMPT")

    # 逐字比：写成一串 `or` 的断言会被左边那一项满足，等于没测右边
    assert argv == ["opencode", "run", "--pure", "--dir", "/tmp/repo",
                    "-m", "ark/deepseek-v4-pro-260425", "PROMPT"]
    assert writes is False                     # 结论走 stdout，不写文件
    assert "opencode-cli" in channels.READONLY
    assert ch.harness_name == "opencode-cli"


def test_opencode_channel_requires_an_explicit_permission_policy():
    """**这条是拿一整轮换来的。**

    2026-10-02 第一次跑 opencode 通道：审核员交了 473 字节的**过程叙述**、0 条发现，
    而退出码是 0。原因是 opencode 的默认权限里 `external_directory` 是 `"ask"`，
    headless 跑没有人能批准 → 工具调用被自动拒绝 → 审核员卡住。

    所以这条通道**必须**自带 `permission`：不写，`channels.build` 直接拒绝启动。
    「权限来自用户级配置」正是这个工具栽过的那个坑——配置里看不见的东西在生效，
    而失败长得像成功。
    """
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    cfg = Config(project="p", brief="b", out_dir="o", repo="/tmp/repo",
                 reviewers=[], channels={}, gates=None)

    def build(env):
        return channels.build(Channel("c", "opencode-cli", model="m", env=env),
                              Reviewer("r", "c"), cfg, "PROMPT")

    for label, env in [("完全没有 OPENCODE_CONFIG_CONTENT", {}),
                       ("有配置但没有 permission",
                        {"OPENCODE_CONFIG_CONTENT": '{"provider": {}}'}),
                       ("配置不是合法 JSON", {"OPENCODE_CONFIG_CONTENT": "{oops"})]:
        with pytest.raises(channels.ChannelError) as e:
            build(env)
        assert "permission" in str(e.value), "%s：报错没说清要写什么" % label

    _argv, _env, _w = build({"OPENCODE_CONFIG_CONTENT": _GOOD_OPENCODE_PERM})


def test_permission_check_rejects_wide_values_not_just_missing_field():
    """**「字段在」不等于「限制生效」——这条测的就是那道差。**

    第一版只检查 `permission` 这个键在不在。2026-10-02 的复核对它当场打脸（luna 独立发现）：
    下面三种**全部通过**了旧检查，而它们一个比一个宽——

      * `"permission": "allow"`                          → 全放行，含写与读到工作目录之外
      * `"permission": {}`                               → 空对象 = 回落到默认 = 照样卡死
      * `"permission": {"external_directory": "allow"}`  → 明确允许读到工作目录之外

    也就是说：**为「存在字段 ≠ 限制生效」写的那道守卫，本身就是装饰性的。**
    这正是这个项目反复讲的那件事，只不过这次落在自己头上。
    """
    from quorum import channels
    from quorum.config import Channel, Config, Reviewer
    cfg = Config(project="p", brief="b", out_dir="o", repo="/tmp/repo",
                 reviewers=[], channels={}, gates=None)

    def build(perm_json):
        return channels.build(
            Channel("c", "opencode-cli", model="m",
                    env={"OPENCODE_CONFIG_CONTENT": perm_json}),
            Reviewer("r", "c"), cfg, "PROMPT")

    for label, perm in [("全放行字符串", '"allow"'),
                        ("ask 字符串", '"ask"'),
                        ("空对象（回落默认）", "{}"),
                        ("只允许外部目录", '{"external_directory": "allow"}'),
                        ("没有兜底 deny", '{"external_directory": "deny", "edit": "deny"}'),
                        ("没有禁写", '{"*": "deny", "external_directory": "deny"}')]:
        with pytest.raises(channels.ChannelError) as e:
            build('{"permission": %s}' % perm)
        assert "底线" in str(e.value) or "不是对象" in str(e.value), \
            "%s：报错没点出是哪条底线没守住" % label


def test_three_builtin_harnesses_have_three_distinct_names():
    """harness 名撞了，plate 的独立性注记就会静默失效——这是那件事的守卫。"""
    from quorum.config import Channel
    names = {Channel("a", k).harness_name
             for k in ("claude-cli", "codex-cli", "opencode-cli")}
    assert names == {"claude-cli", "codex-cli", "opencode-cli"}


# ---------------------------------------------------------------- preflight
def test_preflight_poisons_credentials_and_nothing_else():
    """毒化必须**精确**，两个方向都有代价。

    多毒一个 `CLAUDE_CODE_MAX_OUTPUT_TOKENS`，每个 claude-cli 通道都会报红——
    一条「每次都响」的假警报会把真警报淹掉。少毒一个，那条通道就永远「验过」。
    """
    from quorum.preflight import credential_keys
    env = {"ANTHROPIC_BASE_URL": "https://x/api",       # 端点，不是凭据
           "ANTHROPIC_AUTH_TOKEN": "sk-real",           # ← 凭据
           "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000",    # 含 TOKEN 但不是凭据
           "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "262144",  # 同上
           "ARK_KEY": "sk-real",                        # ← 凭据
           "OPENAI_API_KEY": "sk-real"}                 # ← 凭据
    assert credential_keys(env) == ["ANTHROPIC_AUTH_TOKEN", "ARK_KEY", "OPENAI_API_KEY"]


def test_preflight_self_test_can_actually_fail(monkeypatch):
    """预检自己的自检**必须能红**——否则它证明不了任何事。

    ⚠️ 原来的写法是 `assert preflight.self_test() == 0`：那是「全绿」，不是「能红」。
    （2026-10-02，kimi 独立点到。）这里补一条阴性对照：把自检里用的桩换坏，
    它必须报错——否则那条「四档都能落到位」的声称就只是一句话。
    """
    from quorum import preflight
    assert preflight.self_test() == 0, "自检本身先得是绿的"

    # 「正常（错凭据被拒）」那一档用的桩换成「永远回话」→ 它会落到 hijacked，
    # 与期望的 verified 不符 → 自检必须返回 1
    monkeypatch.setattr(preflight, "_STUB_GOOD_BAD", preflight._STUB_ALWAYS_OK)
    assert preflight.self_test() == 1, "桩被换坏了，自检却还是绿的"


# ---------------------------------------------------- 门禁 · 空洞行不许过
def test_is_text_survives_multibyte_cut_at_chunk_boundary(tmp_path):
    """4096 字节的切点劈开多字节字符时，**不许把整个文件判成「非文本」**。

    2026-10-02 修「跳过不上报」时炸出来的：`_is_text` 只读前 4096 字节再整体
    `decode("utf-8")`。这个仓库中文为主，一个汉字 3 字节，4096 几乎必然落在字的中间
    → `UnicodeDecodeError` → 判「非文本」→ **整个文件跳过不扫**。

    实测被误判的：`README.md` / `CONTRACT.md` / `quorum/snapshot.py` / `reviews/review.yaml`。
    也就是说这个公开仓的泄漏门禁**一直在静默跳过它自己的大部分中文文件**——
    而这件事在此之前完全不可见，因为「跳过」从来没上报过。

    两个方向都要守：中文文件必须判文本；**真二进制必须照样判非文本**（否则就是把门禁关掉）。
    """
    assert 4096 % 3 != 0, "这个测试的前提是 4096 会劈开一个 3 字节的汉字"
    zh = tmp_path / "zh.md"
    zh.write_text("中" * 2000, encoding="utf-8")          # 6000 字节，切点必在字中间
    assert leaks._is_text(str(zh)), "中文文件被误判成非文本——它会被整个跳过不扫"

    binary = tmp_path / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02\xff\xfe" * 100)
    assert not leaks._is_text(str(binary)), "真二进制被判成了文本"

    utf16 = tmp_path / ".env"
    utf16.write_bytes("KEY=whatever\n".encode("utf-16"))   # 含 \x00 → 非文本，走 skipped
    assert not leaks._is_text(str(utf16))


def test_skipped_files_are_reported_not_swallowed(tmp_path):
    """跳过的文件**必须**被报出来——「没扫到」和「没命中」在输出里必须长得不一样。

    真实缺陷（2026-10-02，kimi 与 luna 各自独立发现）：`scan()` 把二进制/超大/非 UTF-8
    的文件追加到一个**局部变量** `skipped`，返回前从没写回 `hits["__skipped__"]`。
    于是那段「⚠️ 有 N 个文件跳过未扫」永远打不出来，`cmd_leaks` 的
    `hits.pop("__skipped__", [])` 拿到的永远是空列表。

    后果不是「少一条提示」：**一个 UTF-16 编码的 .env 会连同密钥一起被静默跳过**，
    而输出干净得像没事。
    """
    # UTF-16 的文件 `_is_text` 判 false → 走 skipped 那条路。
    # 密钥**拼出来**：写死字面量的话，本文件自己会被 check-leaks 判成泄漏
    # （本仓唯一的豁免是 leaks.py 自己）。这个坑我自己又踩了一次。
    tok = "sk-" + "abcdefghijklmnop"
    (tmp_path / ".env").write_bytes(("KEY=%s\n" % tok).encode("utf-16"))
    hits = leaks.scan(str(tmp_path), leaks.default_patterns("nobody"))
    assert hits.get("__skipped__"), "跳过的文件没被报出来（这正是静默盲区）：%r" % (hits,)
    assert any(".env" in s for s in hits["__skipped__"])


def test_clean_scan_says_clean_not_found(tmp_path):
    """干净目录必须明说「未发现任何命中」，不许打一句「在…下发现：」然后空着。

    真实缺陷（2026-10-02，kimi 与 luna 各自独立实测）：`render()` 里那个
    `out = ["在 %s 下发现：", ""]` 被写在 `if/else` **之外**，无条件覆盖掉
    「未发现任何命中」。**读起来像有发现。**
    """
    (tmp_path / "ok.md").write_text("the quick brown fox\n", encoding="utf-8")
    pats = leaks.default_patterns("nobody")
    text = leaks.render(leaks.scan(str(tmp_path), pats), str(tmp_path), [], pats)
    assert "未发现任何命中" in text, "干净目录打成了「发现：」——读起来像有发现：%r" % text
    assert "发现：" not in text


def test_preflight_does_not_paint_a_hang_as_verified(tmp_path):
    """阴性对照**没返回**时，不许写成「端点确实校验了凭据」。

    真实性质（2026-10-02，kimi 与 luna 各自独立发现）：claude-cli 拿到坏凭据**不是报错，
    是挂住**（实测：真 key 7~9s 正常返回，坏 key 90s 没动静）。旧版把这一档和
    「凭据被拒」写进同一句话，还下了结论「端点确实校验了这一路凭据」——
    而看门狗杀掉的进程，我们只知道它**没有成功**，不知道它**为什么**没成功。

    **把不确定状态写成确定结论，正是这个工具最反对的那件事。**
    """
    from quorum import preflight
    stub = ["/bin/sh", "-c",
            'if [ "$FAKE_KEY" = "%s" ]; then sleep 30; fi; '
            'echo QUORUM_PREFLIGHT_PROBE' % preflight.POISON]
    cfg = preflight._synthetic(str(tmp_path), stub, {"FAKE_KEY": "real"})
    v = preflight.probe_reviewer(cfg, "probe", timeout_s=6)

    assert v.status == "not_refuted", "挂住的阴性对照被判成了 %s" % v.status
    assert v.blocks is False, "判不了 ≠ 判否；拦人只留给「有唯一检测手段」的那一档"
    assert "没有被证明" in v.detail, "结论句还在下断言：%s" % v.detail
    assert "端点确实校验了这一路凭据" not in preflight.render([v]), \
        "报告里仍然写着「端点确实校验了凭据」——那正是把不确定状态绿化"


def test_backup_never_clobbers_an_existing_backup(tmp_path):
    """同一秒内的第二次留档**不许覆盖**第一次。

    真实缺陷（2026-10-02，luna 独立发现）：留档名是 `path.HHMMSS.bak`，同一秒内对同一
    路径调用两次时，第二次的目标已经存在，`shutil.move` 会**静默覆盖**掉第一份。
    一个**立刻失败**的通道（凭据错、CLI 没装）在一秒内跑完两轮是可能的。

    换个说法：**用来防丢东西的那一步，自己有一个会丢东西的窗口。**
    """
    p = tmp_path / "x.md"
    p.write_text("第一份\n", encoding="utf-8")
    k1 = gates.protect_existing(str(p))
    assert k1 and "第一份" in open(k1, encoding="utf-8").read()

    p.write_text("第二份\n", encoding="utf-8")
    k2 = gates.protect_existing(str(p))
    assert k2 != k1, "同一秒内的第二次留档撞了同一个名字"
    assert "第一份" in open(k1, encoding="utf-8").read(), "第一份留档被覆盖了"
    assert "第二份" in open(k2, encoding="utf-8").read()


def test_demo_gates_are_green_on_broken_material_but_can_go_red(tmp_path):
    """demo 的两道门禁必须**真的能失败**，否则它们只是道具。

    事故一、事故二的共同性质是「门禁绿、材料错」——所以它们的演示需要有个**真门禁**
    在那儿绿着。2026-10-02 的复核发现（luna）：`demo/README.md` 一直在解释
    「事故二的门禁为什么绿」，**而 demo 里当时根本没有那道门禁**，
    只有事故一的 `gate.py`。那句话是散文，读者验证不了。

    补了 `metric_gate.py` 之后，两个方向都要钉住：
      * 坏材料上它**绿**（这才是事故本身）
      * 把区块里的数字改坏，它**红**（这才说明它是门禁而不是道具）
    """
    import subprocess
    root = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(root)
    subprocess.run([sys.executable, "demo/project/make.py"], cwd=root,
                   check=True, capture_output=True)

    g = subprocess.run([sys.executable, "demo/project/gate.py"], cwd=root, capture_output=True)
    assert g.returncode == 0, "事故一的门禁本该永远为真（那正是事故）"

    m = subprocess.run([sys.executable, "demo/project/metric_gate.py"], cwd=root,
                       capture_output=True)
    assert m.returncode == 0, "事故二的门禁本该在「正文被擦光」的报告上绿着"

    # 阴性对照：把区块里的数字改坏 → 必须红
    rep = os.path.join(root, "demo", "project", "report.md")
    bak = open(rep, encoding="utf-8").read()
    try:
        open(rep, "w", encoding="utf-8").write(bak.replace("41.0%", "99.9%"))
        bad = subprocess.run([sys.executable, "demo/project/metric_gate.py"], cwd=root,
                             capture_output=True)
        assert bad.returncode != 0, "数字改坏了门禁还是绿的——那它不是门禁，是道具"
    finally:
        open(rep, "w", encoding="utf-8").write(bak)


def test_hollow_findings_do_not_pass_the_gate():
    """**位置或证据列空着 = 没有任何可核实的东西**，不该算发现。

    工单的硬约束写着「每条必须带『我怎么查出来的』」，而旧门禁只量「问题」列的长度：
    `| 🔴 |  | 这一行的问题描述凑够了八个字 |  |` 是一张**能过门禁的空表**。
    （2026-10-02，luna 独立发现；kimi 的同类观察落在同一处。）

    但**不能一刀切**：列名认不出来时位置列会整列为空，那种情形下丢发现是错的
    （缺的是信息，不是结论）——见 `test_row_alias.py` 里那条回归。
    """
    from quorum.config import Config, Gates
    cfg = Config(project="p", brief="b", out_dir="o", repo=".",
                 reviewers=[], channels={},
                 gates=Gates(min_bytes=10, min_findings=1, require_sections=[]))

    hollow = ("| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n"
              "| 🔴 |  | 这一行的问题描述凑够了八个字 |  |\n")
    assert gates.evaluate(cfg, hollow, rc=0, seconds=1).findings == 0, "空表拿了绿灯"

    real = ("| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n"
            "| 🔴 | a.py:1 | 这一行的问题描述凑够了八个字 | `cmd` → 命中 |\n")
    assert gates.evaluate(cfg, real, rc=0, seconds=1).findings == 1


def test_snapshot_glob_walks_into_matched_directories(tmp_path):
    """`sources` 里的 glob 命中**目录**时必须走进去。

    旧版是 `[p for p in glob.glob(...) if os.path.isfile(p)]` —— 目录被 `isfile`
    过滤掉、整个丢掉。于是 `sources: ["src/*"]` 会静默漏掉所有子目录里的材料，
    而指纹照样是绿的：**「没扫到」和「没变化」在指纹上长得一模一样**。
    （2026-10-02，luna 独立发现。）
    """
    (tmp_path / "pkg" / "sub").mkdir(parents=True)
    (tmp_path / "pkg" / "a.py").write_text("A", encoding="utf-8")
    (tmp_path / "pkg" / "sub" / "b.py").write_text("B", encoding="utf-8")
    from quorum.config import Config, Gates
    cfg = Config(project="p", brief="b", out_dir="o", repo=str(tmp_path),
                 reviewers=[], channels={}, gates=Gates(), sources=["pkg/*"])
    before = snapshot.take(cfg).digest
    (tmp_path / "pkg" / "sub" / "b.py").write_text("B-CHANGED", encoding="utf-8")
    assert snapshot.take(cfg).digest != before, \
        "glob 命中的目录没被走进去——子目录里的变化看不见"


def test_cluster_prunes_bridges():
    """链式桥接必须被拆开——它与「**宁可拆细，不要合错**」直接冲突。

    贪心合并的条件是「与簇里**任意一条**像」。于是 A~B、B~C 而 A≁C 时三条落进同一簇，
    标签照样按整簇的 primary vendor 打出「跨模型族一致」，而首尾两条其实没关系。
    （2026-10-02，luna 独立发现；kimi 从另一端点到同一处。）

    N=2 时不可能触发（两家最多两条），所以这是为 N≥3 准备的守卫。
    """
    rows = [
        plate.Row("A", "va", "ha", "🔴", "f.py:1",
                  "cache invalidation makes metric overstated", "e1", "primary"),
        plate.Row("B", "vb", "hb", "🔴", "f.py:2",
                  "cache invalidation makes metric overstated backfill script truncated",
                  "e2", "primary"),
        plate.Row("C", "vc", "hc", "🔴", "g.py:9",
                  "backfill script truncated report missing body", "e3", "primary"),
    ]
    clusters = plate.cluster(rows)
    for c in clusters:
        assert len(c.members) <= 2 or all(
            c.rows[0].reviewer in (c.rows[i].reviewer, c.rows[0].reviewer)
            for i in range(len(c.rows))), "桥接没被剪"
    sizes = sorted(len(c.members) for c in clusters)
    assert sizes == [1, 2], "A+B 该在一起、C 该被剪出去，实际 %r" % (sizes,)


def test_json_keeps_each_reviewers_own_problem():
    """JSON 输出也必须逐条列原话——`render()` 在 Markdown 里的承诺不能只在那里成立。

    旧版 `to_json` 的 sources 只有 `{reviewer, evidence}`，`problem` 用的是某一家的那一句。
    消费 JSON 的下游会把一簇当成一个结论，而一簇的成立条件只是「相似度够」。
    （2026-10-02，luna 独立发现。）
    """
    rows = [plate.Row("A", "va", "ha", "🔴", "f.py:1", "第一条措辞足够长足够长", "eA", "primary"),
            plate.Row("B", "vb", "hb", "🔴", "f.py:1", "第二条措辞足够长足够长", "eB", "primary")]
    c = plate.cluster(rows)[0]
    data = json.loads(plate.to_json([c], {"A": "s1", "B": "s1"}))
    srcs = data["findings"][0]["sources"]
    assert len(srcs) == 2
    assert {s["problem"] for s in srcs} == {"第一条措辞足够长足够长", "第二条措辞足够长足够长"}, \
        "JSON 里只剩一句 problem——逐家原话丢了"


def test_preflight_flags_a_channel_that_ignores_its_credential(tmp_path):
    """**这条测的就是 2026-10-02 那场事故的形状**：凭据换成错的，进程却照样回话。

    桩与真实 CLI 同形：无论给什么凭据都回话 → 说明凭据根本没被用上。
    真实世界里它就是「请求被路由到了别处，而结论还挂着声明的来源标签」。
    """
    from quorum import preflight
    cfg = preflight._synthetic(str(tmp_path),
                               ["/bin/sh", "-c", "echo ANYTHING"],
                               {"FAKE_KEY": "whatever"})
    v = preflight.probe_reviewer(cfg, "probe", timeout_s=30)
    assert v.status == "hijacked"
    assert v.blocks is True and preflight.exit_code([v]) == 1
    assert v.poisoned == ["FAKE_KEY"]


def test_preflight_needs_a_positive_control(tmp_path):
    """**死通道不许被判成「已核实」。**

    第一版只有阴性对照。实测发现 claude-cli 拿到坏凭据**不是报错，是挂住**——
    于是「没成功」同时对应「凭据被拒」和「这条通道根本起不来」两种现实，
    而分不开就会把死通道报成「端点属实」。阳性对照把基线钉住，两者才分得开。
    """
    from quorum import preflight
    cfg = preflight._synthetic(str(tmp_path),
                               ["/bin/sh", "-c", "echo nope >&2; exit 1"],
                               {"FAKE_KEY": "whatever"})
    v = preflight.probe_reviewer(cfg, "probe", timeout_s=30)
    assert v.status == "channel_down", "死通道被判成了 %s" % v.status
    assert v.blocks is False, "判不了 ≠ 判否；拦人要只留给「有唯一检测手段」的那一档"


def _run_cfg(tmp_path, argv_yaml):
    """最小可跑的 run 配置：一个 exec 桩通道 + 一个审核员。"""
    key = tmp_path / "key.txt"
    key.write_text("real-key", encoding="utf-8")
    (tmp_path / "brief.md").write_text("# 工单\n", encoding="utf-8")
    p = tmp_path / "review.yaml"
    p.write_text(
        "project: p\nbrief: brief.md\nout_dir: out\nrepo: .\n"
        "channels:\n  c:\n    kind: exec\n    argv: %s\n"
        "    env: {FAKE_KEY_FILE: %s}\n"
        "reviewers:\n  - {name: r, channel: c, vendor: v}\n"
        "gates: {min_bytes: 10, min_findings: 1, require_sections: []}\n"
        % (argv_yaml, key), encoding="utf-8")
    return str(p)


def test_run_refuses_to_start_reviewers_when_preflight_fails(tmp_path):
    """**预检必须在花掉一整轮之前拦住。**

    这条守的是**接线**，不是函数：`probe_reviewer` 返回值再对，`cmd_run` 没接上就等于没有。
    桩无视凭据、永远回话 —— 等价于「请求被劫走」。
    """
    cfg = _run_cfg(tmp_path, "['/bin/sh', '-c', 'echo QUORUM_PREFLIGHT_PROBE']")
    assert main(["run", "--all", "--config", cfg]) == 2, "预检没过却没拦住"
    out = tmp_path / "out"
    assert not out.exists() or not list(out.glob("*.md")), "预检没过，却已经有结论落盘了"


def test_run_skips_preflight_only_when_told_explicitly(tmp_path, monkeypatch):
    """跳过必须**明写**（`--no-preflight`），默认不许跳。"""
    from quorum import preflight
    cfg = _run_cfg(tmp_path, "['/bin/sh', '-c', 'echo QUORUM_PREFLIGHT_PROBE']")
    called = []
    monkeypatch.setattr(preflight, "preflight", lambda *a, **k: called.append(1) or [])
    # 桩产出没有发现表 → 内容门不过 → 3；这正说明它**跑到了**起进程那一步
    assert main(["run", "--all", "--config", cfg, "--no-preflight"]) == 3
    assert called == [], "--no-preflight 仍然跑了预检"


# ------------------------------------------------- preflight · 模型身份探针
def _served_cfg(tmp_path, declared, served):
    """造一条通道：声明的模型 = declared，本地假端点回的 = served。"""
    from quorum import preflight
    sink = []
    preflight._serve(served, sink)
    env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % sink[0], "FAKE_KEY": "real"}
    return preflight._synthetic(str(tmp_path), preflight._STUB_GOOD_BAD, env,
                                model=declared)


def test_model_probe_flags_alias_downgrade(tmp_path):
    """**这条测的是真实观测到的别名降级**。

    第三方端点上，声明的模型名未必是实际服务的那个档位：实测同一个端点上
    `glm-5.3-pro` → `glm-5.3`、`kimi-k2-thinking` → `kimi-k2.7-code`、
    `minimax-m2.7` → `minimax-m3`。你付的钱和你以为买的档位不是一回事，
    而这件事在审核结论里**完全看不出来**——结论只会写「我们用 glm-5.3-pro 审的」。
    """
    from quorum import preflight
    v = preflight.probe_reviewer(_served_cfg(tmp_path, "glm-5.3-pro", "glm-5.3"),
                                 "probe", timeout_s=30)
    assert v.model_status == "mismatch"
    assert v.served_model == "glm-5.3"
    # **不拦人**：这是配置选择问题，不是「结论来源是假的」。只有 hijacked 拦。
    assert v.blocks is False and preflight.exit_code([v]) == 0


def test_model_probe_does_not_cry_wolf_on_naming_differences(tmp_path):
    """探针的第一版风险是**假警报**，不是漏报。

    实测三种命名差异都不是换模型：`glm-5.3-flash`→`glm-5-3-flash`（点转横线）、
    `doubao-seed-2-1-pro-260915`→`doubao-seed-2-1-pro`（日期后缀被剥）、
    `deepseek-v4-pro-260425`→`deepseek-v4-pro`。
    不归一化就会把它们全报成 mismatch —— 而**一条每次都响的警报会被学会无视**，
    那比没有警报更糟。
    """
    from quorum import preflight
    for declared, served in [("glm-5.3-flash", "glm-5-3-flash"),
                             ("doubao-seed-2-1-pro-260915", "doubao-seed-2-1-pro"),
                             ("deepseek-v4-pro-260425", "deepseek-v4-pro")]:
        v = preflight.probe_reviewer(_served_cfg(tmp_path, declared, served),
                                     "probe", timeout_s=30)
        assert v.model_status == "match", \
            "%s vs %s 被误判成 %s——这是假警报" % (declared, served, v.model_status)


def test_model_probe_is_honest_when_it_cannot_see_the_endpoint(tmp_path):
    """验不了就说验不了，**不许默认成通过**。

    端点藏在 CLI 自己的注册表里时（典型：opencode 的内置 provider），
    quorum 从配置里读不到它。这一档必须落成 `unverifiable` 并在报告里点名，
    不能因为「没发现异常」就写成 match —— 那正是这个项目反复批评的那种绿。
    """
    from quorum import preflight
    cfg = preflight._synthetic(str(tmp_path), preflight._STUB_GOOD_BAD,
                               {"FAKE_KEY": "real"}, model="some/model")
    v = preflight.probe_reviewer(cfg, "probe", timeout_s=30)
    assert v.model_status == "unverifiable", "读不到端点却报了 %s" % v.model_status
    assert "没验过" in preflight.render([v])


def test_ipv4_rule_excludes_loopback_but_still_catches_private_ips(tmp_path):
    """收窄 IPv4 规则时**两个方向都要守住**。

    这条规则叫「内网/公网 IP」，它想抓的是**指明某个网络**的地址。
    `127.0.0.1` 每台机器都有、零信息量，却出现在每个本地服务与每条测试里——
    不排除它，门禁会在每个含本地端点的仓库上报红，然后所有人学会无视这个档位
    （**假警报淹没真警报**，`docs/LESSONS.md` 有专条）。

    但收窄的同时**不能把它收没了**：真的内网地址必须照样抓到，
    否则这就不再是「收窄」而是「关掉」。两个方向各一条断言。
    """
    loop = "127." + "0.0.1:15721"          # 拼出来：本文件自己也要过这个门禁
    private = "10." + "20.30.40"
    (tmp_path / "a.md").write_text("本地代理 %s\n内网主机 %s\n" % (loop, private),
                                   encoding="utf-8")
    hits = leaks.scan(str(tmp_path), leaks.default_patterns("nobody"))
    rows = hits.get("IPv4", [])
    assert any(private in r[2] for r in rows), "真内网地址没被抓到——这不是收窄，是关掉"
    assert not any("127." in r[2] for r in rows), "环路地址被报成了泄漏（假警报）：%r" % (rows,)
