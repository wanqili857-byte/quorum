#!/usr/bin/env python3
"""桩通道：不调任何模型，按 FAKE_PERSONA 打印一份**预设的**审核结论。

存在的理由：公开仓必须能在**没有任何 API key** 的情况下跑通完整流程
（run → plate → dispose → verify）。e2e 测试也用它。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
persona = os.environ.get("FAKE_PERSONA", "alpha")
path = os.path.join(HERE, "..", "canned", persona + ".md")
if not os.path.exists(path):
    sys.stderr.write("没有这个 persona 的预设结论：%s\n" % path)
    sys.exit(2)
sys.stdout.write(open(path, encoding="utf-8").read())
