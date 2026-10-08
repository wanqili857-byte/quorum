"""配置契约：一个 review.yaml 描述「审什么、谁来审、门禁多严、产出到哪」。

设计原则：**引擎里不出现任何项目的具体信息**。项目名、路径、审核员端点、密钥位置
全部来自配置；新增一个 Anthropic 兼容的模型厂商 = 加一段配置，不改代码。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import yaml
except ImportError:                                    # pragma: no cover
    yaml = None


class ConfigError(SystemExit):
    pass


def _require_yaml():
    if yaml is None:
        raise ConfigError("需要 PyYAML：pip install pyyaml（或 `pip install -e .` 装上依赖）")


def _expand(p: Optional[str]) -> Optional[str]:
    return os.path.expanduser(p) if p else p


@dataclass
class Reviewer:
    """一个审核员 = 一个「干净进程」+ **两个互相独立的来源轴**。

    这两条轴不是一回事，别把它们混成一个。真实教训：三家审核员里，两家是**同一个
    harness 配不同厂的模型**、一家是**另一个 harness**。并排写成「三个不同通道」，
    读者会以为买到了两维独立，实际只有一维。

    - ``vendor``  —— **模型来源**（谁训的权重）。这是**声明**，工具验证不了真假。
      COI 规则建在它上面：同一 vendor 不得有两个 primary（同源模型看不出同源盲区）。
    - ``harness`` —— **agent 框架**（哪个 CLI 在跑它）。这是**事实**，从通道推出，
      不由审核员声明。

    同一个 vendor 换 harness，模型盲区还是共享的；同一个 harness 换 vendor，
    共识又可能来自 harness 本身（同一套 system prompt、同一套工具、同一种下结论的套路）。
    两轴都报出来，读者才知道这次的一致性值多少——见 ``plate.Cluster.label``。
    """
    name: str
    channel: str
    vendor: str = "unknown"
    harness: str = ""              # 由通道推出（见 load），不从配置里读
    role: str = "primary"          # primary | cross
    label: str = ""
    timeout_s: int = 2700
    extra_env: Dict[str, str] = field(default_factory=dict)


@dataclass
class Channel:
    """怎么起一个进程。`kind` 决定命令构造方式。

    ``kind`` 描述的是**机制**，不是厂商——quorum 不自带任何模型：
    ``claude-cli`` / ``codex-cli`` 是两种内置起法，``exec`` 是通用的（自己写 argv，
    接任何 CLI），``fake`` 是测试桩。底下跑谁的模型，由 ``env`` / ``argv`` / ``model``
    决定，工具不解释也不验证。
    """
    name: str
    kind: str                      # claude-cli | codex-cli | opencode-cli | exec | fake
    model: str = ""
    harness: str = ""              # 覆盖 harness 名；留空则取 kind
    env: Dict[str, str] = field(default_factory=dict)
    # 形如 ANTHROPIC_AUTH_TOKEN_FILE 的键表示「值要从这个文件读」，密钥内容永不进配置
    argv: List[str] = field(default_factory=list)
    # 内置起法（claude-cli / codex-cli）的**额外命令行标志**。
    # 为什么需要：这类需求（放行只读命令的权限白名单、sandbox 标志、--max-turns）
    # 此前只能绕到 exec 通道，而 exec 要求手写完整 argv 与 harness 名——使用者
    # 很容易忘了写 harness，把两个不同的 CLI 记成同一个（plate 的独立性注记就废了）。
    # exec 通道请把标志写进 argv，不要用这个字段（配了会直接报错，见 channels.py）。
    args: List[str] = field(default_factory=list)

    @property
    def harness_name(self) -> str:
        return self.harness or self.kind


@dataclass
class Gates:
    min_bytes: int = 2000
    min_findings: int = 5
    require_sections: List[str] = field(default_factory=lambda: ["最脆弱"])


@dataclass
class Config:
    project: str
    brief: str
    out_dir: str
    repo: str
    reviewers: List[Reviewer]
    channels: Dict[str, Channel]
    gates: Gates
    sources: List[str] = field(default_factory=list)
    ledger: str = ""
    # 台账说谎记录（verify 判出 🔴 时自动落盘的**事实**档案）。
    # 留空 = 不写 —— 默认关闭，不改动任何既有行为。语义与 ledger 一致：
    # 相对路径按**配置文件所在目录**解析。
    incidents: str = ""
    snapshot_exclude: List[str] = field(default_factory=list)
    leak_patterns: Dict[str, str] = field(default_factory=dict)
    path: str = ""

    # ---- 便捷视图 -------------------------------------------------------
    @property
    def _base(self) -> str:
        """配置里声明的相对路径的相对基准 = **配置文件所在目录**（契约如此，实现也必须如此）。"""
        return os.path.dirname(self.path) if self.path else self.repo

    def _resolve(self, p: str) -> str:
        return p if os.path.isabs(p) else os.path.normpath(os.path.join(self._base, p))

    @property
    def brief_abs(self) -> str:
        return self._resolve(self.brief)

    @property
    def out_dir_abs(self) -> str:
        return self._resolve(self.out_dir)

    @property
    def incidents_abs(self) -> str:
        """台账说谎记录的位置。**空字符串 = 不写**（默认），不是「写到默认路径」。"""
        return self._resolve(self.incidents) if self.incidents else ""

    def brief_for_prompt(self) -> str:
        """给审核员看的工单路径：在 repo 内就给相对路径（它的 cwd 是 repo），否则给绝对路径。

        不传对路径的后果很隐蔽：审核员会**自己去找**，找得到就照常产出——看起来一切正常，
        但那是运气不是设计。"""
        try:
            rel = os.path.relpath(self.brief_abs, self.repo)
        except ValueError:
            return self.brief_abs
        return self.brief_abs if rel.startswith("..") else rel

    def out_path(self, reviewer: str) -> str:
        return os.path.join(self.out_dir_abs, "%s-findings-%s.md" % (self.project, reviewer))

    def raw_path(self, reviewer: str, stamp: str) -> str:
        d = os.path.join(self.out_dir_abs, ".raw")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "%s-%s-%s.log" % (self.project, reviewer, stamp))

    def log_path(self) -> str:
        return os.path.join(self.out_dir_abs, "%s-review.log" % self.project)

    def reviewer(self, name: str) -> Reviewer:
        for r in self.reviewers:
            if r.name == name:
                return r
        raise ConfigError("配置里没有审核员 %r（可选：%s）"
                          % (name, ", ".join(r.name for r in self.reviewers)))


def load(path: str) -> Config:
    _require_yaml()
    path = os.path.abspath(_expand(path))
    try:
        raw = yaml.safe_load(open(path, encoding="utf-8"))
    except OSError as e:
        raise ConfigError("读不到配置：%s" % e)
    if not isinstance(raw, dict):
        raise ConfigError("配置必须是 YAML 映射：%s" % path)

    # 相对路径一律**相对配置文件所在目录**解析——这样 `quorum run --config x/y.yaml`
    # 在任何 CWD 下都得到同一结果（CWD 相关的配置是下一类「同参数不同结果」的温床）。
    base = os.path.dirname(path)
    repo = _expand(raw.get("repo", ".")) or "."
    if not os.path.isabs(repo):
        repo = os.path.normpath(os.path.join(base, repo))
    for key in ("project", "brief", "out_dir"):
        if not raw.get(key):
            raise ConfigError("配置缺 %r" % key)

    channels = {}
    for name, spec in (raw.get("channels") or {}).items():
        channels[name] = Channel(
            name=name,
            kind=spec.get("kind", "claude-cli"),
            model=spec.get("model", ""),
            harness=spec.get("harness", ""),
            env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
            argv=list(spec.get("argv") or []),
            args=[str(a) for a in (spec.get("args") or [])],
        )

    reviewers = []
    for spec in (raw.get("reviewers") or []):
        ch = spec.get("channel", spec["name"])
        if ch not in channels:
            raise ConfigError("审核员 %s 引用了未定义的通道 %s" % (spec.get("name"), ch))
        # `family` 是 vendor 的旧名，保留为别名；新配置一律写 vendor。
        vendor = spec.get("vendor") or spec.get("family")
        if not vendor:
            raise ConfigError(
                "审核员 %s 没有声明 vendor（模型来源）。vendor 是 COI 规则的**唯一依据**，"
                "缺省值会让「同源不得有两个 primary」这条硬约束形同虚设"
                "（三条 primary 全不写 vendor 就能全部通过）。" % spec["name"])
        role = spec.get("role", "primary")
        if role not in ("primary", "cross"):
            raise ConfigError("审核员 %s 的 role=%r 非法（只能是 primary 或 cross）——"
                              "写错大小写会让它静默生效为 cross 或 primary" % (spec["name"], role))
        reviewers.append(Reviewer(
            name=spec["name"], channel=ch,
            vendor=vendor,
            harness=channels[ch].harness_name,     # 事实：从通道推出，不由审核员声明
            role=role,
            label=spec.get("label", ""),
            timeout_s=int(spec.get("timeout_s", 2700)),
            extra_env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
        ))
    if not reviewers:
        raise ConfigError("配置里没有审核员")

    g = raw.get("gates") or {}
    gates = Gates(
        min_bytes=int(g.get("min_bytes", 2000)),
        # 旧键 min_severity_marks 仍接受，但语义已改为「发现条数」——名字必须跟着语义走
        min_findings=int(g.get("min_findings", g.get("min_severity_marks", 5))),
        require_sections=list(g.get("require_sections") or ["最脆弱"]),
    )

    cfg = Config(
        project=raw["project"], brief=raw["brief"], out_dir=raw["out_dir"], repo=repo,
        reviewers=reviewers, channels=channels, gates=gates,
        sources=list(raw.get("sources") or []),
        ledger=raw.get("ledger", ""),
        incidents=raw.get("incidents", ""),
        snapshot_exclude=list(raw.get("snapshot_exclude") or []),
        leak_patterns=dict(raw.get("leak_patterns") or {}),
        path=path,
    )

    # COI 自检：同 vendor 不得同时充当 primary（同源模型看不出同源盲区）
    by_vendor = {}
    for r in cfg.reviewers:
        if r.role == "primary":
            by_vendor.setdefault(r.vendor, []).append(r.name)
    clashes = {v: n for v, n in by_vendor.items() if len(n) > 1}
    if clashes:
        raise ConfigError("COI：同一 vendor（模型来源）不能同时当首选——%s。"
                          "把其中一个标成 role: cross" % clashes)
    return cfg
