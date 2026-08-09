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


## 两条静默坑, 事后逐字复核 (8/9 03:34)

配对实验只说明"开了以后读者看得见图", 它不说明**为什么**。两条最可能的静默失败
在实验里都不会现形, 所以事后从 /opt(真正在跑的那棵树)逐字读了一遍, 不从 ON 8/8 反推。

(a) 记忆的单位是 POP 不是机器。happy_eyeballs.py::_pool 返回
    ".".join(ip.split(".")[:3]) -- 八个地址同一个 /24, 记住两个地址等于记住同一栋楼里的
    两台机器, 楼一黑两份记忆一起死。按 /24 分桶, 记住的才是**上一个**池。
    若这条没实现, ON 8/8 的胜因另有其人, #32 的因果措辞就得降级。它实现了。

(b) 记忆能不能变回一个 socket。tests/test_pool_memory.py::
    test_memory_written_by_a_real_winner_can_be_redialed 做的是往返:
    真实 connect 写入记忆 -> 换黑洞 DNS 且清空记忆, **负对照先红**(assertRaises OSError)
    -> 只放机器产生的那个 entry, 重建成功且 getpeername() 命中好地址。
    这条重要是因为 Linux 上 socket 的 type 会带 flag 位(SOCK_NONBLOCK/SOCK_CLOEXEC),
    一旦漏进 entry, socket.socket(family, type, proto) 会抛 OSError -- 而 dial() 捕获它,
    于是那个地址只是"输掉比赛", 整个机制安静地失效, 一行错误都不会打。

其余测试全部手搓元组喂给 _remember, 所以没有任何一条能证明**真实赢家**产出的 entry
可以被重建。名字像不等于做了那件事 -- 这两条都是读了正文才算数。
