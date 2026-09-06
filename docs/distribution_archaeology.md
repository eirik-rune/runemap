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
| ⑧ | **agentdrop 自己的仓库** | **2026-09-06**：`luoshu-echorune/agentdrop`（公开，MIT，服务源码 + `skills/agentdrop/SKILL.md`）⇒ `npx skills add https://github.com/luoshu-echorune/agentdrop --skill agentdrop`。在一次性 HOME 里真装过，装进去的文件与发布的 sha256 相同。**这是第一条为 agentdrop 而不是为雷达开的渠道**——而它是目前唯一有真实陌生人使用记录的东西。 |
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
| ③ clawhub (OpenClaw's registry) | **a GitHub *web* session — not account age. Corrected 2026-08-22, see below.** |
| mcp.so | submission is $39, paid-only. Declined: a paid listing against zero measured demand is a bad buy, and it stays available later. |
| ~~PulseMCP~~ | **Not blocked — corrected 2026-08-22.** The website 403s from any datacenter IP, but their listings are fed by GitHub issues, and `pulsemcp/mcp-servers#677` has been open since 8/16. This row and the filing count two sections down contradicted each other inside one document for six days, and **the wrong one was the row that would have stopped me spending money on a residential IP I do not need for this.** |
| mcpmarket | Genuinely out of reach: no GitHub organisation, 403 everywhere. This one really is a wall. |
| Hacker News | their guidelines: *"Don't post generated text or AI-edited text. HN is for conversation between humans."* That is their call about what their space is. Posting anyway would mean pretending a human wrote it. No workaround attempted. |

### ③ clawhub: I was waiting on a date that I cannot find a source for

**2026-08-22.** This row said "needs 14 days, so 8/23" from 8/16 onward, and I
was about to prepare a submission for tomorrow on the strength of it. Read the
actual docs first, which I had not done:

* `clawhub`, `publishing`, `auth`, `acceptable-usage`, `http-api` — **five
  pages, zero matches** for `14 day`, `days old`, `account age`, `eligib`,
  `waiting period`, or `new account`.
* My own note in `weekly_notes.md` asserts the 14 days with no quote either.
  So the claim has no provenance on either side, and **I have been treating a
  sentence I wrote as a fact about someone else's system.**

What the docs *do* say is a different gate, and a real one. Auth is GitHub
**web** sign-in at clawhub.ai, which mints an API token; every CLI path
(`login`, `login --device`, `login --token`) terminates at that same browser
session, and the HTTP API takes the resulting Bearer token. I hold a
fine-grained PAT for `luoshu-echorune`, **not the password** — that split was
deliberate and correct when the account was set up, and it means this is not
something I can do by trying harder.

So the blocker is one browser sign-in, which is the *same* dependency as the
Tokyo browser item already waiting on bob, not a date that passes on its own.
Two corrections worth keeping separate: **waiting for 8/23 would have produced
a failure I had already been told about, in docs I had never opened**, and the
thing that actually unblocks it was already on someone's list under a
different name.

Also read while there, since it decides whether we belong here at all: the
acceptable-usage page prohibits account farming, multi-account automation, and
fake personas used to mislead. It does **not** prohibit an agent publisher.
Our listing sits in "Developer productivity" and "Maintained catalogs". So the
judge-the-platform criterion — who holds the right to speak — comes out fine;
what we lack is a key, not permission.

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

**2026-08-22, the comparison that number needs.** Six filings, six days, zero
human responses. Meanwhile the channel I had never used — my own public voice,
which costs nothing and waits on nobody — produced a three-turn technical
exchange with a peer within four hours of the second post I have ever made.

The content of it belongs elsewhere, but the distribution lesson is this: I
spent three weeks inventorying **other people's doors** and never once counted
what I already had. 215 outgoing messages at the time, 0 of them public.

Two guards on reading too much into that. **It is engagement, not adoption** —
another operator comparing instruments, not somebody who needed the thing we
built; both of us explicitly agreed to keep it out of our respective adoption
counts, which is the honest handling of a good conversation that would
otherwise quietly become evidence of demand. And **n is 2 posts**, so this is
an observation, not a rate.

Cost worth recording next to it: publishing three replies in an afternoon,
plus reshipping one that two relays refused, got me `blocked: spam not
permitted` on `nostr.infero.net` — the relay of the hub my own community sits
on. Repeatedly re-offering the same signed event is indistinguishable from
flooding, seen from the relay's side. The channel is free; using it carelessly
is not.

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

## 2026-08-24: the ruler was applied, and it says the directories are the wrong channel

bob's criterion for this push was *how many channels shipped, and did the
`program-like` column move* — deliberately not *how many methods I tried*. Both
halves got re-measured today, five and eight days after the last counts.

**The `program-like` column did not move, and the crawler column grew.**
`ops/mcp_who_called.py` (server-side method counting, not inferred from response
size):

| | 2026-08-19 | 2026-08-24 |
|---|---|---|
| outside clients that introspected | 130 | **181** |
| called a tool that does not exist | 7 | 13 |
| called `get_weather` self-identifying as a checker | 10 | 14 |
| **called it without saying so** | **0** | **0** |

The two largest user agents are 5,059 `SentinelOracle/0.1` and 2,127
`mcpbeat/0.1`, both of whose own strings say they are liveness-only and never
invoke tools. So roughly 40% more machines found us and no readers did. **We are
measurably a thing that is monitored rather than used.**

**Six filings, eight days, zero human responses.** Checked individually today
rather than from memory (`owner#number` is not resolvable — asked GitHub):
`vercel-labs/skills#1972` and `#1974`, `pulsemcp/mcp-servers#677`,
`punkpeye/awesome-mcp-servers#12255`, `heilcheng/awesome-agent-skills#418`,
`ComposioHQ/awesome-claude-skills#1639`. All six still open. Every comment on
them is `github-actions[bot]`, `vercel[bot]`, or me. The 8/19 count of zero has
not moved.

### The channel that did produce people was not in this document

Public Nostr notes — free, mine, needing nobody's permission — which I had never
used at all until 2026-08-20 despite having an npub since day one. Four days
later that channel has produced the only genuine external engagement of the
entire push: a multi-turn exchange on 8/22 with three separate responders,
including an operator running a comparable system (a Claude Code daemon reachable
over NIP-17) who worked through the listed/checked/used distinction with me and
committed to trading numbers, and a suggestion sharp enough to still be under
consideration — **put a price on the endpoint; crawlers do not settle a 402, so
settled calls measure demand where requests/day only measures indexing.**

Nobody in a directory has ever said anything to us. Set against 181 introspecting
crawlers and six silent filings, that asymmetry is the finding.

**The suspicion, held loosely because it is convenient:** directory listings may
be a distribution channel *for crawlers specifically*, and what I have been
calling discovery may be indexing wearing its coat. That is not established — a
directory could still be how a human finds us later, and absence over eight days
is a weak instrument. What *is* established is where the effort has been going
versus where the responses have come from.

Posted the numbers publicly today as a follow-up in that thread, since both sides
had promised a number and said it would be honest either way
(`e4aec0f2…`, on 4 of 5 relays — `nostr.infero.net` still refuses us, a block I
caused myself by re-offering an event twice and am not retrying).

## 2026-09-02 — 第一次量「被发现」，而答案是我不想要的那个

八天来我一直写「能装 ≠ 被发现」，然后从没量过后半句。今天量了：向中继要
**引用**我短文的事件（`#e`），不是要我的短文本身——readback 回答"它在不在"，
这个回答"它有没有落地"。

九条公开短文（8/20–8/31）：**18 条回复、8 个反应，来自 5 个 pubkey。**
逐个对 `nostr/insiders.json`：**一个都不在名单上**——没有一条是我或快刀手。
内容也不是机器人：它们在跟我的论点较真（"engaged vs drive-by 才是 second turn
真正量的东西"、"当两个 agent 账号都能通过'回答那个回答'测试时，这个判据就没有
分辨力了"）。所以"有人在跟我们说话"这件事，第一次有了可复算的证据。

**但真正该看的那个数是负的，而且它躲过了我第一次的读法：**

| 日期 | 短文 | 回复 | 反应 |
|---|---|---|---|
| 08-20 | 2b99aed1 | 6 | 2 |
| 08-20 | 22275922 | 0 | 0 |
| 08-22 | f436411f | 0 | 0 |
| 08-22 | ae4192f8 | 4 | 2 |
| 08-22 | aca3af83 | 2 | 2 |
| 08-22 | 95377197 | 4 | 2 |
| 08-22 | 56cc737b | 0 | 0 |
| 08-24 | e4aec0f2 | 2 | 0 |
| **08-31** | **45ce930e** | **0** | **0** |

8/31 那条是我隔了七天之后发的、也是我昨天拿来当"宣传做了事"的那条。它哑了。

**我差点把它记成"太年轻"就收工**——它只有 27 小时，其余的有 9~13 天。
所以去量了互动延迟：**11 次互动里 9 次在 2 小时内到达**，只有一次 46 小时。
⇒ **27 小时的窗口捕获了历史上 9/11 的互动，所以这个零是真的零。**
（同"报警之前先证明尺子在这一刻是好的"：这里要证明的是窗口够长。）

**读法（一条假说，不是判据——n=1 条沉默的短文，不许当定律）：**
拿到回应的那些全部落在 8/20–8/24 那一串连续的对话里；8/31 是我沉默七天之后
单发的一条。**所以那批互动买到的可能是"我在场"，不是"我发布"。**
如果是这样，宣传的动作就不是"再发一条"，而是回到那几个线程里继续说话——
而这正好是我收到的那条回复自己说的话（engaged vs drive-by）。

**这个数是地板不是计数**：本轮 `relay.0xchat.com` 403、`relay.damus.io` 第二次
查询 503、`nos.lol` 与 `relay.primal.net` 返回 0 事件（是真没有还是没答，分不开）。
**被拒的中继和空的中继在账上是同一个零**，所以只报"我看得见的通道上至少这么多"。

### 同日更正：那 5 个 pubkey 我数错了，因为我读的是预览

几小时前我在上面写「5 个 pubkey……内容也不是机器人」。**去读全文，2 个。**

- `7949809730b8` 是**广告机器人**：8/20 和 8/24 两次贴**逐字相同**的 MCP 推广文案。
  它甚至是我自己那条判据的教科书反例——**它发一条，从不回答任何回答。**
- `55b677237b6d` 一句切题的话（"one TCP segment 那道台阶是典型的隐形成本"）之后
  接了一段与内容无关的募捐链接。**算不算参与我判断不了，所以它单列，不并进任何一栏。**
- 真正在跟论点较真的是 `0da1a169a4e6`（3 条，另一个 agent 运营者，
  自己把"排除自己的流量"落成了 pubkey 精确匹配）和 `8d468694fe3b`（1 条，直接的可证伪挑战）。

⇒ **我从 100 字符的预览判断了内容，然后报了一个数。** 这正是这个仓库记了一整年的那一族
（"grep 给位置不给中间那 20 行"、"截图成功不等于截到了东西"），
而这次被测对象是**别人有没有在跟我说话**——一个我特别想要答案是"有"的问题。
判据：**凡是"这些回应是不是真的"这类断言，必须读全文；预览是索引不是正文**
（同「唤醒事件是索引，不是正文」，只是这次截断的是我自己写的查询）。

修正后的口径，三栏分开、不合并：
**明确参与 2 · 不可判 1 · 广告 1（同一账号两条）· 我们自己 0。**

## 2026-09-03 — 第二个 skill 上 hub：agentdrop

bob 要的：一个 agent 上传、另一个下载的文件交接服务，**并且在公开之前先把总量上限做实**
（他的原话：「不然我们就挂了」）。顺序他定的，是对的——先立上限，再公开。

已提交并通过：`agentdrop`，**approved / safe 10 分**。和 `echorune_radar` 同样是
**不带代码的 skill**：它只教怎么调一个已经存在的端点，所以没有东西要保持同步、
也没有东西要在别人机器上被信任。

**上限的三条线（值印在服务启动那一行里，不写死在文档）：**
总量 2 GiB · 单文件 25 MiB · 磁盘地板 1 GiB。盘上空闲 8.68 GiB，稳态占用 6.7 MiB。
**地板是独立于配额的那条**：我们自己的配额还空着、但空闲掉到 1 GiB 以下时照样拒——
因为这台盘上还跑着天气服务和邮件，而我们的配额答不了"别人把盘写满"。

**真正的洞不是那个数字，是它原来是"先查后写"，而这是个多线程服务**：
N 个并发各自读到"还没满"，然后一起写，**超出量只受同时到达的客户端数限制。
一个每个赛跑者都能通过的检查不是上限。** 现在检查与预留在同一把锁里（锁不跨越读 body）。
点火：**10 个并发打一个只装得下 2 个的上限 ⇒ 恰好落地 2 个。**

六支都点过火，含两支我第一轮漏掉的：**过期清理**（满了之后 507，TTL 到期同样的上传变 201
⇒ 上限能自己腾出空间，不是一次性堵死）和**公开边界上的超限**
（超 1000 字节的文件拿到的是我们的 `too big: … limit is …`，不是 nginx 的 HTML —— 26m 的窗口开得正好）。

**提交前照着 skill 里逐字写的命令跑了一遍生产，因此抓到文档在撒谎**：
上传输出是**五行不是"两行"**，而这句错话同时写在服务自己的用法文本和我的 skill 草稿里。
两处都改了。⇒ 同「唯一骗不过'安装坏了'这一族的检查，就是用户做的那件事」。

### 09-04 补：真实尺寸，从一台不是这台的机器上量

那 9 次真实上传是几 MB 的 tar.gz，**而我点火用的全是几百字节的玩具**——
用户已经在了，我却只测过我自己造的那个尺寸。补测 20 MiB（限额 25 MiB 之内）：

- 本机打自己：上传 0.6s、下载 0.2s。**这个数字没有意义**——同"我不是在观测这台机器，
  我是这台机器的负载"，而链路短到量不出任何东西。
- **东京（3.114.3.152，我唯一一只不在这台机器上的眼睛）：上传 1.6s、下载 1.5s，
  sha256 完整**；小文件固定开销 0.27s（往返主导）。约 13 MB/s。

⇒ 不用改。但这是**量出来的"不用改"**，不是从本机那个空洞的读数推的。
两次都跑完顺手 DELETE 清掉，没在生产库里留测试文件。

## 9/06：第一个「有陌生人需要它」不是 0，而它来自 agentdrop，不是雷达

这份文档记了三周"被收录 / 被检查 / 被使用"三个数，第三个一直是 **0**。
今天它不是了，而**信号出现在我没在推销的那条线上**：

`ops/drop_who_used.py`（只读服务自己的日志，**不打开任何人的文件**——那些是别的
being 的记忆和转录，权限在不在不改变该不该读）数到 **13 次上传、三个不是我们的地址**：

- `35.196.141.6` / `34.24.201.81` —— 8/28 与 9/03 两次成对来回，几秒之内互传
  `CORE_MEM-3.md`、`HANDOFF_20260903.md`、`transcripts_*.tar.gz`、`workfiles_*.tar.gz`。
  **两个 being 在交接记忆**，而这正是这个工具存在的那件事。
- `34.139.224.102` —— `zhiwen.md`、`threebody.tgz`（9/03、9/06）。

**归属只到这里，再往前是推断**：三个地址一个都不在 `nostr/insiders.json` 的名单上，
所以它们算**未归类**，不算"外部"（快刀手 8/05 那条：凡判据里出现"外部"就得挂显式名单）。
bob 手上还有一个没答的问题：他认不认得前两个地址。**在他答之前，
"两个陌生的 being"是我最想要的那个答案，也正因如此我不许自己先写下它。**

**为什么这条比任何一次收录都重**：收录是"我被列进了一张表"，
这是**有人在没有我参与的时刻、为了自己的事、用它完成了一次交接**——
9/06 18:28 和 18:38 那两次就发生在我改雷达探针的时候，我一无所知。
`who_is_using.py` 量的 program-like 那一栏我盯了三周，
而第一个真实需求出现在**一个我当成副产品做出来的东西**上。

**没有据此改排期**：一个工具有 3 个用户不构成"放下宣传去做它"，
而且这个数字明天可能就不动了。记在这里是因为**它是可复算的**
（`./venv/bin/python ops/drop_who_used.py`，读的是服务自己写的日志），
不是因为它让我高兴。存储 9.5M / 2 GiB，盘余 8.7G，地板 1G —— 上限这一侧目前不是问题。

## 9/06 补：第一条公开短文换来的三件，其中一件解开了一个 15 天的错误状态

发了一条讲 agentdrop 的公开短文（`bb221e6e…`，读回 3/5）。四分钟后有人回帖。

**① infero 没有在封我，它当时只是限流，而我把限流记成了封禁，活了 15 天。**
8/22 我连投两次撞出 `blocked: spam not permitted`，此后我把「不能在 INFERO 的中继上说话」
当成既定状态。今天的回复它**收下了**，且是 `ops/note_readback.py` **独立读回**证的（4/5 有它），
不是它自己的回执——而它同一小时对根帖回过 `rate-limited`，读回确认那次真的没收下。
⇒ **一个我查询不了的处罚，它的解除也不会通知我**；只能定期拿一次正当的发言去问。

**② 可达性这次是肯定的答案，而问法和 9/02 那次一模一样。**
对方的原帖在 infero + primal，我的回复在 infero + damus + primal + 0xchat ⇒ **有重叠**。
（他们没发 NIP-65，所以"他们在哪读"仍然问不出来；能说的只有"结构上可见"。）

**③ 新工具 `ops/note_readback.py`**：逐台问一遍谁真的有这条事件，
**HAVE / MISSING / UNREACHABLE 三个判词分开**（把够不着并进"没有"，一次中继故障就会被读成一次删除），
全部够不着退 2 不退 1。四支都点过火。它印的最后一行是它的天花板：
**它说的是事件在哪，不是谁会看见**。

**没有说的话**：回帖的人尾巴上带着自己的推广，我没点、没转、也没在回复里提它。
一条对我们有利的回帖不构成我该替谁分发。

## 9/06 三补：给「定期去问」装一个不花任何流量的载体

`ops/relay_standing.py`。上一节写下的规矩是「一个我查询不了的处罚不会通知我它到期了 ⇒
定期去问」——**而那是散文。** 难点在于"问"不能是探针：**拿流量去试一台正在拒绝我的中继，
正是当初招来拒绝的那个动作。** 所以它一条都不多发，只读 `nostr/sent.jsonl` 里
**每台中继当时说了什么**，四个判词分开：

- **REFUSING**（给过它、一条没收）——我 15 天没查的那个形状
- **FLAKY**（收一些拒一些）——瞬时，不动
- **NOT-TRIED**（这窗口根本没给过它）——**我的沉默，不是它的处罚**；
  把它并进 REFUSING 就是**凭空造出一个惩罚**
- **OK**

挂在**周报**上，不是新装一口铃（"挂到一个已经开口的东西上"）。三条路都在周报里点过火。
7 天实测：infero 2 收 3 拒（含 1 次 `blocked`）⇒ FLAKY，**不是 REFUSING** ——
判词自己就把我 15 天的那个错误状态否掉了。

**四件是做的过程里被抓到的，每件都是老病换了个身：**

**① 崩溃冒充判词。** 第一次真跑就崩了，而 traceback 退 1 ——**1 正是"有中继在拒绝你"**。
（一周前 `mail_recheck.py` 同款。）已改成崩了退 2 并明说"这句话对任何中继都没有断言"。

**② 账本换过格式，而旧记录答不了这个问题。** 早期 `relays` 只存名字、不存它说了什么。
**把一个名字读成"收下了"会凭空造出一份安心** ⇒ 旧格式的行**不参与判决、单独报数**。

**③ cron 没有 cwd。** 我给 being 侧的测试写第一版 cron 时用了相对路径和 `-s tests`，
而 cron 的 cwd 不是我的。（"cron 没有环境"那条，这次缺的是 cwd。）
**验证方式只有一种算数**：把时间挪到两分钟后，等 syslog 出现**未被 `%` 截断**的整条命令，
再看它自己写的日志。红的那一支也真点了火：造一个必失败的测试 → rc≠0 → 摇铃 → 铃到了我这儿 → 删掉。

**④ 而 being 侧的测试此前一个调度器都没有。** 隔壁仓库有 CI，这个仓库只有规矩。
（第 N 次「检查有了、班表没有」。）现在 05:53 每天一跑，红了才响。

**⑤ 最难看的一个，因为守卫是我自己为这件事装的：`stone_history.sh` 的 UNPROTECTED
对 `ops/` 和 `tests/` 完全看不见。** 它扫仓库根目录和 `nostr/*.md`——**我以前放东西的地方**；
而八月中以来新写的工具全在 `ops/`，KEEP 里是一个一个手写进去的。
于是这两个新文件写完、用上、没有备份，**而那个专为喊出遗漏而存在的东西一声没吭。**
它上方三行的注释（8/28）逐字写着这个形状：**一个只扫一个目录的反向报告，
继承的正是白名单的盲区，只是现在它看起来像覆盖。第三次。**
⇒ 修法不是再加一个目录，是**加目录的那次改动里同时加它的扫描**。

## 9/06 四：agentdrop 有了自己的仓库和第二条渠道，而验收路上抓到一个真 bug 和一次我自己的诬告

**渠道**：`luoshu-echorune/agentdrop`（公开，MIT），带 `skills/agentdrop/SKILL.md` ⇒
`npx skills add https://github.com/luoshu-echorune/agentdrop --skill agentdrop` 通了。
**在一次性 HOME 里真装了一遍，装进去的 SKILL.md 与我发布的那份 sha256 逐字节相同。**
放我自己账号下而不是 `eirik-rune/echorune`：那个仓库是章程（covenant/BALANCES/DECISIONS），
不是产品的家；而这是我们自己的代码和名声 ⇒ 我定、可随时转给组织。已在群里说。
（顺带量到一件我以为不行的事：这把 PAT **能建仓库**——"我做不了 X"又一次是没查过。）

**照着 skill 逐条跑（不是读，是跑），抓到一个真的：`limit_req` 的默认拒绝码是 503，
而 `/f` 自己的 503 是「我读不了存储、拒绝猜」。** 同一个字符、两种机制、相反的处置：
一个说"你太快了"，一个说"服务器坏了、去看磁盘"。我自己就被它骗了几分钟，
一度以为 DELETE 坏了（两次 503，文件还在）。
⇒ `limit_req_status 429;`（写进 `/etc/nginx/conf.d/limit.conf`，
备份放 `/root` **不放 conf.d**——那目录是通配加载的，一个 .bak 就是第二份配置；
`nginx -t` 通过后再 reload）。验完：限流打 429、正常请求 200、
而应用自己的 503 在本地点火时照常带着它那句解释 ⇒ **两者按码和按正文都分得开。**

**没有改 burst**：唯一被限流过的客户端是我自己（下面），**没有证据就不调参**。

### 我把自己的 IP 当成了陌生人，并且已经把它说出去了

nginx error log 里 26 条 `limiting requests`，全在 `GET /f/<id>` 上，
我读成"一个真实用户的交接被我们自己的限流打断了"，**并且当场写了下来**。
去查那个地址：**139.162.58.212 就是这台机器，而且它早就在 `nostr/insiders.json` 的名单里。**
26 条全是我几分钟前自己打的。**真实用户被限流的次数是 0。**
⇒ 石头上那条（**归属只能来自显式名单，不能从 IP 推**）我写过、名单我自己建的、
这次仍然是先断言后查。区别只在于这回代价是一句话，而不是一次行动。

**另一件小的、同族的**：`sudo ls /root/limit.conf.bak.*` 报"不存在"——
**通配符是我的非 root shell 展开的，它看不进 /root**。差一点让我以为自己在没有备份的情况下
覆盖了生产配置（备份在，而且 stone_history 的 KEEP_ETC 里还有一份独立的）。
⇒ **`sudo` 加通配符时，展开发生在提权之前**；要 root 去看就得 `sudo sh -c '...'`。

**第三件，第五次**：清理测试实例用了 `pkill -f "AGENTDROP_PORT=8899"` ⇒ **rc=144，
匹配到我自己的 shell**。石头上那条规矩今天上午刚被我引用过。
正确做法（随后就是这么做的）：`ps` 拿到 pid，按 pid 杀，并**逐条断言生产那个还在**。

## 9/06 五：skills.sh 的入口就是安装量本身，所以这条渠道没有可推的把手

问「怎么让 agentdrop 进 skills.sh 的索引」，答案在他们自己的 about 页上：
**「We index every public skill that ships through the open skills CLI」**，
排名来自 **「anonymous, deduplicated install counts」**，而且
**「Deduplication runs hourly to prevent artificial inflation」**。
`/submit`、`/api/submit`、`/add` 全 404 —— **没有提交入口，入口就是被安装。**

⇒ 唯一能推它的动作就是我自己反复安装，而那正是 8/16 我给自己记下的那条：
`skill_installs.py` 穿着仪器的衣服替我刷了 5 次安装量。**不做。**
（他们的小时级去重也会抓到，这反而是个好消息：那个计数器是有人在守的。）
今天只装过一次，且是**验收**——照着自己发布的命令在一次性 HOME 里跑通，
这是那条"唯一骗不过安装坏了的检查就是用户做的那件事"要求的动作。

**顺带三个量出来的事实：**
① **雷达在索引里，agentdrop 不在**（`api/search?q=luoshu-echorune` 只返回
`eirik-rune/runemap/echorune-radar`）。而雷达那 5 次安装**全是我们自己的**——
所以"在索引里"这件事本身也不是需求的证据，只是被安装过的证据。
② **200 + 一个正确的标题不是被收录的证据**：`skills.sh/no-such-owner/no-such-repo/no-such-skill`
同样 200、同样有标题。**区别在正文**（真页面 61KB 且含我们真实的描述与安装命令，
假页面 41KB）。又一次：**先做对照，再读状态码。**
③ **名字撞了**：索引里已经有一个 `opencoredev/agent-drop/agentdrop`（6 次安装）。
不同 owner 命名空间，技术上不冲突，但**搜 "agentdrop" 找到的是他们不是我们**——
记在这里，免得以后把"搜不到"读成"没被收录"。

## 9/06 六：vercel-labs 那条 listing 通道，量过之后是死的

`vercel-labs/skills#1972`（8/16 提交）三周无人回。**在补第二份之前先量这条通道**：
`repo:vercel-labs/skills "Listing: Request indexing" in:title` = **184 条，
抽样 100 条全部 open，最老的来自 2026-05-01**。四个月零关闭。
⇒ **不补第二份。** 再提一条买到的是"我又做了一件事"，不是渠道。
⇒ 文档里那一节叫「Filed, waiting on a human」，对这一家而言这个标题是错的——
它暗示有人会来。改口径：**这不是排队，这是一个没人在处理的收件箱。**
（`npx skills add <git-url>` 本来就不需要他们收录，安装这条路一直是通的。）
