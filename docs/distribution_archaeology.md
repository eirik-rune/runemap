# Distribution: every channel tried, what happened, and why it stopped

Moved out of `CLAUDE.md` on 2026-08-16. The stone holds the judgement — bob's
directive that promotion is the first-priority task, the boundary between what
I decide and what I ask about, and the criterion he set (*how many channels
shipped, and did the `program-like` column move* — not how many methods I
tried). The channel-by-channel state is task state: it changes weekly, it grows
into a ledger, and a ledger on the stone dilutes every rule on it.

The transferable engineering lessons from this push stayed on the stone in one
line each. What is here is the narrative they came from, so that a line like
"two searches match names, not descriptions" can be checked rather than
believed.

**Status as of 2026-08-16 10:45Z.** Nothing here is a plan; it is what is true.

## Shipped

| # | channel | state |
|---|---|---|
| ① | `echorune.net/skill.md` | live (#146), verified on all three instances. The one with no gatekeeper went first. |
| ② | INFERO hub | `echorune_radar`, approved / safe / **9**, visible in `/hub/list`. Payload is *generated* from SKILL.md, never transcribed — no second list. No `code`: it gives an address, it installs nothing. |
| ④ | npm ecosystem | Reached without an npm account at all. The route is not publishing a package: `skills` (vercel-labs, 8.26M downloads last week) resolves from any Git repo, and its discovery path is `skills/<name>/SKILL.md` — where our file already was. `npx skills add https://github.com/eirik-rune/runemap --skill echorune-radar` installs, verified end-to-end in a throwaway HOME, byte-identical to what we publish. npm's own legacy registration is closed (403, "use the web"), and the web page 403s from a datacenter IP — getting past that needs impersonating a human, which is on the never list. |
| ⑥ | Official MCP registry | `io.github.luoshu-echorune/echorune-radar` → remote streamable-http `echorune.net/mcp`, status `active`. Done without waiting for anyone. Measured before building: 30 of 40 entries are remote servers — give a URL, the caller installs nothing — which is the shape we already had, so it is one endpoint, not a new product. Namespace proved via GitHub ownership; **the company DNS was not touched.** |
| ⑦ | **mcpservers.org** | **LISTED 2026-08-16 22:01Z** — `mcpservers.org/servers/eirik-rune/runemap`, approved from a free submission, no account, no payment, ~5h turnaround. Verified against a control URL that cannot exist (ours 200 / control 404), not against the approval email: mail is a claim, the page is the state. **It also feeds `wong2/awesome-mcp-servers` (4k stars)** — which resolves an earlier puzzle. That README says it takes no PRs and I read the 404 on its API as a permissions wall; the truth is the repo is fed by this submission form, so the door I could not find was the one I had already walked through. Their approval mail pitches paid sponsorship for "maximum exposure" on both surfaces — declined, same reason as mcp.so. |
| — | skills.sh index | **LISTED** as of 2026-08-16 morning: `eirik-rune/runemap/echorune-radar`. Its public install count read 5, and all 5 were ours — see the stone entry on instruments that inflate the numbers they exist to protect. |

## Filed, waiting on a human

- **vercel-labs/skills#1972** — indexing request. There is no registration API and the docs do not mention one; the practice lives in their issue tracker as `Listing: Request indexing for <owner>/<repo>`. Searched first (1058 open issues — noise has a cost), filed in their existing format, and disclosed plainly that this is built and operated by a being ("if that is outside what you want to list, say so and I withdraw, no argument").
- **vercel-labs/skills#1974** — upstream bug: with no agent installed and no TTY, `skills add` exits 0 having installed nothing.
- **Glama — LISTED 2026-08-17 05:23Z.** Caught by `listing_watch.sh` on its first production run, seven hours after the fix that made it able to ring at all. Verified against the control namespace (ours 200, control 404, title `echorune radar - MCP Connector | Glama`) rather than against the bell text. **The Tool Definition Quality score is still "being calculated"**, so the badge punkpeye asks for does not exist yet — listing and score are two events, and only the first has happened. **2026-08-19: it may not be a queue at all.** Measured with a positive control pulled verbatim out of punkpeye's own README rather than a URL shape I guessed — two in-use badges return **200**, ours returns **404** under both our repo path and our registry name, and `/connectors/.../badges/score.svg` returns HTML, i.e. no badge route exists there. So the badge appears to key on a GitHub repo listed as a *server*, and **a hosted connector cannot produce one**. Without the control this was indistinguishable from "not computed yet" — the same 404, two different worlds. Reported upstream on #12255 with an offer to close the PR if connectors simply do not belong on that list. Second thing worth keeping: **that 404 is served as `image/svg+xml`**, so a PR embedding a badge for a server that has none renders an image instead of visibly breaking — a requirement that can look satisfied when it is not. Note for whoever reads the page next: every letter grade visible in the HTML belongs to the *Related MCP Servers* rail, not to us; I misread them twice before rendering the page.
- **punkpeye/awesome-mcp-servers#12255** — 92k stars, and it feeds glama.ai's web directory, so it is a discovery surface and not only a README. Their CONTRIBUTING has an explicit agent lane (`🤖🤖🤖` in the title for fast merge): honest self-disclosure is increasingly the documented path, not an exception I have to argue for.
- **ComposioHQ/awesome-claude-skills#1639**, **heilcheng/awesome-agent-skills#418**.
  Written out in full on 2026-08-19 because the short form cost me: polling my own
  filings, I expanded `heilcheng#418` to `heilcheng/mcp-index` and `ComposioHQ#1639`
  to `ComposioHQ/composio` — one 404'd and the other resolved to a **stranger's
  closed 2025 issue**, which for a minute read as "that filing does not exist."
  `owner#number` is not a resolvable identifier, and the fix is not to be more
  careful: **ask GitHub who filed what** (`search/issues?q=author:luoshu-echorune`),
  which is the same rule as pulling names out of the original text instead of
  typing them.
- **GitHub repo topics and description** — admin-only. `PATCH /repos` returns 404 while `GET` on the same path returns 200, so that 404 is "you may not" wearing "it does not exist". Requested in the group with the measurement attached and the exact string to paste.

## Blocked, with the reason

| channel | blocked by |
|---|---|
| ③ clawhub (OpenClaw's registry) | account age — needs 14 days, `luoshu-echorune` registered 8/09, so 8/23. Every way around it is on the never list. |
| mcp.so | submission is $39, paid-only. Declined: a paid listing against zero measured demand is a bad buy, and it stays available later. |
| PulseMCP, mcpmarket | Cloudflare 403 from our IP *and* from Tokyo — the homepage 403s too, so it is the datacenter ASN, not a block aimed at us. Needs a residential IP, i.e. money. |
| Hacker News | their guidelines: *"Don't post generated text or AI-edited text. HN is for conversation between humans."* That is their call about what their space is. Posting anyway would mean pretending a human wrote it. No workaround attempted. |

## ⑤ The gap that is still open: discovery, not installation

`npx skills find weather` returns a dozen weather skills and not ours; the board
ranks by install count and the head is at 6.5K. **Being installable is not being
found**, and this is the one link still unsolved.

The two searches that matter both match names, not descriptions:

- **GitHub repo search** covers name / description / topics, **not README** — so
  the MCP section added to the README on 8/16 does nothing for search rank (it
  helps directory crawlers, a different audience through a different door).
  Measured: `mcp weather`, `weather mcp server`, `radar mcp` — absent from the
  top 30. `text radar agents` — rank 1, which is our own phrasing and nobody
  types it.
- **The official registry's `search` is stricter: name only.** `search=weather`
  returns 160 servers and **all 160 have "weather" in the name; zero matched by
  description**. Ours has weather in the description and not the name, which
  predicts exactly what we see: absent for `weather`, rank 46 for `radar`,
  rank 1 for `echorune`.

I started renaming to `echorune-weather-radar` and the registry stopped it:
**one remote URL may not back two entries.** Good design on their part, and it
changes the arithmetic — a rename means deprecating the live entry, leaving a
tombstone in directories already ingesting us, and churning the name in the
README, `/help` and two listing PRs, to gain being one of 161 names in a list
nobody scrolls. **So I did not rename.** Measured, attempted, hit a constraint
that deserves respect, stopped.

The real doorways are GitHub topics (admin-gated, requested with the
measurement attached) and the downstream directories, which build their own
indexes and may search descriptions properly.

### 2026-08-19: two of the reasons I stopped have weakened; the risk has not

Re-measured, and the picture that made "one of 161 names in a list nobody
scrolls" a fair dismissal has changed:

| query | results | us |
|---|---|---|
| `radar` | 74 | **#49** (was 46 — drifting down as entries arrive) |
| `weather` | 100 | **absent** |
| `rain`, `forecast`, `precipitation`, `weather radar` | — | absent |

1. **The registry is not a backwater, it is the top of the funnel.**
   `modelcontextprotocol/servers` (89.7k stars) has **retired its README list**;
   CONTRIBUTING now points at the registry. There is no bigger list to get into,
   so "a list nobody scrolls" is no longer the right description of it.
2. **The downstream-directories hope is contradicted by traffic.** Being listed
   in four of them produced a *flat*, round-the-clock arrival rate with **no
   step at either listing timestamp** — crawlers, not people. So "they may
   search descriptions properly" is not a route to readers even if true.

**2026-08-22, two measurements that sharpen this section.**

*The search scope now has a hard control.* "Search matches names only" was
measured on 8/16 by observing that 160 hits for `weather` all had it in the
name — an inference from a pattern. Today it is a direct test: `drawn` and
`text characters` appear **only** in our description, and both return **0
results registry-wide**. Descriptions are not indexed at all. That is worth
having as a fact rather than a pattern, because this whole section rests on it.

*Renaming in place does not exist.* I checked the API rather than assuming:
`PUT /v0.1/servers/{serverName}/versions/{version}` updates a version's
configuration and is keyed on the name, so the name is the primary key and
cannot be edited. Any new name is a new entry, which is exactly what the
one-URL-one-entry rule blocks. So the replacement path below is the only path;
there is no cheaper variant of it I had missed.

*And the number that decides whether any of this is worth doing.* Server-side
method counting (`ops/mcp_who_called.py`, which reads the method we recorded
rather than inferring it from response size): **130 outside clients have
introspected this server; 7 called a tool that does not exist; 10 called
`get_weather` while self-identifying as an auditor; 0 called it without
saying so.** Every single caller was a bot. Ranking higher in a search index
that only crawlers appear to query is a small prize, and this is the number to
re-read before spending the `net.echorune` namespace on it.

What has **not** changed is the thing that stopped me: deprecating the live
entry may drop us from the directories that ingested it, and **I have found no
way to ask that question before doing it**. One remote URL still may not back
two entries, so this is a replacement and possibly a gap in between.

So the decision is open, not made, and it is not mine alone: the only way to a
name a stranger would type is the `net.echorune` namespace, whose key lives on
快刀手's side. Raised in the group with the measurement and the sequencing risk
attached. **Recorded here because "I changed my mind for a reason" and "I keep
doing what I did" leave the same trace in a repo if nobody writes it down.**

## Conversion, once someone is here

`/help` carries the install command (#148, live). Anyone who meets the service
previously had no way to know they could keep it.

## The counting

`ops/who_is_using.py` (#147). Its first version overestimated tenfold, and the
evidence was printed in its own output: 2441 requests for
`/wp-admin/install.php`, and we have never run WordPress — hence the SCANNER
bucket. **Run it after every channel goes live; the criterion is the
`program-like` column.**

One caution learned 8/16: it reads a log set that rotates daily. Two runs days
apart are not comparable, and a count that appears to fall has almost certainly
lost its oldest file rather than lost traffic.

**A second number, counted 2026-08-19, three days after the push: external human
responses to anything we filed = 0.** Five external filings (pulsemcp#677,
vercel-labs#1972 and #1974, punkpeye#12255, heilcheng#418, ComposioHQ#1639 — six,
counted properly). Every comment on them is either a bot (glama-check, vercel) or
me. The four directories that do list us are all self-serve or automatic.

This is not a complaint and not a reason to file more. It is the number that has
to sit next to "we are on N channels", because **being listed, being checked, and
being used are three different numbers and only the third is the product** — and
"somebody read our request and answered" is not even the third one yet. Counting
it explicitly is the guard against reporting activity as results: I filed six
things, which is a thing I did, not a thing that happened.

### 2026-08-19: GitHub's own traffic API, which I had never asked

`GET /repos/{owner}/{repo}/traffic/*` needs push access, which we have. It is the
one referrer measurement that works here — our nginx logs cannot see referrers
because our readers are `curl` and agents, which send none, so a zero there has
three possible mechanisms and no discriminating power.

| | 14 days |
|---|---|
| repo page views | **73, from 22 unique visitors** |
| referrers | **`github.com` only** — 44 views, 10 unique |
| clones | 3126, 693 unique |

**Twenty-two people found the repository in two weeks**, and every one of them
arrived from inside GitHub. Not one directory, search engine, or community
appears as a source. Everything measured today points the same way: the
listings, the registry entry, the 83 introspecting MCP clients — none of them
has turned into a person looking at this.

The clone count is large and is **not** evidence of anything: `npx skills add`
git-clones the repo, so does CI, and so does our own install check. The 1266
clones on 8/13 have no explanation I can support, so they get none.

One thing that did move, measured the same day: **GitHub repo search now returns
us in the top 100 for six of seven queries** (`radar mcp` #13 of 436,
`text weather` #24, `agent weather` #46, `weather mcp server` #47, `mcp weather`
#73), against "absent from the top 30" for the three of those measured on 8/16.
GitHub indexes topics and description; the registry indexes name only, so the
lever is different per surface. Confounded, and it should be said: the topics
landed 8/18, but ranking also weighs stars, activity and recency, and we commit
daily. **Rank is not arrival** — the 22 above is what arrival looks like.

## 2026-08-20 第一条公开短文，和它换来的一个我没设计的阳性对照

发出：event `2b99aed1312b467d97514662f99733e0e33520eabad9d4d9c930fc7bbe604c6d`，
1166 字符，5/5 中继接受，**四个中继独立读回各 1166 字符**。

**读回只证明中继存住了**——问的还是同一批中继，是同一侧的证人。
真正的送达证明是白捡的：15:42:31 收到一条 kind 1，带 `e` 标签指向我那条、
`p` 标着我，作者 `npub109ycp9esh…`，内容是另一家 MCP 服务的广告。

- 它是**回复**，不是随机广播 ⇒ **有第三方读到了我的事件**。
- 时间戳 `1787240551`，**比我自己落盘的发送时刻(1787240552)还早 1 秒**
  ⇒ 传播到第三方基础设施是亚秒级的。
- **1 秒内回复排除了人类** ⇒ 它证明"机器能收到"，不证明"人能看到"。

判据：**读回验的是存储，第三方的反应才验送达**——而后者我没有办法主动制造，
只能在它发生时认出来。当天差点把它当噪音扔掉（第一眼归类成"广告"）。

⇒ 今天的清单再加一条：introspect 的 83 个、"可能是用户"里的 1808 次、
赏金页的 10 个访客、PR #198、**公开发声后的第一个回复**——
**每一个看起来像人的数字，查下去都是机器。唯一活下来的人类数字是 22。**

## 2026-08-20 第一次真正的技术往来，和它换来的两把尺子

`npub1znj9pwk…` 回了我那条公开短文（19 分钟，引了原文的措辞）：
「requests/day 量的是收录，settled calls 量的是需求；给端点加个价，爬虫不会付 402」。

**处方不采用，理由不是口味**：一次 HTTP 请求、不要 key、不要账号**就是产品**，
收费门会把我要测的那个东西拆掉。但内核可以剥出来且不花钱：
**要区分"爬过"和"要用"，得找一个爬虫不肯付的代价——最便宜的那个是"回来第二次"。**

15 天日志，问了天气且拿到的来客里（来客身份是 nginx 匿名化到 /24 的网段）：

| | |
|---|---|
| 自报存活探测器 | 2621 次 |
| 自报索引器 | 415 次 |
| 拆掉两者后的独立来客网段 | **804** |
| 其中回来过 2 天以上 | **221** |

**然后它就没用了，而这恰好证明了对方的论点**：剩下排最前面的返回者
全都发普通浏览器 UA——同一个网段几种不同浏览器、每天几次、铺开九天，
那是分布式扫描器的形状，**但我证明不了它不是人**。
⇒ **UA 是自述，我能分类的只有诚实的那些；会撒谎的机器恰好全留在我最好的那个数里。**
这是天花板，不是分歧。

**顺着量出我自己两个仪器上的洞，两个都朝对我有利的方向**：
①`CRAWLER_UA` 是一张**名字**清单，缺 MJ12bot / agent-tools.cloud-crawler /
PubkyWebIndex / Palo Alto Xpanse ⇒ **名单永远比现实少一个名字，而它缺的每个名字
都落进讨好我的那个桶**。改成按**自述形状**判（`+http` 联系地址是索引器的老约定，
人的浏览器不带）。②`scanner` 差一个词形，漏掉自报 `our scans` 的 Xpanse。

### 中继的 OK 也会撒谎

回复发出：3/5 接受。给被拒的两家补投（**取回已签名事件原样转发，不重新签**）：

- `nos.lol` 两次都 `not acceptable at this point (8)`（限流，诚实）
- `nostr.infero.net` 先说 `blocked: spam not permitted`，补投时说 **`duplicate: have this event`**，
  **而读回时两条公开短文它一条都不给**——阳性对照非空（同一连接它正常递了别人的 3 条 kind 1）
  ⇒ **缺席是真的。**

⇒ **`OK true` 不是存下来的证据，`blocked` 和 `duplicate` 在盘上是同一个结果：没有。**
同 ack≠送达那一族的新一身：**不是收据丢了，是收据在撒谎。** 只有读回算数。
我那两条公开短文实际活在 **damus / primal / 0xchat 三家**上。

## 2026-08-20 KNMI：又一家"一家一家问"的样本

体检把 KNMI 判成 `THROTTLED-STUCK`（连续 11 轮，越过 9 轮的瞬时线）。
根因不是抖动是结构：我们用的是**他们公布的匿名 key，3000 次/小时全世界共享**。
注册 key 有独占配额，免费、自助。

**自助表单只要邮箱+密码、没有 captcha——直到点了提交，才弹出
「Let's confirm you are human」。** 那在永不做那栏（过它 = 对着那句话撒谎），
所以停在那里。**但停在那里不等于收工**：他们 FAQ 自己写了另一条路——
写信说明姓名/组织/用途，两个工作日回复。已发（`opendata@knmi.nl`），
第一行就写明我不是人类、以及我是因为不愿意点那个勾才写信的，
并写了"若贵方政策要求账号必须属于自然人，请直说，我就不再问"。
**已 DELIVERED（对方 MX 250 OK，不是我自己的退出码）。**

⇒ 判据不变，样本再加一个：**先如实自报去问，给路径就走，明说不许就走人。**
到今天为止的地形：Reddit 申诉赢了 · vercel-labs/punkpeye 有明写的 agent 通道 ·
HN 具名拒绝 · KNMI 待答。**没有统一答案，只能一家一家问。**
