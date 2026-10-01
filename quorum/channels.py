"""通道：怎么起一个「干净上下文」的审核进程。

三条内置通道：

* ``claude-cli`` —— 任何 **Anthropic 兼容端点**（官方、各厂商的兼容网关）都能接。
  接一个新厂商 = 在 ``review.yaml`` 里加一段 env，**不动代码**。
  约定（两种引用方式，密钥永远不进配置文件、也不进命令行参数——命令行会进 ps 与 shell 历史）：
    * ``X_FILE: /path`` → 读文件内容填进 ``X``
    * ``X: ${ENV_VAR}`` → 从环境变量取值；变量未设置时报错而不是静默传空串
* ``codex-cli``  —— 本机 codex CLI，``exec -s read-only``，结论写文件。
* ``fake``       —— 不调模型的桩，用于测试与 demo（公开仓必须能无密钥跑通全流程）。

通道只负责「怎么起进程」。「审得对不对」由工单与门禁负责，两者刻意分离。
"""
from __future__ import annotations

import os
import shlex
from typing import Dict, List, Tuple

from .config import Channel, Config, Reviewer


class ChannelError(SystemExit):
    pass


DEFAULT_PROMPT = """你是独立外部审计员，与本项目无关。工作目录是仓库根 {repo}。

读 {brief}，**严格按它执行独立复核**。

要点：
- 只读：不改任何现有文件、不新建文件、不重跑训练、不调用任何 LLM API（纯本地脚本可以跑）
- 工单里给出的输出格式**直接作为你的回复正文**
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
        return argv, env, False

    if kind == "codex-cli":
        argv = ["codex", "exec", "-s", "read-only", "-C", cfg.repo,
                "--skip-git-repo-check"]
        if channel.model:
            argv += ["--model", channel.model]
        argv += ["-o", "__OUT__", prompt]          # __OUT__ 由 runner 替换成临时文件
        return argv, env, True

    if kind == "fake":
        # 桩通道：argv[0] 是一个脚本，读 FAKE_FINDINGS 指定的文件并打印。
        # 公开仓靠它做 e2e 测试与 demo —— 没有密钥也能跑完整流程。
        if not channel.argv:
            raise ChannelError("fake 通道需要 argv 指向一个脚本")
        return list(channel.argv) + [prompt], env, False

    raise ChannelError("未知通道类型：%s（可选 claude-cli | codex-cli | fake）" % kind)


READONLY = {
    # 通道层能不能**强制**只读。不能强制的，只能靠工单措辞 + 事后材料快照比对，
    # 这一点必须显式说出来，不能让大家以为「审核员只读」是都被保证了的。
    "codex-cli": "enforced（-s read-only）",
    "claude-cli": "NOT enforced（CLI 无沙箱开关；靠工单措辞 + 事后快照比对）",
    "fake": "n/a",
}


def readonly_note(channel: Channel) -> str:
    return READONLY.get(channel.kind, "未知通道")


def describe(cfg: Config) -> str:
    """给日志用的一行摘要。"""
    parts = []
    for r in cfg.reviewers:
        parts.append("%s[%s/%s]" % (r.name, r.family, r.role))
    return " · ".join(parts)


def quote(argv: List[str]) -> str:
    return " ".join(shlex.quote(a) for a in argv)
