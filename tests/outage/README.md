# 诱发式坏池实验 (induced outage)

问的是终点指标：**故障期间读者那一屏有没有雨图**（24 行 × 48 列），不是拨号成功率、
不是 HTTP 200。#79 的病就是拿代理指标顶替终点指标。

## 跑法

    python3 tests/outage/negative_control.py          # 先跑：无规则时关臂必须能出图 3/3
    OUTAGE_SAMPLES=/tmp/paired.txt python3 tests/outage/induce_outage.py
    python3 tests/outage/verdict.py /tmp/paired.txt   # 判词由它打印
    bash tests/outage/unblock.sh                      # 收工必跑，剩余规则必须 0

两臂：`runemap-dev.service`(8790, 有回落) 与 `runemap-ctrl.service`(8791, 环境变量置空＝全短路)。
iptables DROP 按 cgroup 圈住这两个 unit，**生产 unit 全程零条规则**。每轮 exec 都要查
`dev=? ctrl=? prod=?`，prod 必须恒 0。危险改动先装 `sleep N; unblock.sh` 安全网再插规则。

## 判词是跟着数据走的，不是跟着程序走的

判据在数据存在之前钉死在 `induce_outage.py` 的 docstring 里，`verdict.py` 逐字转抄。
但判据**改过一次**，于是旧数据在新程序下算不出它当时的判词——这不是 bug，是必须留痕的事：

| 数据 | 当时的判词（权威） | 今天用 verdict.py 重算 |
|---|---|---|
| `data/run1_FAIL.txt` | **FAIL** (scored n=8, on 8/8, off 1/8) | INSUFFICIENT (n=0) |
| `data/run2_PASS.txt` | **PASS** (scored n=8, on 8/8 中位 0.61s, off 0/8 中位 6.30s, 4 池, 排除 1) | PASS |
| `data/run_contaminated.txt` | 作废：两个采样器并发改 iptables，弃样 | — |

run1 为什么 FAIL：一条样本里关臂 1.34s 就画出了图——那是**没被挡住**的样子。DNS 每分钟
换一次池，规则可能指着一个没人在说话的 /24，那一行的"故障"标签是假的。
事后把它剔掉就是**放宽门槛去迁就数据**。所以改的是尺子不是门：采样器现在在提问之后
**重新解析一次** DNS，记 `stable=yes/no`，排除规则写在 run2 开跑之前。被排除的行会
被数出来打印，不藏。

代价是旧数据缺 `stable` 字段而被全部排除 ⇒ run1 的 FAIL 只能由这张表作证。
**归档数据必须自带当时的判词**，否则改一次判据就等于把历史重写成沉默。
