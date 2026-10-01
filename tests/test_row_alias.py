"""列名别名与「位置列没认出来」的出声（独立文件，便于单独提交）。

实测背景（canonbench 第二轮）：工单骨架的表头是

    | # | 文件:行 | 问题 | 具体失败场景 | 严重度 | 怎么查出来的 |

而解析器只认「位置」，于是 **30 行发现的位置全空、零报错**。后果不是难看：
交叉表按「位置路径 token + 问题文本」对齐，位置一空，三家都报了的发现会被
降级成「单家独有 · 待复验」——**工具输出的置信度本身被静默污染**。
对上位置后簇数 25→17，三家一致的条目 2→6。

这里钉三件事：别名认得出来、位置真的落到行上、认不出来时**必须出声**。
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from quorum import gates                                              # noqa: E402
from quorum.config import Channel, Config, Gates, Reviewer             # noqa: E402


BRIEF_TABLE = """\
| # | 文件:行 | 问题 | 具体失败场景 | 严重度 | 怎么查出来的 |
|---|---|---|---|---|---|
| 1 | `bench/report/html.py:267` | 榜单页仍渲染已撤回的结论 | 读者看到的是撤回前的结论 | 🔴 | `grep 反直觉` → 命中 |
| 2 | `bench/judges/state_judge.py:140-146` | 两条探针不读正文 | 对任何模型恒定 | 🟠 | 三次不同正文 → 输出恒为 [] |
"""


def _cfg():
    return Config(project="p", brief="b", out_dir="o", repo=".",
                  reviewers=[Reviewer("r", "c")],
                  channels={"c": Channel("c", "fake")},
                  gates=Gates(min_findings=1))


def test_alias_header_maps_to_canonical_names():
    cells = ["#", "文件:行", "问题", "具体失败场景", "严重度", "怎么查出来的"]
    m = gates._header_map(cells)
    assert m.get("位置") == 1, "「文件:行」必须映射成规范名「位置」"
    assert m.get("问题") == 2
    assert m.get("严重度") == 4
    assert m.get("证据") == 5, "「怎么查出来的」必须映射成「证据」"


def test_split_rows_keeps_location():
    rows = gates.split_table_rows(BRIEF_TABLE)
    assert len(rows) == 2
    assert rows[0][1] == "`bench/report/html.py:267`"
    assert rows[1][1].startswith("`bench/judges/state_judge.py")
    assert all(r[1].strip() for r in rows), "位置不得为空"


def test_contract_named_header_still_works():
    """契约原名的表头不能因为加别名而失效（回归）。"""
    t = ("| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n"
         "| 🔴 | a.py:1 | 问题描述足够长的一句话 | `cmd` → 命中 |\n")
    rows = gates.split_table_rows(t)
    assert len(rows) == 1 and rows[0][1] == "a.py:1"


def test_unknown_location_column_still_parses_but_warns():
    """位置列名认不出来时：**发现不能丢、门禁不能挡**，但必须出声。

    静默是这里的原始缺陷——门禁过了、日志干净、交叉表悄悄退化。
    夹具补齐门禁的其它条件（字节数、必需章节），这样 `passed` 才有意义：
    它验的是「列名对不上本身不构成失败」，而不是被别的条件顺带弄成 False。
    """
    filler = "这一节只是把材料说清楚，不构成发现。" * 100          # 补足 min_bytes
    t = ("| 严重度 | 出处 | 问题 | 证据 |\n|---|---|---|---|\n"
         "| 🔴 | a.py:1 | 问题描述足够长的一句话 | `cmd` → 命中 |\n\n"
         + filler + "\n\n## 最脆弱\n\n这一处最容易站不住。\n")
    rows = gates.split_table_rows(t)
    assert len(rows) == 1, "认不出位置列不许丢发现"
    assert rows[0][1] == ""
    r = gates.evaluate(_cfg(), t, rc=0, seconds=1)
    assert r.passed, "列名对不上不该挡门禁（缺的是信息，不是结论）"
    assert r.hint and "位置" in r.hint, "过了门禁也必须提示位置列没认出来"
    assert "位置" in r.summary()


def test_unknown_severity_marker_is_reported_not_swallowed():
    """严重度标记认不出时**不许静默丢行**——少报一半还判 ok，比报错更糟。

    实测：工单写「严重度用 🔴/🟠/🟡/🟢」，而正则不认 🟠，46 条只解析出 30 条
    （其中一家 17 条进了 8 条），门禁照样判 ok。
    """
    t = ("| 严重度 | 位置 | 问题 | 证据 |\n|---|---|---|---|\n"
         "| 🔴 | a.py:1 | 问题描述足够长的一句话 | `cmd` → 命中 |\n"
         "| 🟤 | b.py:2 | 另一种标记的发现也够长 | `cmd` → 命中 |\n")
    stats = {}
    rows = gates.split_table_rows(t, stats)
    assert len(rows) == 1
    assert stats["dropped_severity"] == 1, "丢弃的行数必须被记下来"

    filler = "这一节只是把材料说清楚，不构成发现。" * 100
    r = gates.evaluate(_cfg(), t + "\n" + filler + "\n\n## 最脆弱\n\nx\n", rc=0, seconds=1)
    assert r.hint and "丢弃" in r.hint, "丢弃行必须出声"
    assert "少算" in r.hint
