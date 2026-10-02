"""通道：怎么起一个「干净上下文」的审核进程。

四条内置通道：

* ``claude-cli`` —— 任何 **Anthropic 兼容端点**（官方、各厂商的兼容网关）都能接。
  接一个新厂商 = 在 ``review.yaml`` 里加一段 env，**不动代码**。
  约定（两种引用方式，密钥永远不进配置文件、也不进命令行参数——命令行会进 ps 与 shell 历史）：
    * ``X_FILE: /path`` → 读文件内容填进 ``X``
    * ``X: ${ENV_VAR}`` → 从环境变量取值；变量未设置时报错而不是静默传空串
* ``codex-cli``  —— 本机 codex CLI，``exec -s read-only``，结论写文件。
  只认 ``wire_api="responses"``——**只提供 chat/completions 的端点接不了它**。
* ``opencode-cli`` —— 本机 opencode CLI（它自己的 agent harness）。
  自带协议适配，所以**只提供 chat/completions 的编码套餐**也能接；
  这让 harness 那一轴可以跨开，而不必被迫换协议。
* ``fake``       —— 不调模型的桩，用于测试与 demo（公开仓必须能无密钥跑通全流程）。

通道只负责「怎么起进程」。「审得对不对」由工单与门禁负责，两者刻意分离。
"""
from __future__ import annotations

import json
import os
import shlex
from typing import Dict, List, Tuple

from .config import Channel, Config, Reviewer


class ChannelError(SystemExit):
    pass


# opencode 的权限**默认值**里，`external_directory` 和 `doom_loop` 是 `"ask"`。
# headless 跑的时候没有人能批准 —— 于是这些调用被**自动拒绝**，审核员卡住，
# 最后交回一段「我先读取…我正在对照…」的过程叙述，而**退出码是 0**。
#
# 2026-10-02 真实发生：一个 opencode 通道的审核员因此整轮白跑（473 字节、0 条发现）。
# 它当时想读的是仓库里的 `templates/review.yaml`，但路径算错成了工作目录**之外**的路径。
#
# 所以这个通道**必须**在配置里写死 `permission`，不写就拒绝启动。
# 理由是同一句话：「权限来自用户级配置」正是这个工具栽过的那个坑 ——
# 配置里看不见的东西在生效，而失败长得像成功。
_OPENCODE_PERM_HELP = """\
opencode-cli 通道必须在 OPENCODE_CONFIG_CONTENT 里写死一组**够严**的 `permission`。不写的话，
opencode 的默认权限里 `external_directory` 是 "ask"，而 headless 跑没有人能批准 ——
工具调用会被**自动拒绝**，审核员卡住，最后交回一段过程叙述而不是结论，**退出码还是 0**。

最小可用的一组（放行只读工具与 bash，禁一切写与对外）：

  {"permission": {
     "*": "deny",
     "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny", "*.env.example": "allow"},
     "glob": "allow", "grep": "allow", "bash": "allow", "task": "allow",
     "edit": "deny", "webfetch": "deny", "websearch": "deny",
     "external_directory": "deny", "question": "deny", "skill": "deny"}}

注：`read` 用对象写法是为了保住 opencode 自带的「默认不读 .env」。
写成 `"read": "allow"` 会把那条保护一起关掉。

要完全自定义就别用这个通道 —— 写 `exec`，把 argv 摆出来。\
"""

# 只要求「`permission` 这个键存在」是不够的 —— 那正是这个工具最反对的那类检查：
# **验的是「你做了那个动作」，不是「那个问题解决了」。**
# 2026-10-02 的复核当场把这条打了出来（luna 独立发现）：下面三种**全都能通过**旧检查。
#     {"permission": "allow"}                          ← 全放行，含写与读到工作目录之外
#     {"permission": {}}                               ← 空对象 = 回落到默认 = 照样卡死
#     {"permission": {"external_directory": "allow"}}  ← 明确允许读到工作目录之外
# 所以这里改为**核对内容**：三条底线，少一条就拒绝启动。
_OPENCODE_MUST_DENY = {
    "*": "兜底必须是 deny——否则没列到的权限会走 opencode 的默认值（多数是 allow）",
    "external_directory": "必须显式 deny——它的默认值是 \"ask\"，headless 下等于卡死；"
                          "而且允许它等于让审核员读到工作目录之外",
    "edit": "必须显式 deny——写权限不该给一条只读复核通道",
}


def _check_opencode_permission(env: Dict[str, str], name: str) -> None:
    raw = env.get("OPENCODE_CONFIG_CONTENT", "")
    if not raw:
        raise ChannelError(
            "opencode-cli 通道 %s 没有 OPENCODE_CONFIG_CONTENT —— 那么权限来自**用户级配置**，"
            "工具看不见它。\n\n%s" % (name, _OPENCODE_PERM_HELP))
    try:
        conf = json.loads(raw)
    except ValueError as e:
        raise ChannelError(
            "opencode-cli 通道 %s 的 OPENCODE_CONFIG_CONTENT 不是合法 JSON，"
            "无法核对权限：%s\n\n%s" % (name, e, _OPENCODE_PERM_HELP))
    if not isinstance(conf, dict) or "permission" not in conf:
        raise ChannelError(
            "opencode-cli 通道 %s 的配置里没有 `permission`。\n\n%s" % (name, _OPENCODE_PERM_HELP))
    perm = conf["permission"]
    if not isinstance(perm, dict):
        raise ChannelError(
            "opencode-cli 通道 %s 的 `permission` 是个 %r，不是对象。"
            "`\"allow\"` 是**全放行**；`\"ask\"` 在 headless 下等于全部卡死。\n\n%s"
            % (name, perm, _OPENCODE_PERM_HELP))
    bad = [k for k, _why in _OPENCODE_MUST_DENY.items() if perm.get(k) != "deny"]
    if bad:
        raise ChannelError(
            "opencode-cli 通道 %s 的 `permission` 里有 %d 条底线没守住：\n%s\n\n"
            "（只检查「permission 这个键在不在」是不够的——"
            "`{\"permission\": \"allow\"}` 和 `{\"permission\": {}}` 都能通过那种检查，"
            "而前者全放行、后者等于什么都没限制。）\n\n%s"
            % (name, len(bad),
               "\n".join("  - `%s`：%s" % (k, _OPENCODE_MUST_DENY[k]) for k in bad),
               _OPENCODE_PERM_HELP))


DEFAULT_PROMPT = """你是独立外部审计员，与本项目无关。工作目录是仓库根 {repo}。

读 {brief}，**严格按它执行独立复核**。

要点：
- 只读：不改任何现有文件、不新建文件、不重跑训练、不调用任何 LLM API（纯本地脚本可以跑）
- 工单里给出的输出格式**直接作为你的回复正文**
- **发现必须是一张 Markdown 表格，且表头含「严重度」列**——门禁按列名解析；
  写成标题式（`### F1 …`）会被判「0 条发现」，整轮白跑
- 引用的每个数字必须**自己从数据文件重算**，不从任何文档抄
- 你的回复会被原样存档为审核结论，请直接输出结论文本，不要写任何文件。

如果你发现工单里的某条断言站不住，直接说站不住并给出你的证据——**推翻作者的结论是本工作的价值所在**。
"""


def build_prompt(cfg: Config, reviewer: Reviewer) -> str:
    return DEFAULT_PROMPT.format(repo=cfg.repo, brief=cfg.brief_for_prompt())


def _resolve_env(env: Dict[str, str]) -> Dict[str, str]:
    """把 ``X_FILE=/path`` 解析成 ``X=<文件内容>``。密钥不进配置、不进 argv。"""
    out: Dict[str, str] = {}
    for k, v in env.items():
        if k.endswith("_FILE"):
            p = os.path.expanduser(v)
            if not os.path.exists(p):
                raise ChannelError("通道 env %s 指向的文件不存在：%s" % (k, p))
            out[k[:-5]] = open(p, encoding="utf-8").read().strip()
        else:
            # 支持 `${VAR}` 引用环境变量——很多厂商把 token 放在环境变量里而不是文件里。
            v2 = os.path.expandvars(v)
            if "$" in v2 and v2 == v and "${" in v:
                raise ChannelError(
                    "通道 env %s 引用的环境变量没有设置：%s" % (k, v))
            out[k] = os.path.expanduser(v2)
    return out


def build(channel: Channel, reviewer: Reviewer, cfg: Config, prompt: str) -> Tuple[List[str], Dict[str, str], bool]:
    """返回 (argv, env, writes_to_file)。

    ``writes_to_file=True`` 表示该 CLI 自己写结论文件（如 codex 的 ``-o``），
    调用方不要重定向它的 stdout。
    """
    env: Dict[str, str] = {}
    for k, v in channel.env.items():
        env[k] = v
    env.update(reviewer.extra_env)
    env = _resolve_env(env)

    kind = channel.kind
    if kind == "claude-cli":
        argv = ["claude", "-p", prompt]
        if channel.model:
            argv += ["--model", channel.model]
        argv += list(channel.args)                 # 额外标志（权限白名单/sandbox/…）
        return argv, env, False

    if kind == "codex-cli":
        argv = ["codex", "exec", "-s", "read-only", "-C", cfg.repo,
                "--skip-git-repo-check"]
        if channel.model:
            argv += ["--model", channel.model]
        # 额外标志必须插在**位置参数 prompt 之前**：codex 的 prompt 是位置参数，
        # 写在它后面的标志会被当成 prompt 的一部分
        argv += list(channel.args)
        argv += ["-o", "__OUT__", prompt]          # __OUT__ 由 runner 替换成临时文件
        return argv, env, True

    if kind == "opencode-cli":
        # opencode 的**官方 harness**。加它的理由不是「多支持一个厂商」——
        # 是为了 harness 那一轴能真的跨开，而不必被迫换协议。
        #
        # 背景（2026-10-02 实测）：火山 AgentPlan 这类**编码套餐**只吃
        # chat/completions（`/api/coding/v1/chat/completions` → 200），
        # **不支持 Responses**（`/api/coding/v1/responses` → 404），而 codex 只认 responses。
        # 于是「全用订阅跑 + 保住 harness 轴」在 claude-cli/codex-cli 两种起法下做不到。
        # opencode 自带协议适配，正好补上这一格。
        #
        # `--pure`（不加载外部插件）**不给开关**：本地装了什么插件，是 review.yaml 里
        # 看不见的依赖——而「配置看不见的东西在生效」正是这个工具栽过的那个坑。
        # 要插件就写 `exec`，把 argv 明明白白摆出来。
        #
        # 密钥走 opencode 自己的 `{env:VAR}` 替换（配置内容里写 `"apiKey": "{env:ARK_KEY}"`），
        # 所以 env 里的凭据仍是**真凭据**、仍能被 `quorum preflight` 毒化——不需要为它开特例。
        #
        # `permission` 是**必填**，理由见 `_OPENCODE_PERM_HELP`：默认值里
        # `external_directory` 是 "ask"，headless 下等于自动拒绝，审核员会静默卡死。
        _check_opencode_permission(env, channel.name)
        argv = ["opencode", "run", "--pure", "--dir", cfg.repo]
        if channel.model:
            argv += ["-m", channel.model]
        argv += list(channel.args)
        argv += [prompt]
        return argv, env, False

    if kind == "exec":
        # 通用通道：**任何** CLI，自己写 argv。占位符 `{prompt}` / `{repo}` / `{out}`。
        #
        # 这个分支存在的理由：只有 claude-cli / codex-cli 两种内置起法的话，
        # harness 维度就是**封闭枚举**——想接 aider / gemini-cli / 自己写的脚本，
        # 必须改本文件的源码。那样「harness 可自定义」就是一句空话。
        if not channel.argv:
            raise ChannelError("exec 通道需要 argv（占位符：{prompt} / {repo} / {out}）")
        if channel.args:
            raise ChannelError(
                "exec 通道请把标志直接写进 argv，不要用 args: %r\n"
                "（两处都能加标志只会让人猜哪一处生效）" % (channel.args,))
        writes_to_file = any("{out}" in a for a in channel.argv)
        argv = [a.replace("{repo}", cfg.repo).replace("{prompt}", prompt)
                for a in channel.argv]
        return argv, env, writes_to_file

    if kind == "fake":
        # 桩通道：argv[0] 是一个脚本，读 FAKE_FINDINGS 指定的文件并打印。
        # 公开仓靠它做 e2e 测试与 demo —— 没有密钥也能跑完整流程。
        if not channel.argv:
            raise ChannelError("fake 通道需要 argv 指向一个脚本")
        return list(channel.argv) + [prompt], env, False

    raise ChannelError("未知通道类型：%s（可选 claude-cli | codex-cli | opencode-cli | exec | fake）"
                       "——想接别的 CLI 用 exec，不需要改源码" % kind)


READONLY = {
    # 通道层能不能**强制**只读。不能强制的，只能靠工单措辞 + 事后材料快照比对，
    # 这一点必须显式说出来，不能让大家以为「审核员只读」是都被保证了的。
    "codex-cli": "enforced（-s read-only）",
    "claude-cli": "NOT enforced（CLI 无沙箱开关；靠工单措辞 + 事后快照比对）",
    "opencode-cli": "NOT enforced（用 --pure 但没给沙箱标志；靠工单措辞 + 事后快照比对）",
    "exec": "未知（由你的 argv 决定；quorum 不保证）",
    "fake": "n/a",
}


def readonly_note(channel: Channel) -> str:
    return READONLY.get(channel.kind, "未知通道")


def describe(cfg: Config) -> str:
    """给日志用的一行摘要。"""
    parts = []
    for r in cfg.reviewers:
        parts.append("%s[%s@%s/%s]" % (r.name, r.vendor, r.harness, r.role))
    return " · ".join(parts)


def quote(argv: List[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
