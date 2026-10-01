"""quorum 的命令行入口。

四条命令，对应复核闭环的四段：

    quorum run          起独立进程审核（干净上下文）→ 结论落盘 + 记账
    quorum plate        把几家的结论对齐成交叉表（一致 / 独有）→ 可导出处置骨架
    quorum verify       跑处置台账里每行的 `check` 断言 → 抓「台账说谎」
    quorum check-leaks  泄漏自检（公开仓的守门人），`--self-test` 证明检查本身能失败

设计取舍：**只通过 CLI 暴露，不提供 import API。** 需要编程接入就消费 `--json` 的输出契约
——这样上层不必跟这个包的版本绑定，非 Python 的项目也能用。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime

from . import channels, gates, ledger, leaks, plate, snapshot
from .config import ConfigError, load

OK, FAIL = "✅", "✗"


def _hdr(t: str) -> None:
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


# --------------------------------------------------------------------- run
def cmd_run(a) -> int:
    cfg = load(a.config)
    want = [r.name for r in cfg.reviewers] if a.all else [a.reviewer]
    for n in want:
        cfg.reviewer(n)                            # 提前校验名字

    snap = snapshot.take(cfg)
    print("项目 %s · 审核员 %s" % (cfg.project, ", ".join(want)))
    print(snap.header_line().lstrip("> "))
    if a.dry_run:
        for n in want:
            r = cfg.reviewer(n)
            argv, env, _ = channels.build(cfg.channels[r.channel], r, cfg, "<prompt>")
            print("\n[%s] %s\n  env: %s" % (n, channels.quote(argv),
                                            ", ".join(sorted(env)) or "（无）"))
        return 0

    rc_all = 0
    for n in want:
        r = cfg.reviewer(n)
        out = cfg.out_path(n)
        stamp = datetime.now().strftime("%Y-%m-%d")
        raw = cfg.raw_path(n, stamp)
        kept = gates.protect_existing(out)
        if kept:
            print("已有结论非空 → 先留档为 %s" % os.path.basename(kept))

        argv, env, writes_file = channels.build(cfg.channels[r.channel], r, cfg,
                                                channels.build_prompt(cfg, r))
        tmp_out = tempfile.mktemp(prefix="quorum-%s-" % n, suffix=".md")
        if writes_file:
            argv = [tmp_out if x == "__OUT__" else x for x in argv]
            stdout_path = tmp_out + ".stream"
        else:
            stdout_path = tmp_out

        print("\n── %s（通道 %s · 上限 %ds）" % (n, r.channel, r.timeout_s))
        t0 = datetime.now()
        rc = gates.run_with_timeout(argv, env, r.timeout_s, stdout_path, raw, cwd=cfg.repo)
        secs = int((datetime.now() - t0).total_seconds())

        text = gates.read_text(tmp_out)
        result = gates.evaluate(cfg, text, rc, secs)
        snap_after = snapshot.take(cfg)
        extra = ""
        if rc != 0:
            extra = ("进程退出码 %d（信号/异常收尾）。**四道内容门全过即接受**——"
                     "退出码描述的是进程，不是材料。" % rc) if result.passed else \
                    "进程退出码 %d，且内容门未过。" % rc
        if snap_after.digest != snap.digest:
            extra = (extra + " " if extra else "") + \
                    "⚠️ **材料在审核期间发生变化**（%s → %s），结论可能对应中间的某个状态。" % (
                        snap.digest, snap_after.digest)

        if result.passed:
            body = gates.header(cfg, n, snap.header_line(), extra) + text
            gates.atomic_write(out, body)
            print("  %s 通过（%s）→ %s" % (OK, result.summary(), os.path.relpath(out, cfg.repo)))
        else:
            fail_path = "%s.FAILED-%s.md" % (out[:-3], datetime.now().strftime("%H%M"))
            gates.atomic_write(fail_path, text or "（空产出）")
            print("  %s 未过门禁（%s）→ %s" % (FAIL, result.summary(), os.path.relpath(fail_path, cfg.repo)))
            rc_all = 3
        gates.log(cfg, n, result, a.label)
        for f in (tmp_out, tmp_out + ".stream"):
            if os.path.exists(f):
                os.unlink(f)
    return rc_all


# ------------------------------------------------------------------- plate
def cmd_plate(a) -> int:
    cfg = load(a.config)
    rows, snaps = plate.collect(cfg)
    if not rows:
        print("没收到任何发现——先跑 `quorum run`"); return 1
    clusters = plate.cluster(rows)
    if a.json:
        print(plate.to_json(clusters, snaps))
    else:
        print(plate.render(cfg, clusters, snaps))
    if a.dispose:
        path = a.dispose if isinstance(a.dispose, str) else os.path.join(cfg.out_dir_abs, "%s-dispose.md" % cfg.project)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(plate.dispose_skeleton(cfg, clusters))
        print("\n处置台账骨架 → %s" % path)
    if a.json and a.dispose:
        pass
    return 0


# ------------------------------------------------------------------ verify
def cmd_verify(a) -> int:
    cfg = load(a.config)
    path = a.ledger or cfg.ledger or os.path.join(cfg.out_dir_abs, "%s-dispose.md" % cfg.project)
    # 路径语义：**命令行给的按 CWD 解析，配置里声明的按配置文件目录解析**（最小惊讶原则）。
    if not os.path.isabs(path) and not os.path.exists(path):
        cand = os.path.join(os.path.dirname(cfg.path), path)
        if os.path.exists(cand):
            path = cand
        elif os.path.exists(os.path.join(cfg.repo, path)):
            path = os.path.join(cfg.repo, path)
    entries = ledger.parse(path)
    if not entries:
        print("台账里没有可解析的行：%s" % path); return 1
    verdicts = ledger.run_checks(entries, cfg.repo, a.timeout)
    print(ledger.render(verdicts))
    return ledger.exit_code(verdicts, a.strict)


# -------------------------------------------------------------- check-leaks
def cmd_leaks(a) -> int:
    pats = leaks.default_patterns(a.username)
    if a.config:
        try:
            cfg = load(a.config)
            for name, rx in cfg.leak_patterns.items():
                pats.append(leaks.Pattern(name, rx, a.self_sample or "sample", "来自配置"))
        except ConfigError:
            pass

    if a.self_test:
        bad = [f for f in leaks.self_test(pats) if "样本" not in f]     # 配置规则可自供样本
        _hdr("自检：这些规则能不能抓到自己种的样本")
        if bad:
            for b in bad:
                print("  %s %s" % (FAIL, b))
            print("\n自检未通过——**一份不能失败的检查等于没有检查**。")
            return 1
        print("  %s 全部规则都能抓到自己种的样本，且不误伤安全文本" % OK)
        if not a.dir:
            return 0

    if not a.dir:
        print("用法：quorum check-leaks <目录> [--self-test]")
        return 1
    hits = leaks.scan(a.dir, pats, skip_files=(leaks.FIXTURE_FILE,) + tuple(os.path.abspath(x) for x in a.ignore))
    print(leaks.render(hits, a.dir))
    return 1 if hits else 0


# -------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="quorum", description="多模型交叉审计：独立进程 · 冻结工单 · 交叉表 · 可执行断言")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="起独立进程审核")
    r.add_argument("--config", required=True)
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--reviewer")
    g.add_argument("--all", action="store_true")
    r.add_argument("--label", default="")
    r.add_argument("--dry-run", action="store_true", help="只打印将执行的命令（不需要密钥）")
    r.set_defaults(func=cmd_run)

    t = sub.add_parser("plate", help="交叉表")
    t.add_argument("--config", required=True)
    t.add_argument("--json", action="store_true", help="输出机器可读契约（接你自己的流程）")
    t.add_argument("--dispose", nargs="?", const=True, default=False, help="同时导出处置台账骨架")
    t.set_defaults(func=cmd_plate)

    v = sub.add_parser("verify", help="跑处置台账里的 check 断言")
    v.add_argument("--config", required=True)
    v.add_argument("--ledger", default="")
    v.add_argument("--strict", action="store_true", help="「无断言」也算失败")
    v.add_argument("--timeout", type=int, default=120)
    v.set_defaults(func=cmd_verify)

    k = sub.add_parser("check-leaks", help="泄漏自检")
    k.add_argument("dir", nargs="?", default="")
    k.add_argument("--config", default="")
    k.add_argument("--username", default="")
    k.add_argument("--self-test", action="store_true")
    k.add_argument("--ignore", action="append", default=[], help="额外跳过的文件（重复可加）")
    k.add_argument("--self-sample", default="")
    k.set_defaults(func=cmd_leaks)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as e:
        print("配置错误：%s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
