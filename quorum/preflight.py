"""阴性对照预检：证明每条通道**真的打到了它声明的端点**。

存在的理由（2026-10-02 事故，详见 `docs/LESSONS.md`）：

四条通道声明了四个厂商的模型，**连续四轮复核全部由同一个模型服务**。
根因是 `~/.claude/settings.json` 的 `env` 段**盖过进程环境变量**，通道里那几个
`ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` 一次都没生效，请求全被送进本机代理。

四轮没有一轮审出来，因为 **`vendor` 是「声明」**——工具看见的是通道**说自己**是谁，
而没有任何东西从**事实侧**反证过这句话。这一整轴从来没进过射程。

所以这里补一条对照，原理是实验室里最老的那一招：

    用**故意错误的凭据**发一次极小请求。
      报错        → 通道确实打到了它声明的端点      ✅ 通过
      **照样回话** → 请求被路由到别处了（凭据根本没用上）  ✗ 中止

关键在「照样回话」那一支：它对**正确的**实现是**不可能发生**的，所以它不是启发式，
是一条能红的断言。而它恰好精确命中本次症状。

**它证明什么、不证明什么**（别把它读大）：

* 证得了：**这一路请求确实经过了它声明的那个端点**（凭据在那里被校验）。
* 证不了：**模型是谁**。端点可以诚实地回话而背后挂着别的权重——
  那一轴没有外部可验的签名，工具只能记录声明，不能核实。
  换句话说，这条预检把「声明 vs 事实」的缺口**缩小了**，没有关掉它。
* 证不了：`exec` 通道里的 argv 干了什么。凭据在 env 里才毒得到。

用法：``quorum preflight --config review.yaml``（`run` 也会在起审核员之前自动跑一次）。
自检：``python3 -m quorum.preflight --self-test`` ——证明这条检查自己**能红**。
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, List, Tuple

from . import channels, gates
from .config import Channel, Config, Gates, Reviewer

# 凭据类环境变量。**精度全靠那个 `$` 锚点**，不是靠一张排除表。
#
# 这里原本还有一条 `_NOT_CRED`（排掉 MAX_ / _TOKENS / TOKENIZER / _URL / _FILE）。
# 变异测试证明它**一条都不生效**：`_CRED` 要求名字以 TOKEN/KEY/… **结尾**，
# 而 `…_TOKENS` 结尾是 S、`…_URL` 结尾是 URL —— 两者永远不可能同时成立；
# `_FILE` 更早就被 `_resolve_env` 剥成裸名了。一份**从不生效**的排除表看着像保护，
# 实际是装饰——留着它比删掉更危险，因为下一个人会以为精度是它给的。
#
# 残留的边界（写在这里，因为它不在射程内）：这把密钥**内联**进
# `OPENCODE_CONFIG_CONTENT` 这类大块配置里的通道，毒不到——它会落到 `no_credential`，
# 报告会明说「这次没验过」，不会假装通过。
_CRED = re.compile(r"(?:^|_)(?:API_?KEY|KEY|TOKEN|SECRET|PASSWORD|AUTH_TOKEN)$", re.I)

POISON = "quorum-preflight-deliberately-invalid-credential"
PROBE = "Reply with exactly: QUORUM_PREFLIGHT_PROBE"

OK, FAIL, WARN = "✅", "✗", "⚠"


@dataclass
class Verdict:
    reviewer: str
    channel: str
    kind: str
    # verified | hijacked | channel_down | egress_blocked | no_credential
    # | unsupported | error
    status: str
    detail: str = ""
    poisoned: List[str] = None
    endpoint: str = ""
    pos_secs: int = 0            # 阳性对照用时：阴性那条「没返回」全靠它才有意义
    # ---- 模型身份探针（第二天轴）----
    # match | mismatch | unverifiable | skipped
    model_status: str = "skipped"
    declared_model: str = ""
    served_model: str = ""
    model_detail: str = ""

    @property
    def blocks(self) -> bool:
        """只有 `hijacked` 拦人。

        「判不了」的那些档刻意**不**拦：把它们当失败会让预检变成一条随时误伤的闸门，
        而误伤的闸门会被关掉，关掉之后就什么都守不住了。拦人只留给
        **没有别的检测手段**的那一种——被劫持在后续任何环节都看不见，
        它是这里唯一「只有这条预检能发现」的失败。

        `egress_blocked` 同样**不拦人**，尽管它比 channel_down 确定得多：
        探针可能误报（被测 CLI 也许有探针没有的网络能力），而可能误报的闸门
        迟早被关掉——关掉之后就什么都守不住了。它的价值在于**说清病因**，
        不在于拦人。
        """
        return self.status == "hijacked"


def credential_keys(env: Dict[str, str]) -> List[str]:
    return sorted(k for k in env if _CRED.search(k))


def _scrub(text: str, env: Dict[str, str]) -> str:
    """把 env 里的凭据值从**要外露的文本**里抹掉。

    ⚠️ 这不是可选的。`_resolve_env` 已经把 `*_FILE` 解成**裸值**放回 env，
    所以任何从子进程带出来、再打进终端的文本都可能夹着真密钥。白名单式的
    正则匹配靠不住——2026-10-08 作者本人就是因为脱敏正则只匹配 `sk-` 前缀、
    漏了 `tp-` 前缀，把一个真实 token 打进了对话记录。这里改成**按值替换**：
    env 里凡是 `_CRED` 命中的键，它的值在文本里一律换成 `***`。
    """
    for k in credential_keys(env):
        v = env.get(k) or ""
        if len(v) >= 8:
            text = text.replace(v, "***")
    return text


# ------------------------------------------ 网络出口探针（L2, 2026-10-08 补）
#
# `channel_down` 此前把**四种现实**压成一档：凭据错 / 端点错 / CLI 没装 /
# **网络出口不通**。前一、二种还能换个凭据逼近，第三种能直接看出来，第四种
# **此前没有任何检测手段** —— 而它是最常见的一类（代理没起、代理地址写错、
# 主机被丢包、DNS 不通）。
#
# 2026-10-08 的实际代价：一条 opencode 通道连续失败，真因是 gpt-6-luna 只走
# Responses 协议而那条路径被区域封锁，叠加「Node 不读 macOS 系统代理、只认
# HTTP(S)_PROXY」，被当成「通道起不来」排查了很久。
#
# ⚠️ **探针必须和被测 CLI「同样瞎」，这是要害**：只用**子进程真正拿到的**代理
#   变量（`os.environ` 叠加通道 env 之后的结果），不掺 quorum 自己的偏好，
#   也不用 `urllib` 的默认路径（它会 `getproxies()` 去读 `os.environ`）。
#   **探针比被测对象聪明的那一刻，它证明的东西就没了。** 所以这里用裸 socket：
#   既没有隐式的代理发现，也不会被「服务器不肯答某个路径」骗到。
#
# ⚠️ 上面那次事故**不是传输层问题**（opencode.ai 的 TCP 是通的），所以本探针
#   抓不到它 —— 那一类靠 L1 带出子进程的理由。别把这一档读成比它实际更强。
_REACH_TIMEOUT = 15


def channel_endpoint(ch: Channel, env: Dict[str, str]) -> str:
    """这条通道的端点：配置里 `endpoint:` 优先，否则取 env 里的 base URL。

    `opencode-cli` 的端点藏在 **CLI 自己的注册表**里，配置看不见 —— 不显式声明的话，
    可达性探针与模型身份探针**双双读不到它**，而这恰好是 preflight 仅有的两轴。
    """
    return (ch.endpoint
            or env.get("ANTHROPIC_BASE_URL")
            or env.get("OPENAI_BASE_URL")
            or "").rstrip("/")


def _dial(host: str, port: int) -> Tuple[str, str]:
    """TCP 连一次。返回 (档位, 说明)，档位 ∈ {reachable, unreachable}。

    为什么是**传输层**而不是发个 HTTP 请求就完：实测（2026-10-08）

        opencode.ai         DNS 0.0s   TCP:443 OK 0.2s
        api.openai.com      DNS 0.0s   TCP:443 超时        ← 包被丢
        api.xiaomimimo.com  DNS 0.0s   TCP:443 OK 0.0s

    发 HTTP 有两个坑：①裸 GET 打基地址，服务器可能**不回话**（不是拒绝，是挂着），
    于是把「可达但没这条路」误判成「不可达」；②要把 base URL 拼成某个具体路径，
    而"哪个路径算活着"本身就是猜。TCP 连一下没有这两问题，且快。
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception as e:                                     # noqa: BLE001
        return "unreachable", "DNS 解析不了 `%s`（%s）" % (host, type(e).__name__)
    last = ""
    # 总预算而不是每个地址各给一份：一个双栈主机 ×2 个地址族会翻倍，
    # 而这一档只在阳性对照已经失败之后才跑，**不该再拖长失败路径**。
    deadline = time.time() + _REACH_TIMEOUT
    for fam, typ, proto, _canon, addr in infos:
        left = deadline - time.time()
        if left <= 0:
            break
        s = socket.socket(fam, typ, proto)
        s.settimeout(left)
        try:
            s.connect(addr)
            return "reachable", "`%s:%d` 连得上" % (host, port)
        except Exception as e:                                 # noqa: BLE001
            last = "%s（%s:%d）" % (type(e).__name__, host, port)
        finally:
            s.close()
    return "unreachable", last or "连不上 `%s:%d`" % (host, port)


def _proxy_in(env: Dict[str, str]) -> str:
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
              "ALL_PROXY", "all_proxy"):
        if env.get(k):
            return env[k]
    return ""


def reachability(env: Dict[str, str], url: str) -> Tuple[str, str]:
    """从**子进程同款 env**出发，够不够得到它要打的东西。返回 (档位, 说明)。

    ⚠️ **探的是子进程真正的下一跳**：
      - 通道**声明了代理** → 探**代理**（那才是它的出口；代理没起，子进程一样出不去）；
      - 没声明代理 → 探**端点主机**。

    ⚠️ **能抓什么、抓不到什么**（写清楚，免得这一档被读成比它实际更强）：
      - 抓得到：代理没起 / 代理地址写错 / 主机被丢包（如 api.openai.com 直连超时）/
        DNS 解析失败。**这是最常见的一类。**
      - **抓不到**：主机连得上、但**应用层**按地区/套餐拒你（2026-10-08 那次就是：
        opencode.ai 的 TCP 通着，是 `/responses` 上按模型区域策略回了 403）。
        那一类只能靠 L1 把子进程的理由带出来 —— 探针在这里会诚实地报 reachable。
    """
    if not url:
        return ("unknown",
                "配置里没声明 `endpoint:`，env 里也没有 base URL —— 无从探测")
    proxy = _proxy_in(env)
    if proxy:
        try:
            pu = urllib.parse.urlsplit(proxy if "://" in proxy else "http://" + proxy)
        except Exception:                                      # noqa: BLE001
            return "unreachable", "代理地址解析不了：%s" % proxy
        phost, pport = pu.hostname or "", pu.port or (1080 if pu.scheme.startswith("socks") else 8080)
        v, why = _dial(phost, pport)
        # 代理通了就到此为止：再往后的路是代理的事，探针看不到，也不该假装看到。
        return v, ("通道声明了代理：%s\n        %s" % (proxy, why))
    host = urllib.parse.urlsplit(url).hostname or ""
    port = urllib.parse.urlsplit(url).port or (443 if url.startswith("https") else 80)
    return _dial(host, port)


# ------------------------------------------------ 模型身份探针（第二条轴）
#
# 凭据探针证的是「请求经过了声明的端点」。**它证不了端点回话的是谁。** 这一条补另外半边：
# 直接向声明的端点发一次极小请求，读**应答里带的模型名**，和配置里声明的比对。
#
# 为什么值得单独做（2026-10-02 实测）：第三方端点普遍有一层**别名映射**——
# 声明 `glm-5.3-pro` / `kimi-k2-thinking` / `minimax-m2.7`，
# 回来的分别是 `glm-5.3` / `kimi-k2.7-code` / `minimax-m3`。
# 也就是说**你以为买的档位和你实际拿到的可能不是一回事**，而这件事在结论里完全看不出来。
#
# ⚠️ 边界（别读大）：它证的是「这个端点对**这个模型名**的应答里写着**这个模型名**」。
# 端点仍然可以在应答里说谎，也仍然可以在别的请求上换模型。它把缺口缩小了，没有关掉。
# 而且它只对**配置里写得出端点**的通道有效——端点藏在 CLI 自己注册表里的
# （典型：opencode 的内置 provider）只能报 `unverifiable`，报告会明说没验过。
_DATE_SUFFIX = re.compile(r"[-_]\d{6}$")


def _norm_model(m: str) -> str:
    """归一化，否则全是假警报。

    实测的三种写法差异：`glm-5.3-flash` 回来是 `glm-5-3-flash`（点转横线）、
    `doubao-seed-2-1-pro-260915` 回来是 `doubao-seed-2-1-pro`（日期后缀被剥）、
    `deepseek-v4-pro-260425` 回来是 `deepseek-v4-pro`。
    这三种都**不是**换模型，只是命名——不归一化就会把它们全报成 mismatch。
    """
    return _DATE_SUFFIX.sub("", m.strip().lower()).replace(".", "-").replace("_", "-")


def probe_model(cfg: Config, name: str, timeout_s: int = 60) -> Tuple[str, str, str, str]:
    """返回 (status, declared, served, detail)。**不抛异常**，一切失败都落成档位。"""
    r = cfg.reviewer(name)
    ch = cfg.channels[r.channel]
    if ch.kind == "fake":
        return "skipped", "", "", ""
    try:
        _argv, env, _w = channels.build(ch, r, cfg, PROBE)
    except SystemExit as e:
        return "unverifiable", ch.model, "", "通道构造失败：%s" % (e.code,)

    base = channel_endpoint(ch, env)
    creds = credential_keys(env)
    if not (base and creds and ch.model):
        return ("unverifiable", ch.model, "",
                "端点不在配置里（藏在 CLI 自己的注册表里），或没有凭据——"
                "这条通道**这次没有验过模型身份**，别把它读成通过。"
                "修法：给这条通道加 `endpoint:`（opencode-cli 就属于这种）")
    body = json.dumps({"model": ch.model, "max_tokens": 1,
                       "messages": [{"role": "user", "content": "hi"}]}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/v1/messages", data=body, method="POST",
                                 headers={"content-type": "application/json",
                                          "anthropic-version": "2023-06-01",
                                          "x-api-key": env[creds[0]],
                                          "authorization": "Bearer " + env[creds[0]],
                                          "user-agent": "quorum-preflight/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            got = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return "unverifiable", ch.model, "", "端点回 HTTP %s，读不到模型名" % e.code
    except Exception as e:                                     # noqa: BLE001
        return "unverifiable", ch.model, "", "请求失败：%s" % type(e).__name__

    served = str(got.get("model") or "")
    if not served:
        return "unverifiable", ch.model, "", "应答里没有 model 字段"
    if _norm_model(served) == _norm_model(ch.model):
        return "match", ch.model, served, ""
    return ("mismatch", ch.model, served,
            "声明的是 `%s`，端点回的是 `%s`——**这是别名映射，不是命名差异**"
            "（命名差异已经被归一化掉了）。" % (ch.model, served))


def probe_reviewer(cfg: Config, name: str, timeout_s: int = 120) -> Verdict:
    """两条轴都跑：**凭据对照**（请求经不经过声明的端点）+ **模型身份**（那边回的是谁）。

    两条轴抓的是两个不同的洞。第一条抓「通道改道」，第二条抓「端点换模型」。
    实测两者都真实存在：claude-cli 的 `ANTHROPIC_*` 会被用户级 settings 盖过；
    第三方端点的别名映射会把 `glm-5.3-pro` 悄悄降成 `glm-5.3`。
    """
    v = _credential_controls(cfg, name, timeout_s)
    v.model_status, v.declared_model, v.served_model, v.model_detail = probe_model(cfg, name)
    return v


def _credential_controls(cfg: Config, name: str, timeout_s: int = 120) -> Verdict:
    """对一条通道做一次阴性对照。**只读**：不写任何配置/结论路径，只用临时文件。"""
    r = cfg.reviewer(name)
    ch = cfg.channels[r.channel]

    if ch.kind == "fake":
        return Verdict(name, r.channel, ch.kind, "unsupported", "桩通道，没有端点可验")

    try:
        argv, env, writes_file = channels.build(ch, r, cfg, PROBE)
    except SystemExit as e:
        return Verdict(name, r.channel, ch.kind, "error", "通道构造失败：%s" % (e.code,))

    creds = credential_keys(env)
    endpoint = env.get("ANTHROPIC_BASE_URL") or env.get("OPENAI_BASE_URL") or ""
    if not creds:
        return Verdict(
            name, r.channel, ch.kind, "no_credential",
            "通道 env 里没有凭据类变量——这次请求用的是**本机登录态**，"
            "而不是配置里声明的那个端点。这条预检对它无能为力，请自己确认这是你要的。",
            [], endpoint)

    poisoned_env = dict(env)
    for k in creds:
        poisoned_env[k] = POISON

    # ---- 阳性对照：同样的 argv、同样的端点，**只把凭据换回真的** --------------
    #
    # 第一版只有阴性对照，实测不够用：坏凭据下去，claude-cli **不是报错，是挂住**
    # （2026-10-02 实测：真 key 6.7s / rc=0 / 输出 `OK`；坏 key 90s 没动静）。
    # 于是「没成功」这一个信号同时对应两种完全不同的现实——「凭据被拒」和
    # 「这条通道根本是死的」。光看阴性分不开，而分不开就会把死通道报成「已核实」。
    pos_rc, pos_body, pos_err, pos_secs = _invoke(cfg, argv, env, writes_file, timeout_s,
                                                  name + "-pos")
    if pos_rc != 0 or not pos_body:
        # 把子进程自己说的话带出来（凭据先抹掉）。阳性对照失败时，「为什么失败」几乎
        # 只写在 stderr 上——不带出来，这一档就只能报「产出 0 字」，于是
        # **网络出口不通与 CLI 没装长得一模一样**（2026-10-08 的实际代价：手工重跑才定位）。
        raw = _scrub(pos_err or pos_body, env).strip()
        ev = ("\n        子进程说的（末 400 字，凭据已抹）：%s" % raw[-400:]) if raw else ""
        # ---- 网络出口探针：够不到就单独成一档，不再和「凭据错/CLI 没装」混一起 ----
        ep = channel_endpoint(ch, env)
        reach, why = reachability(env, ep)
        head = ("**阳性对照就没过**：真凭据下 %ds 后 rc=%s、产出 %d 字。"
                % (pos_secs, pos_rc, len(pos_body)))
        if reach == "unreachable":
            detail = (head
                      + "\n        **网络出口不通**：这条通道从它自己的 env 出发"
                        "**够不到** `%s`。\n        探针：%s\n"
                        "        这不是凭据问题、也不是端点写错——是**包出不去**。\n"
                        "        最常见的原因：端点要走代理，而代理只配在 **macOS 系统设置**里；\n"
                        "        **Unix CLI 不读系统代理**，只认 `HTTP_PROXY` / `HTTPS_PROXY`\n"
                        "        环境变量。把它们写进**这条通道的 env**——不要只靠 shell export，\n"
                        "        那样事后追不到「这一轮走的是哪个出口」。\n"
                        "        另注：`small_model` 这类**副调用**用的是另一个模型，"
                        "可能单独被墙。" % (ep, why)) + ev
            return Verdict(name, r.channel, ch.kind, "egress_blocked", detail,
                           creds, ep, pos_secs)
        detail = (head
                  + "这条通道自己起不来（凭据错/端点错/CLI 没装），"
                    "所以**「端点属不属实」这件事这次没有验过**——别把这一行读成通过。"
                    "\n        网络出口：%s" % why) + ev
        return Verdict(name, r.channel, ch.kind, "channel_down", detail,
                       creds, ep, pos_secs)

    # ---- 阴性对照：只把凭据换成故意错的 -------------------------------------
    #
    # 上限由**实测基线**推出来，不是一个拍脑袋的常数：被劫持的通道会像阳性一样几秒就回话，
    # 所以只要比基线宽出几倍还没动静，就足以判「它不是成功，是被拒了」。
    neg_cap = int(min(timeout_s, max(25, 3 * pos_secs + 15)))
    neg_rc, neg_body, neg_err, neg_secs = _invoke(cfg, argv, poisoned_env, writes_file, neg_cap,
                                                  name + "-neg")

    if neg_rc == 0 and neg_body:
        return Verdict(name, r.channel, ch.kind, "hijacked",
                       "凭据是**故意错的**，进程却 %ds 退出 0 且有产出——**这份凭据根本没被用上**，"
                       "请求被路由到了别处。产出前 80 字：%r。"
                       "修法（claude-cli 最常见）：CLI 读了自己的用户级 settings，"
                       "进程环境变量被盖过——加 `--setting-sources project`。"
                       % (neg_secs, _scrub(neg_body[:80], env)),
                       creds, endpoint, pos_secs)
    if neg_rc == -9:
        # ⚠️ **「没返回」和「被拒」是两件事，不能混成一句话。**
        # （2026-10-02，kimi 与 luna 各自独立点到这条：旧版把这一档也写成
        #  「端点确实校验了这一路凭据」——而看门狗杀掉的进程，我们只知道它**没有成功**，
        #  不知道它是因为凭据被拒、还是因为请求挂住了。把后者写成前者，
        #  就是**把不确定状态绿化**，正是这个工具最反对的那件事。）
        return Verdict(name, r.channel, ch.kind, "not_refuted",
                       "真凭据 %ds 正常返回；换成错凭据后 %ds **没有返回**（被看门狗杀掉）。"
                       "所以这次**排除掉了「凭据没生效」**——但「因为凭据被拒」和"
                       "「因为请求挂住」**分不开**，端点是否校验凭据这件事**没有被证明**。"
                       % (pos_secs, neg_secs),
                       creds, endpoint, pos_secs)
    return Verdict(name, r.channel, ch.kind, "verified",
                   "真凭据 %ds 正常返回；换成错凭据后 %ds 干净地被拒（rc=%s）"
                   "——端点确实校验了这一路凭据。"
                   % (pos_secs, neg_secs, neg_rc),
                   creds, endpoint, pos_secs)


def _invoke(cfg: Config, argv: List[str], env: Dict[str, str], writes_file: bool,
            cap: int, tag: str):
    """跑一次探针，返回 (rc, 产出文本, stderr 文本, 用时秒)。只用临时文件，不碰任何结论路径。

    ⚠️ **stderr 必须带出来**（2026-10-08 补）。看门狗一直把 stderr 写进文件，
    但这里从来没读过它 —— 于是阳性对照失败时，`channel_down` 只能报「产出 0 字」，
    而「为什么失败」几乎只写在 stderr 上。实例：opencode 把
    `Country, region, or territory not supported` 打在 stderr，被丢掉之后，
    「网络出口不通」和「CLI 没装」在报告里长得一模一样，害得人手工重跑才找到根因。
    """
    fd, out = tempfile.mkstemp(prefix="quorum-preflight-%s-" % tag)
    os.close(fd)
    err, stream = out + ".err", out + ".stream"
    try:
        if writes_file:
            argv = [out if x == "__OUT__" else x for x in argv]
            stdout_path = stream
        else:
            stdout_path = out
        t0 = time.time()
        rc = gates.run_with_timeout(argv, env, cap, stdout_path, err, cwd=cfg.repo)
        secs = int(round(time.time() - t0))
        body = (gates.read_text(out) + gates.read_text(stdout_path)).strip()
        stderr = gates.read_text(err).strip()
        return rc, body, stderr, secs
    finally:
        for f in (out, err, stream):
            try:
                if os.path.exists(f):
                    os.unlink(f)
            except OSError:
                pass


def preflight(cfg: Config, names: List[str], timeout_s: int = 120,
              jobs: int = 0) -> List[Verdict]:
    jobs = len(names) if jobs <= 0 else min(jobs, len(names))
    if jobs <= 1:
        return [probe_reviewer(cfg, n, timeout_s) for n in names]
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(lambda n: probe_reviewer(cfg, n, timeout_s), names))


_ICON = {"verified": OK, "hijacked": FAIL, "channel_down": FAIL,
         "egress_blocked": FAIL,
         "not_refuted": WARN, "no_credential": WARN, "unsupported": "·", "error": FAIL}
_M_ICON = {"match": OK, "mismatch": FAIL, "unverifiable": WARN, "skipped": "·"}


def render(verdicts: List[Verdict]) -> str:
    lines = ["阴性对照预检（每条通道两次极小的请求）：",
             "  阳性对照 —— **真凭据**必须回话（否则这条通道是死的，预检对它无从判断）",
             "  阴性对照 —— 同样的 argv、同样的端点，**只把凭据换成故意错的**：",
             "               回话 = 凭据根本没被用上，请求被劫走了；不回话 = 端点属实。",
             "",
             "网络出口探针（**只在阳性对照失败时跑**，不占正常路径的开销）：",
             "  从**子进程同款 env** 出发够不够得到端点 —— 把「包出不去」",
             "  与「凭据错 / 端点错 / CLI 没装」分开。探针按值只看路，不看协议。",
             "",
             "模型身份探针（另发一次极小请求，读应答里带的模型名）：",
             "  抓的是**别名映射**——声明 `X-pro` 而端点回 `X` 这类降级。",
             "  证不了端点是否在应答里说谎，也证不了它在别的请求上换了模型。",
             "  端点取自通道的 `endpoint:`，否则取 env 里的 base URL ——",
             "  两者都没有就没法验（如未声明端点的 opencode-cli 通道）。",
             ""]
    for v in verdicts:
        enc = ("  毒化：%s" % ", ".join(v.poisoned)) if v.poisoned else ""
        ep = ("  端点：%s" % v.endpoint) if v.endpoint else ""
        pos = ("  阳性基线：%ds" % v.pos_secs) if v.pos_secs else ""
        lines.append("  %s %-12s [%s] %s" % (_ICON.get(v.status, "?"), v.reviewer,
                                             v.kind, v.status))
        if ep or pos:
            lines.append("      %s%s" % (ep.strip(), pos))
        if enc:
            lines.append("      %s" % enc.strip())
        if v.detail:
            lines.append("      %s" % v.detail)
        if v.model_status != "skipped":
            lines.append("      %s 模型身份：%s  声明 `%s`%s"
                         % (_M_ICON.get(v.model_status, "?"), v.model_status,
                            v.declared_model,
                            "  → 实回 `%s`" % v.served_model if v.served_model else ""))
            if v.model_detail:
                lines.append("         %s" % v.model_detail)
    n_bad = sum(1 for v in verdicts if v.blocks)
    n_mis = sum(1 for v in verdicts if v.model_status == "mismatch")
    lines.append("")
    if n_bad:
        lines.append("  %s %d 条通道的凭据**没有生效**——配置里声明的端点不是实际在用的那个。\n"
                     "     跑出来的结论会带上**错误的来源标签**。\n"
                     "     常见根因：CLI 读了自己的**用户级**配置，进程环境变量被盖过\n"
                     "     （claude-cli：用户级 settings；opencode：$XDG_DATA_HOME 下的 auth.json）。"
                     % (FAIL, n_bad))
    else:
        weak = [v.reviewer for v in verdicts
                if v.status in ("no_credential", "channel_down")]
        lines.append("  %s 没有通道被劫持" % OK
                     + ("；但 %s 那几条**这次没验过**（见上）。" % "、".join(weak) if weak else "。"))
    egr = [v.reviewer for v in verdicts if v.status == "egress_blocked"]
    if egr:
        lines.append("  %s %s 的**网络出口不通** —— 包出不去，既不是凭据也不是端点。\n"
                     "     多半是端点要走代理，而代理只配在 **macOS 系统设置**里；\n"
                     "     Unix CLI 不读系统代理，只认 `HTTP_PROXY` / `HTTPS_PROXY`。\n"
                     "     这几条**跑起来会白烧一整轮额度**，先修再 run。" % (FAIL, "、".join(egr)))
    nr = [v.reviewer for v in verdicts if v.status == "not_refuted"]
    if nr:
        lines.append("  %s %s：阴性对照**是被看门狗杀掉的**，不是干净地失败。"
                     "所以「凭据没生效」被排除了，但**端点是否校验凭据没有被证明**——"
                     "别把这行读成 ✅。" % (WARN, "、".join(nr)))
    if n_mis:
        lines.append("  %s %d 条通道**声明与实际拿到的不是同一个档位**（见上）。"
                     "不拦人——但结论里写「我们用 X 审的」之前，先看这一行。" % (FAIL, n_mis))
    unv = [v.reviewer for v in verdicts if v.model_status == "unverifiable"]
    if unv:
        # 不再断言原因（"端点不在配置里"）—— 现在端点是**可以声明**的，
        # 声明了照样可能验不了（模型不走 `/v1/messages`，探针读不到模型名）。
        # 具体原因在每条的 model_detail 里，这里只说结论。
        lines.append("  %s %s 的模型身份**这次没验过**（原因见上）——别读成通过。"
                     "这一轴对**不走 Anthropic 协议**的端点结构性地验不了，"
                     "替代的事实侧核对是 CLI 自己的日志。"
                     % (WARN, "、".join(unv)))
    return "\n".join(lines)


def exit_code(verdicts: List[Verdict]) -> int:
    return 1 if any(v.blocks for v in verdicts) else 0


# ------------------------------------------------------------------ self-test
def _synthetic(tmp: str, argv: List[str], env: Dict[str, str], model: str = "") -> Config:
    ch = Channel(name="probe", kind="exec", argv=argv, env=env, model=model)
    rv = Reviewer(name="probe", channel="probe", vendor="synthetic")
    return Config(project="preflight-selftest", brief="", out_dir=tmp, repo=tmp,
                  reviewers=[rv], channels={"probe": ch}, gates=Gates(), path="")


def _serve(model_name: str, sink: List[int]):
    """本地假端点：只回一个 `{"model": <model_name>}`。用来给身份探针造对照。"""
    import http.server
    import threading

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("content-length") or 0))
            body = json.dumps({"model": model_name}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    sink.append(srv.server_address[1])
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# 桩：**行为取决于凭据** —— 拿到毒化的那个就拒绝，否则回话。
# 这才能同时喂出阳性与阴性两条对照；一个恒定行为的脚本只能落在其中一档。
_STUB_GOOD_BAD = ["/bin/sh", "-c",
                  'if [ "$FAKE_KEY" = "%s" ]; then echo auth failed >&2; exit 1; fi; '
                  'echo QUORUM_PREFLIGHT_PROBE' % POISON]
_STUB_ALWAYS_OK = ["/bin/sh", "-c", "echo QUORUM_PREFLIGHT_PROBE"]
_STUB_ALWAYS_FAIL = ["/bin/sh", "-c", "echo nope >&2; exit 1"]


def self_test() -> int:
    """证明这两条探针**都能红**。一条不能红的检查等于没有检查——本项目的老规矩。"""
    tmp = tempfile.mkdtemp(prefix="quorum-preflight-selftest-")
    bad = 0

    # ---- 轴一：凭据对照 ----------------------------------------------------
    cred_cases = [
        ("被劫持（错凭据照样回话）", _STUB_ALWAYS_OK,
         {"FAKE_KEY": "real"}, "hijacked"),
        ("正常（错凭据被拒、真凭据通过）", _STUB_GOOD_BAD,
         {"FAKE_KEY": "real"}, "verified"),
        ("通道是死的（真凭据也不回话）", _STUB_ALWAYS_FAIL,
         {"FAKE_KEY": "real"}, "channel_down"),
        ("env 里没有凭据可毒", _STUB_ALWAYS_OK,
         {"ANTHROPIC_BASE_URL": "http://x"}, "no_credential"),
    ]
    print("轴一 · 凭据对照：这些用例必须**各自落到它该落的那一档**\n")
    for label, argv, env, want in cred_cases:
        v = probe_reviewer(_synthetic(tmp, argv, env), "probe", timeout_s=30)
        hit = v.status == want
        print("  %s %-32s → %-14s（期望 %s）" % (OK if hit else FAIL, label, v.status, want))
        if not hit:
            bad += 1
            print("      %s" % v.detail)

    # ---- 轴二：模型身份 ----------------------------------------------------
    #
    # 前两条是**真实观测到的命名差异**，必须判 match —— 否则探针会对着每一路
    # 正常通道报假警报，而假警报会把真警报淹掉（LESSONS 有专条）。第三条是真实
    # 观测到的**别名降级**：声明 `glm-5.3-pro`，端点回 `glm-5.3`。
    model_cases = [
        ("命名差异：点→横线，不是换模型", "glm-5.3-flash", "glm-5-3-flash", "match"),
        ("命名差异：日期后缀被剥，不是换模型", "doubao-seed-2-1-pro-260915",
         "doubao-seed-2-1-pro", "match"),
        ("真·别名降级：声明 pro，实回非 pro", "glm-5.3-pro", "glm-5.3", "mismatch"),
    ]
    print("\n轴二 · 模型身份：前两条必须判 match，否则就是假警报\n")
    for label, declared, served, want in model_cases:
        sink: List[int] = []
        _serve(served, sink)
        env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:%d" % sink[0], "FAKE_KEY": "real"}
        v = probe_reviewer(_synthetic(tmp, _STUB_GOOD_BAD, env, model=declared),
                           "probe", timeout_s=30)
        hit = v.model_status == want
        print("  %s %-34s → %-9s（期望 %s）" % (OK if hit else FAIL, label,
                                                v.model_status, want))
        if not hit:
            bad += 1
            print("      声明 %s / 实回 %s — %s" % (v.declared_model, v.served_model,
                                                    v.model_detail))

    print()
    if bad:
        print("  %s %d 条用例没落到该落的档位——预检自己对不了账。" % (FAIL, bad))
        return 1
    print("  %s 两条轴都能落到位。\n"
          "     轴一重点是**被劫持**与**正常**必须分得开——第一版只有阴性对照，\n"
          "     而真实 CLI 对坏凭据是**挂住**不是报错，两者会混成同一档，\n"
          "     死通道就会被报成「已核实」。\n"
          "     轴二重点是**命名差异不许报成 mismatch**——三条用例里两条是防假警报的。"
          % OK)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--self-test"]:
        return self_test()
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
