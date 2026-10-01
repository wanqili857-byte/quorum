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
    """一个审核员 = 一个「干净进程」+ 一个模型族标记。

    `family` 是 COI 规则的基础：同一 family 的模型不能同时充当首选审核员，
    只能作交叉（同源模型看不出同源的盲区）。
    """
    name: str
    channel: str
    family: str = "unknown"
    role: str = "primary"          # primary | cross
    label: str = ""
    timeout_s: int = 2700
    extra_env: Dict[str, str] = field(default_factory=dict)


@dataclass
class Channel:
    """怎么起一个进程。`kind` 决定命令构造方式。"""
    name: str
    kind: str                      # claude-cli | codex-cli | fake
    model: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    # 形如 ANTHROPIC_AUTH_TOKEN_FILE 的键表示「值要从这个文件读」，密钥内容永不进配置
    argv: List[str] = field(default_factory=list)


@dataclass
class Gates:
    min_bytes: int = 2000
    min_severity_marks: int = 5
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
    snapshot_exclude: List[str] = field(default_factory=list)
    leak_patterns: Dict[str, str] = field(default_factory=dict)
    path: str = ""

    # ---- 便捷视图 -------------------------------------------------------
    @property
    def brief_abs(self) -> str:
        return os.path.join(self.repo, self.brief) if not os.path.isabs(self.brief) else self.brief

    @property
    def out_dir_abs(self) -> str:
        return os.path.join(self.repo, self.out_dir) if not os.path.isabs(self.out_dir) else self.out_dir

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
            env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
            argv=list(spec.get("argv") or []),
        )

    reviewers = []
    for spec in (raw.get("reviewers") or []):
        ch = spec.get("channel", spec["name"])
        if ch not in channels:
            raise ConfigError("审核员 %s 引用了未定义的通道 %s" % (spec.get("name"), ch))
        reviewers.append(Reviewer(
            name=spec["name"], channel=ch,
            family=spec.get("family", "unknown"),
            role=spec.get("role", "primary"),
            label=spec.get("label", ""),
            timeout_s=int(spec.get("timeout_s", 2700)),
            extra_env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
        ))
    if not reviewers:
        raise ConfigError("配置里没有审核员")

    g = raw.get("gates") or {}
    gates = Gates(
        min_bytes=int(g.get("min_bytes", 2000)),
        min_severity_marks=int(g.get("min_severity_marks", 5)),
        require_sections=list(g.get("require_sections") or ["最脆弱"]),
    )

    cfg = Config(
        project=raw["project"], brief=raw["brief"], out_dir=raw["out_dir"], repo=repo,
        reviewers=reviewers, channels=channels, gates=gates,
        sources=list(raw.get("sources") or []),
        ledger=raw.get("ledger", ""),
        snapshot_exclude=list(raw.get("snapshot_exclude") or []),
        leak_patterns=dict(raw.get("leak_patterns") or {}),
        path=path,
    )

    # COI 自检：同 family 不得同时充当 primary（同源模型看不出同源盲区）
    fams = {}
    for r in cfg.reviewers:
        if r.role == "primary":
            fams.setdefault(r.family, []).append(r.name)
    clashes = {f: n for f, n in fams.items() if len(n) > 1 and f != "unknown"}
    if clashes:
        raise ConfigError("COI：同一 family 的模型不能同时当首选——%s。"
                          "把其中一个标成 role: cross" % clashes)
    return cfg
