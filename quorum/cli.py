"""quorum 的命令行入口。

五条命令，对应复核闭环的各段：

    quorum preflight    阴性对照预检：通道声明的端点到底属不属实（**能拦人**）
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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Tuple

from . import channels, gates, incidents, ledger, leaks, plate, preflight, snapshot
from .config import ConfigError, load

OK, FAIL = "✅", "✗"


def _hdr(t: str) -> None:
    print("\n" + "=" * 72 + "\n" + t + "\n" + "=" * 72)


# --------------------------------------------------------------------- run
@dataclass
class _One:
    """一个审核员的全部产出。

    **不在这里 print**：并发时几家的进度行会交错成一团，读不出谁是谁。
    由调用方按批、按审核员顺序原子打印（`console` 就是要打印的行）。
    """
    name: str
    text: str
    result: gates.GateResult
    rc: int
    secs: int
    ro: str
    console: List[str] = field(default_factory=list)


def _run_one(cfg, name: str, built: Tuple[List[str], Dict[str, str], bool]) -> _One:
    """跑一个审核员。副作用只落在**它自己的**路径上。

    并发下不串味，靠的是「每样东西每个审核员一份」，三样缺一不可：

    1. 临时文件带自己的前缀（``mkstemp(prefix="quorum-<name>-")``）；
    2. 结论 ``out_path(name)`` 与原始日志 ``raw_path(name, stamp)`` 都按名字分；
    3. **不碰 ``os.environ``** —— ``run_with_timeout`` 是 copy 一份再 update，
       所以两家通道的 env 不会互相渗。谁把某个通道的密钥写进全局环境，这一条就废了。

    这三条同时也是「各条 Agent 的上下文是干净的」在**本进程内**的全部含义：
    进程之间的干净由「各自起独立进程」保证，不靠这里。
    """
    argv, env, writes_file = built
    r = cfg.reviewer(name)
    stamp = datetime.now().strftime("%Y-%m-%d")
    console: List[str] = []
    kept = gates.protect_existing(cfg.out_path(name))
    if kept:
        console.append("已有结论非空 → 先留档为 %s" % os.path.basename(kept))

    fd, tmp_out = tempfile.mkstemp(prefix="quorum-%s-" % name, suffix=".md")
    os.close(fd)
    if writes_file:
        argv = [tmp_out if x == "__OUT__" else x for x in argv]
        stdout_path = tmp_out + ".stream"
    else:
        stdout_path = tmp_out

    ro = channels.readonly_note(cfg.channels[r.channel])
    console.append("\n── %s（通道 %s · 上限 %ds · 只读: %s）" % (name, r.channel, r.timeout_s, ro))
    if "NOT enforced" in ro:
        console.append("   ⚠ 该通道无法在 CLI 层强制只读——只读靠工单措辞，事后由材料快照比对兜底")

    t0 = datetime.now()
    rc = gates.run_with_timeout(argv, env, r.timeout_s, stdout_path,
                                cfg.raw_path(name, stamp), cwd=cfg.repo)
    secs = int((datetime.now() - t0).total_seconds())

    text = gates.read_text(tmp_out)
    result = gates.evaluate(cfg, text, rc, secs)
    for f in (tmp_out, tmp_out + ".stream"):
        try:
            if os.path.exists(f):
                os.unlink(f)
        except OSError:
            pass
    return _One(name, text, result, rc, secs, ro, console)


def cmd_run(a) -> int:
    cfg = load(a.config)
    want = [r.name for r in cfg.reviewers] if a.all else [a.reviewer]
    for n in want:
        cfg.reviewer(n)                            # 提前校验名字

    # 工单必须先存在：不存在的工单照样能跑起来（审核员会自己去找，找得到就照常产出），
    # 于是你会拿到一份「看起来正常、其实没按工单审」的结论——这是最贵的一类静默失败。
    if not os.path.exists(cfg.brief_abs):
        print("工单不存在：%s（配置里的 brief=%s）" % (cfg.brief_abs, cfg.brief), file=sys.stderr)
        return 2

    jobs = len(want) if int(a.jobs) <= 0 else int(a.jobs)

    # 起审核员**之前**先证明「这一路真的打到它声明的端点上」。
    #
    # 位置很关键：这是唯一一个能在**花掉一整轮**之前就发现「四条通道其实是同一个模型」
    # 的地方。四轮复核全废在这件事上，而当时没有任何检查会响 —— 因为 `vendor` 被定义为
    # 「声明」，工具不去核实。代价是每条通道多一次一 token 的请求。
    # `--dry-run` 不发请求（它本来就跑在任何凭据解析之前）。
    if not a.no_preflight and not a.dry_run:
        _hdr("阴性对照预检")
        verdicts = preflight.preflight(cfg, want, timeout_s=a.preflight_timeout, jobs=jobs)
        print(preflight.render(verdicts))
        if preflight.exit_code(verdicts):
            print("\n预检未过——**一个审核进程都没起**。\n"
                  "  这几条通道的凭据没有生效，说明配置里声明的端点不是实际在用的那个，\n"
                  "  跑出来的结论会带上**错误的来源标签**（四轮复核就是这么废掉的）。\n"
                  "  修好通道再跑；确定知道自己在干什么，用 --no-preflight 跳过。",
                  file=sys.stderr)
            return 2

    snap = snapshot.take(cfg)
    print("项目 %s · 审核员 %s · 并发 %d" % (cfg.project, ", ".join(want), min(jobs, len(want))))
    print("工单：%s" % cfg.brief_for_prompt())
    print(snap.header_line().lstrip("> "))
    if a.dry_run:
        for n in want:
            r = cfg.reviewer(n)
            argv, env, _ = channels.build(cfg.channels[r.channel], r, cfg, "<prompt>")
            print("\n[%s] %s\n  env: %s" % (n, channels.quote(argv),
                                            ", ".join(sorted(env)) or "（无）"))
        return 0

    rc_all = 0
    for start in range(0, len(want), jobs):
        chunk = want[start:start + jobs]

        # 起进程**之前**把这一批的通道全部解析完。一个通道配错（缺密钥文件、引用了没设的
        # 环境变量）应当在任何进程启动前就失败——并发放大了「同批其他几家白跑一趟」的代价。
        prepared: Dict[str, Tuple[List[str], Dict[str, str], bool]] = {}
        for n in chunk:
            r = cfg.reviewer(n)
            prepared[n] = channels.build(cfg.channels[r.channel], r, cfg,
                                         channels.build_prompt(cfg, r))

        # 快照按**批**取。`--jobs 1` 时一批一家，与旧版「每个审核员前后各取一次」逐字等价；
        # `--jobs N` 时是批级基线，代价是**归因变粗**：材料变了只知道「这一批里有人改了」，
        # 不知道是谁。换来的是三家审的是**同一份材料的同一时刻**，而不是先后三份。
        snap = snapshot.take(cfg)
        if len(chunk) == 1:
            ones = [_run_one(cfg, chunk[0], prepared[chunk[0]])]
        else:
            with ThreadPoolExecutor(max_workers=len(chunk)) as ex:
                ones = list(ex.map(lambda n: _run_one(cfg, n, prepared[n]), chunk))
        snap_after = snapshot.take(cfg)
        moved = snap_after.digest != snap.digest

        for one in ones:
            for line in one.console:
                print(line)

            extra = ""
            if one.rc != 0:
                extra = ("进程退出码 %d（信号/异常收尾）。**四道内容门全过即接受**——"
                         "退出码描述的是进程，不是材料。" % one.rc) if one.result.passed else \
                        "进程退出码 %d，且内容门未过。" % one.rc
            if moved:
                who = "该审核员" if len(chunk) == 1 else \
                      "本批 %d 家（并发，**归不到具体某一家**）" % len(chunk)
                extra = (extra + " " if extra else "") + \
                        "⚠️ **材料在审核期间发生变化**（%s → %s），%s 的结论可能对应中间的某个状态。" % (
                            snap.digest, snap_after.digest, who)

            out = cfg.out_path(one.name)
            if one.result.passed:
                if "NOT enforced" in one.ro:
                    extra = (extra + " " if extra else "") + "只读强度：未强制（%s）" % one.ro
                body = gates.header(cfg, one.name, snap.header_line(), extra) + one.text
                gates.atomic_write(out, body)
                print("  %s 通过（%s）→ %s" % (OK, one.result.summary(),
                                               os.path.relpath(out, cfg.repo)))
            else:
                fail_path = "%s.FAILED-%s.md" % (out[:-3], datetime.now().strftime("%H%M%S"))
                # 同一分钟内同一个审核员第二次失败会覆盖掉第一份失败产出——失败也要留档（唯一记账入口）
                gates.protect_existing(fail_path)
                gates.atomic_write(fail_path, one.text or "（空产出）")
                print("  %s 未过门禁（%s）→ %s" % (FAIL, one.result.summary(),
                                                    os.path.relpath(fail_path, cfg.repo)))
                if one.result.blocked:
                    print("     ↳ 这多半不是模型不行，而是它的沙箱不够：解封只读工具（或换通道）再跑一次")
                rc_all = 3
            gates.log(cfg, one.name, one.result, a.label)
    return rc_all


# --------------------------------------------------------------- preflight
def cmd_preflight(a) -> int:
    cfg = load(a.config)
    want = [r.name for r in cfg.reviewers] if a.all else [a.reviewer]
    for n in want:
        cfg.reviewer(n)
    _hdr("阴性对照预检 · %s" % cfg.project)
    verdicts = preflight.preflight(cfg, want, timeout_s=a.timeout, jobs=a.jobs)
    print(preflight.render(verdicts))
    return preflight.exit_code(verdicts)


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
        # 这里曾经是裸 `open(path,"w")` —— 与 docs/LESSONS.md 事故二**同一个写法**，
        # 而且默认路径正好就是用户填好的台账本身：一份填了 check/status 的台账会被整份擦成空骨架。
        kept = gates.protect_existing(path)
        if kept:
            print("\n已有台账非空 → 先留档为 %s" % os.path.basename(kept))
        gates.atomic_write(path, plate.dispose_skeleton(cfg, clusters))
        print("处置台账骨架 → %s" % path)
    if a.json and a.dispose:
        pass
    return 0


# ------------------------------------------------------------------ verify
def _record_incidents(cfg, a, ledger_path: str, verdicts) -> None:
    """把 🔴 落进**台账说谎记录**（事实档案）。

    **绝不影响 verify 的退出码。** 写档案失败只意味着"这次没留痕"，不意味着台账有了
    新结论——同 §「内容优先于退出码」。所以这里的失败一律打印、不抛出。

    ⚠️ 判据与 ``ledger.exit_code`` 一致：只有 ``LIE`` 是"唯一不可接受的一档"。
    ``error``（命令没跑起来）默认不记——它常属于「门禁的结果取决于跑它的机器」那一类。
    """
    if getattr(a, "no_incidents", False):
        return
    dest = a.incidents or cfg.incidents_abs
    if not dest:
        return                                   # 没配 = 不写。不是"写到默认路径"
    include_error = bool(getattr(a, "incidents_include_error", False))
    want = [v for v in verdicts
            if v.verdict == "LIE" or (include_error and v.verdict == "error")]
    if not want:
        return
    try:
        fp = snapshot.take(cfg).digest
    except Exception:                            # 指纹取不到不该挡住记录
        fp = ""
    try:
        new, upd = incidents.record(verdicts, ledger_path, dest, repo=cfg.repo,
                                    snapshot_fp=fp, include_error=include_error)
    except Exception as e:                       # 同上：不改变本次判定
        print("\n⚠️ 台账说谎记录写入失败（不影响本次判定）：%s" % e)
        return
    if new or upd:
        print("\n台账说谎记录 → %s（新增 %d · 更新 %d）" % (dest, new, upd))


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
    _record_incidents(cfg, a, path, verdicts)
    return ledger.exit_code(verdicts, a.strict)


# -------------------------------------------------------------- check-leaks
def cmd_leaks(a) -> int:
    pats = leaks.default_patterns(a.username)
    if a.config:
        try:
            cfg = load(a.config)
            for name, rx in cfg.leak_patterns.items():
                pats.append(leaks.Pattern(name, rx, a.self_sample or "sample", "来自配置"))
        except ConfigError as e:
            # ⚠️ 这里曾经是 `pass`（2026-10-02，kimi 独立发现）。配置文件写坏时，
            # 自定义的 leak_patterns 会被**静默丢弃**——扫描照跑、退出码照出，
            # 而你以为那几条规则在守着。**少守几条和全守住，输出长得一样。**
            print("⚠️ 配置 %s 没解析成功，自定义泄漏规则**一条都没生效**（用的是内置规则集）：%s"
                  % (a.config, e), file=sys.stderr)

    if a.self_test:
        # 这里曾经写成 `[f for f in self_test(pats) if "样本" not in f]`，
        # 而失败消息正是「正则抓不到自己种的样本」——**过滤条件恰好滤掉了它要抓的东西**，
        # 于是「检查能不能失败」的检查自己永远不能失败。配置带来的规则若没给样本，
        # 在 self_test 里跳过即可，不该在这一层做字符串过滤。
        bad = leaks.self_test(pats)
        _hdr("自检：这些规则能不能抓到自己种的样本")
        if bad:
            for b in bad:
                print("  %s %s" % (FAIL, b))
            print("\n自检未通过——**一份不能失败的检查等于没有检查**。")
            return 1
        print("  %s 全部规则都能抓到自己种的样本，且不误伤安全文本" % OK)
        if not a.dir:
            print("  （这只证明了**规则本身**有效；扫描覆盖面要传目录才验得了："
                  "`quorum check-leaks <dir> --self-test`）")
            return 0

    if not a.dir:
        print("用法：quorum check-leaks <目录> [--self-test]")
        return 1
    hits = leaks.scan(a.dir, pats, skip_files=(leaks.FIXTURE_FILE,) + tuple(os.path.abspath(x) for x in a.ignore))
    skipped = hits.pop("__skipped__", [])
    print(leaks.render(hits, a.dir, skipped, pats))
    # 退出码只看 fail 档：启发式规则的命中的是「看一眼」而不是「拦住提交」，
    # 否则 `~/workspace/` 这类正当占位符会把真警报淹掉。
    return 1 if leaks.failing(hits, pats) else 0


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
    r.add_argument("--jobs", type=int, default=0,
                   help="并发几个审核员（0 = 全部并发；1 = 串行，用于排查）")
    r.add_argument("--dry-run", action="store_true",
                   help="只打印将执行的命令与 env 的**键名**（不发起任何请求；"
                        "但仍会解析 `_FILE`，所以密钥文件必须存在）")
    r.add_argument("--no-preflight", action="store_true",
                   help="跳过阴性对照预检（默认跑；跳过 = 放弃「端点属不属实」这条唯一的事实侧核对）")
    r.add_argument("--preflight-timeout", type=int, default=120, help="每条通道预检的超时秒数")
    r.set_defaults(func=cmd_run)

    f = sub.add_parser("preflight", help="阴性对照预检：通道声明的端点属不属实")
    f.add_argument("--config", required=True)
    gf = f.add_mutually_exclusive_group(required=True)
    gf.add_argument("--reviewer")
    gf.add_argument("--all", action="store_true")
    f.add_argument("--timeout", type=int, default=120)
    f.add_argument("--jobs", type=int, default=0)
    f.set_defaults(func=cmd_preflight)

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
    v.add_argument("--incidents", default="",
                   help="台账说谎记录（事实档案）路径；覆盖配置里的 incidents。按 CWD 解析")
    v.add_argument("--no-incidents", action="store_true", help="本次不写记录（覆盖配置）")
    v.add_argument("--incidents-include-error", action="store_true",
                   help="连「命令没跑起来」也记（默认只记「台账说谎」）")
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
