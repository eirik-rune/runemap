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
