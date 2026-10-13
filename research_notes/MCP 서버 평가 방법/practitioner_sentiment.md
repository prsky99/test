# Practitioner Sentiment: How Developers and Agent Builders Evaluate and Choose MCP Servers (2025 to Oct 2026)

Access notes:
- **Reddit:** direct fetch of reddit.com was blocked ("unable to fetch from www.reddit.com"), and `site:reddit.com` searches returned no Reddit threads. I reached one r/mcp thread only through a third-party snapshot mirror (reddit.sentinel-team.org). Coverage of r/ClaudeAI, r/LocalLLaMA and r/AI_Agents is effectively **missing**.
- **X/Twitter:** not accessed directly, and no tweets surfaced in search. Coverage is **missing**.
- **Hacker News:** HN threads were fetched directly, but only relative dates ("12 months ago") were visible. Dates are approximate unless stated.
- **Evidence labels:** [DATA] marks a measured result, even from a small or vendor-run sample. [ANECDOTE] marks an individual opinion or experience. [VENDOR-CLAIM] marks a figure from a party selling a fix.

## Q1. What criteria do practitioners use to judge an MCP server?

### Takeaway
The criterion practitioners agree on most is context efficiency. They want few, workflow-shaped tools with small token footprints rather than 1:1 API-endpoint wrappers, plus clear names and parameter descriptions. Next come reliability and uptime of remote servers, correct auth (OAuth with minimal scopes), and trust/maintenance signals. Practitioners openly distrust GitHub stars and registry popularity as quality signals.

### Cited Findings
**Tool count and scope (the dominant criterion)**
- [ANECDOTE/guide] Phil Schmid recommends **5–15 tools per server**, "one server, one job". He also advises designing "for outcomes, not operations", flattening arguments into top-level primitives and `Literal` enums, a `{service}_{action}_{resource}` naming pattern, and pagination defaults of 20–50 with `has_more`/`next_offset`/`total_count`. He sums it up: "The protocol works fine. The servers don't." (Jan 21, 2026) — [philschmid.de](https://www.philschmid.de/mcp-best-practices)
- [ANECDOTE] HN user CharlieDigital advises against "slam[ming] 100 tools into your agent" and prefers a few flexible tools. HN jabber86 proposes a 3-tool pattern (list / get details / execute) to keep context small. (thread from ~Mar 2026) — [HN: MCP is dead; long live MCP](https://news.ycombinator.com/item?id=47380270)
- [ANECDOTE] HN user brookst: "well-documented big catalogs are possible; they're just rare". The suggestion is to group tools into 10–12 areas with actions inside each, e.g. one "file" tool instead of list/copy/rename tools. — [HN: I graded 36 popular MCP servers](https://news.ycombinator.com/item?id=49002358)
- [DATA, vendor's own product change] GitHub itself treats footprint as a quality metric. The Oct 29, 2025 changelog says it "continued to decrease the footprint of the GitHub MCP Server by consolidating more tools into fewer, more powerful tools". Consolidated tools take a `method` parameter, and server instructions were added. — [GitHub changelog](https://github.blog/changelog/2025-10-29-github-mcp-server-now-comes-with-server-instructions-better-tools-and-more). A related discussion moved Sub-issues, Orgs, PR Reviews, Releases and Discussions out of the default toolset — [github-mcp-server discussion #1182 (mirror)](https://gh.mise.run.place/github/github-mcp-server/discussions/1182)

**Description and schema clarity**
- [DATA, single author, self-run] The "mcpgrade" author graded 36 popular servers on description quality, schema design, naming, token cost and consistency. About a third got D or F, including official servers from MongoDB, Notion, GitHub and Airtable, mostly for missing parameter descriptions. That failure is said to cause hallucinated arguments or refusals. — [zeli.app summary of HN story](https://zeli.app/story/49002358); [mcpgrade on Glama](https://glama.ai/mcp/servers/jr9ma1v40s)
  - HN pushback: Hitton called rule D004 (parameter with no description) too strict for self-explanatory params like `url` ("stupid analysis"). crefiz and d1l dismissed the article as AI-written slop. — [HN](https://news.ycombinator.com/item?id=49002358)

**Value over plain tool call / CLI**
- [ANECDOTE] cheema33 (HN, ~Oct 2025): "About 95% of the MCP servers out there are useless and can be replaced with a simple tool call." dinkleberg agreed that "bad MCP servers can actively make things significantly worse", adding that many exist because product teams want "a quick way to say 'we're an AI product'". ojosilva named the high-value cases: custom internal MCPs for business APIs "that no model knows about", and centralized HTTP endpoints for teams. — [HN](https://news.ycombinator.com/item?id=45621078)
- [ANECDOTE] Per HN user clintonb, engineers had "few, if any, issues" with shared MCPs at their company, while designers and PMs had "numerous issues". CharlieDigital: "Server hosted MCP over streamable HTTP benefits orgs and teams and has virtually no benefit for individuals." — [HN](https://news.ycombinator.com/item?id=47380270)

**Auth and security**
- [ANECDOTE] HN DetroitThrow says "many popular MCPs have done auth incorrectly", so vet each server's auth. dtraub's preferred model: "The agent authenticates via OAuth/SSO, the server holds the downstream keys". tptacek: "Securing MCPs is an open problem. I'll take the CLI _every time_." — [HN](https://news.ycombinator.com/item?id=47380270)
- [VENDOR GUIDANCE] Block recommends OAuth with minimal scopes, tokens in the system keyring, and never plaintext secrets. Each tool should be either read-only or write/delete, never mixed, so users can judge risk, with `readOnlyHint`-style annotations to support approval decisions. (Jun 16, 2025) — [Block engineering](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers)

**Maintenance and trust signals**
- [ANECDOTE] r/mcp commenter (~Oct 2025): "Stars lie, last-commit dates can be misleading", since one cleanup commit makes an abandoned repo look alive. A server that installs cleanly clears a far lower bar than one that "does what the README claims and is actively maintained when upstream APIs change". The commenter calls the ecosystem a "weekend-project graveyard". Signals they trust more are npm weekly downloads ("Actual usage is harder to fake than star counts") and issue response rate. — [r/mcp thread via snapshot mirror](https://reddit.sentinel-team.org/posts/1sjovet/snapshots/2026-04-18T01%3A20%3A39.31167Z)
- [DATA, self-reported curation] The same commenter's curation removed ~1,164 of ~2,225 repos by automated cutoff (zero stars, no commits in 2+ years, no meaningful README), then manually reviewed borderline cases. — [same](https://reddit.sentinel-team.org/posts/1sjovet/snapshots/2026-04-18T01%3A20%3A39.31167Z)
- [ANECDOTE/guide] One MCP security write-up says there is "no sure-fire way" to know a server is safe. It suggests favoring public code with strong GitHub engagement and starting from the official servers list. — [MCPJam Substack](https://mcpjam.substack.com/p/lets-talk-about-mcp-security)

### Inferences
- Practitioner rubrics converge on a rough ordering: (1) does it beat a CLI or a direct API call for my use case; (2) tool count and token footprint; (3) clarity of names, descriptions and params; (4) reliability and latency of the hosted endpoint; (5) auth model and permission separation; (6) maintenance and real usage, not stars.
- "Official" is not treated as a quality guarantee. The mcpgrade results and the GitHub server's own consolidation show that official servers were also criticized for bloat and poor descriptions.

### Gaps
- No systematic survey of practitioners' selection criteria was found. All evidence is threads, blogs and vendor guidance.
- The specific Reddit communities requested (r/ClaudeAI, r/LocalLLaMA, r/AI_Agents) and X/Twitter could not be accessed.

## Q2. How do people test or evaluate MCP servers in practice?

### Takeaway
Serious builders follow the Anthropic-style loop: realistic multi-step tasks with verifiable answers, run programmatically by an agent, measured on accuracy, tool calls, tokens, runtime and errors, with transcripts read closely. A growing set of open-source eval harnesses implements this (often LLM-as-judge). Observability vendors add per-tool latency and error tracing. Casual users mostly try a server in their client and drop it if it misbehaves.

### Cited Findings
- [VENDOR GUIDANCE] Anthropic "Writing effective tools for agents — with agents" (Sep 11, 2025) — [Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents):
  - **Prototype:** wrap the tools in a local MCP server or DXT and try them in Claude Code or Claude Desktop.
  - **Eval tasks:** generate many realistic tasks grounded in real data, often needing dozens of tool calls, each with a verifiable outcome. Avoid over-strict verifiers. Expected tools may be recorded, but don't overfit to one strategy.
  - **Run:** run evals in a simple agent loop, and have agents output reasoning and feedback before tool calls.
  - **Metrics:** accuracy, runtime per tool call and per task, number of tool calls, total tokens, tool errors.
  - **Diagnostics:** frequent invalid-parameter errors point to unclear descriptions. Redundant calls point to pagination or limit issues.
  - **Iterate:** read full transcripts, paste them into Claude Code to refactor the tools, and use held-out test sets.
- [GUIDE] The mcp-builder evaluation guide judges a server on "how well its tool schemas and descriptions let an LLM answer realistic, multi-step questions", not on how many tools it implements. It recommends ~10 read-only questions with verifiable answers. — [mcp-builder evaluation.md (HF mirror)](https://huggingface.co/spaces/Luminia/README/blob/main/mcp-builder/reference/evaluation.md)
- [TOOLS] Open-source MCP eval harnesses found:
  - **lastmile-ai/mcp-eval:** real LLM calls the actual tools (no mocks); pytest, dataset and decorator styles; OpenTelemetry metrics. — [GitHub](https://github.com/lastmile-ai/mcp-eval)
  - **npm `mcp-evals`:** Node package plus GitHub Action that scores tool calls with an LLM. — [npm](https://www.npmjs.com/package/mcp-evals); Glama tutorial (May 1, 2025) — [Glama blog](https://glama.ai/blog/2025-05-01-mcp-evals)
  - **gleanwork/mcp-server-tester:** Playwright-based. Its "LLM host mode" tests whether names, descriptions and schemas are clear enough for autonomous use, a separate question from output correctness. — [GitHub](https://github.com/gleanwork/mcp-server-tester)
  - **deeppavlov/mcp-evals:** tasks defined as domain + goal + evaluator functions. — [GitHub](https://github.com/deeppavlov/mcp-evals)
  - **"MCP Server Evals" GitHub Action:** YAML test cases with LLM-as-judge; checks which tools were called with which args. — [GitHub Marketplace](https://github.com/marketplace/actions/mcp-server-evals)
  - **mcp-use + pydantic-eval** combination. — [Medium](https://medium.com/@varun.singh9786/testing-mcp-servers-mcp-eval-113ca6d9b85f)
- [TOOLS] Static linting and grading: mcpgrade scores description, schema, naming, token cost and consistency — [Glama](https://glama.ai/mcp/servers/jr9ma1v40s). "MCP Doctor" scores dimensions 0–100 from a repo path (as described in search results; not independently verified).
- [DATA] Practitioner A/B benchmarks: Scalekit (Mar 11, 2026) ran 75 runs with Claude Sonnet 4 on 5 read-only GitHub tasks, comparing CLI, CLI + Skills and MCP. It measured median tokens and success rate and tested significance at p<0.05 — [Scalekit](https://scalekit.com/blog/mcp-vs-cli-use). An academic "mcp-vs-cli-bench" (2026) tests the GitHub MCP server against a bare shell across 7 agent scaffolds and 5 models, verifying completion via repo state — [USAL listing](https://produccioncientifica.usal.es/documentos/6a776d7c5afd4024cfca2c42).
- [TOOLS] Observability:
  - **Langfuse:** links client and server traces by passing OpenTelemetry context in the MCP `_meta` field — [Langfuse docs](https://langfuse.com/docs/observability/features/mcp-tracing.md). Its mcp-use integration reports tool latency and errors — [Langfuse](https://langfuse.com/integrations/other/mcp-use).
  - **Sentry:** lists tool calls, errors, per-tool average and P95 latency, and linked traces as baseline signals — [Sentry](https://sentry.io/resources/mcp-observability/).
  - **Grafana:** a dashboard tracks per-tool invocation rates, latency percentiles and in-flight calls — [Grafana](https://grafana.com/grafana/dashboards/25252).
- [SECURITY TESTING] Invariant Labs' mcp-scan (Apr 11, 2025; Invariant acquired by Snyk June 2025, tool reportedly renamed Snyk Agent Scan). It auto-discovers configs from Claude Desktop, Cursor, Claude Code and others, checks for tool poisoning and prompt injection, and pins tool hashes to detect "rug pulls". Run with `uvx mcp-scan@latest`. Sourced from secondary blogs. — [appsecsanta](https://appsecsanta.com/mcp-scan); [mcpplaygroundonline](https://mcpplaygroundonline.com/blog/mcp-security-tool-poisoning-owasp-top-10-mcp-scan)

### Inferences
- Practitioner evaluation splits into three layers. (a) Static schema and description linting: mcpgrade, Inspector-style manual inspection. (b) Agentic task suites with LLM-as-judge or verifiable outcomes: mcp-eval, mcp-evals, Anthropic's method. (c) Production telemetry: Langfuse, Sentry, Grafana. Security scanning (mcp-scan) runs as a separate track.
- Anthropic's five metrics (accuracy, runtime, tool calls, tokens, errors) are the de facto metric set that later harnesses and benchmarks reuse.

### Gaps
- I found no first-hand practitioner discussion of **MCP Inspector** as an eval tool (beyond its well-known role as a manual debugger). No search result covered it.
- The term "golden tasks" did not surface in MCP-specific practitioner discussion.
- Arize/Phoenix MCP-specific tracing was not verified.
- How widely these harnesses are adopted (stars, downloads) was not measured.

## Q3. Common complaints and failure modes

### Takeaway
The most frequent complaints are context bloat from too many tools, API-mirroring servers that force multi-call chains, and missing or poor parameter descriptions. Other recurring ones: huge raw outputs, flaky or timing-out remote servers, broken auth, tool poisoning and supply-chain fears, and registries full of abandoned or gamed listings.

### Cited Findings
- **Context bloat:** [ANECDOTE] HN jswny: "MCP is context bloat", because all tools load immediately — [HN](https://news.ycombinator.com/item?id=47380270). A secondary source says Claude Code loads every connected server's full tool list, costing an estimated 10k–18k tokens per message with 3–4 servers — [MindStudio](https://www.mindstudio.ai/blog/claude-code-mcp-server-token-overhead).
- **API-mirroring and multi-call chains:** [DATA, qualitative] Block's Linear server v1 had 30+ tools mirroring GraphQL queries. "What issues is bob working on" took 4–6 chained calls. The final version uses 2 tools (`execute_readonly_query`, `execute_mutation_query`) and answers in 1 call. The Google Calendar v1 thin wrapper couldn't answer "How many meetings did I have last month?". v2 syncs to DuckDB behind a single `query_database` tool. (Jun 2025) — [Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers)
- **Huge outputs:** Claude Code caps tool responses at 25,000 tokens by default — [Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents). Goose's file reader rejects files over 400KB with an actionable message suggesting `sed` or `head` — [Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers). A 2-hour meeting transcript adds ~50k tokens because it passes through the model twice — [Anthropic code execution](https://www.anthropic.com/engineering/code-execution-with-mcp).
- **Flakiness:** [DATA, small n] In Scalekit's test, all 7 failed MCP runs (of 25) against GitHub's hosted Copilot MCP server were TCP `ConnectTimeout`, not protocol or tool errors — [Scalekit](https://scalekit.com/blog/mcp-vs-cli-use). [ANECDOTE] HN reports include an Atlassian MCP server failing repeated Jira ticket creation (the LLM mis-capitalized a project code) and Codex truncating MCP responses so images never arrive. A commenter said the "majority of my time has gone into trying to identify servers that work". These come from search-summarized HN threads, not fetched directly — [HN: Everything wrong with MCP](https://news.ycombinator.com/item?id=43676771); [HN: A critical look at MCP](https://news.ycombinator.com/item?id=43945993).
- **Bad-server examples:** [ANECDOTE] Figma was named "notoriously bad, by having the agent write javascript to communicate with the mcp" (sebazzz) — [HN](https://news.ycombinator.com/item?id=49002358). Contrast: gabrielpoca118 says Figma MCP let their team finish 3 weeks of work in an afternoon. When pressed, they compared it to no LLM; the LLM-without-MCP alternative was "at least 1 week" — [HN](https://news.ycombinator.com/item?id=45621078).
- **Security and tool poisoning:**
  - Invariant Labs named tool poisoning, tool shadowing and rug pulls on Apr 1, 2025. The attack hides instructions in tool descriptions, which enter context verbatim (secondary source) — [mcpplaygroundonline](https://mcpplaygroundonline.com/blog/mcp-security-tool-poisoning-owasp-top-10-mcp-scan).
  - An HN thread reports 21,000 exposed servers, 92% lacking OAuth (figure from the linked article, unverified) — [HN](https://news.ycombinator.com/item?id=49316815). Another covers MCP auth flaws enabling RCE in Claude Code and Gemini CLI — [HN](https://news.ycombinator.com/item?id=45348183). goalieca: "MCP servers seem to be a hackers delight" — [HN](https://news.ycombinator.com/item?id=45621078).
  - Simon Willison's "lethal trifecta" (private data + untrusted content + external communication, ~June 2025) is cited as why mixing MCP servers is risky: each server can supply one leg (secondary coverage) — [DZone](https://dzone.com/articles/mcp-lethal-trifecta).
  - Some HN commenters push back that the risk is about untrusted servers, comparable to pip/npm packages (search summary) — [HN](https://news.ycombinator.com/item?id=49316815).
- **Registry quality:**
  - A third-party analysis says the official MCP Registry has no official badge, download counts, reviews or maintainer reputation, though `updatedAt` can flag abandonment — [ncp registry analysis (Glama)](https://glama.ai/mcp/servers/@portel-dev/ncp/blob/290845e3bef09f59d08c3e58660d36de9fb0b3d8/docs/REGISTRY-SECURITY-ANALYSIS.md).
  - Nordic APIs flags popularity bias on mcp.so, and spam and ranking-gaming risk on MCP-Get — [Nordic APIs](https://nordicapis.com/7-mcp-registries-worth-checking-out/).
  - [VENDOR-CLAIM] MCP Index says it flagged ~396 listings (416 on another page) for farmed stars, bought downloads, borrowed repos and self-installing packages, and flags anything silent for 6 months as stale — [mcpservers.org listing](https://mcpservers.org/servers/themcpindex-com).
- **Protocol complaints:** a single request/response per call (no streaming partial data), servers interfering with each other, and harsh views of the spec (summarized from HN) — [HN: Everything wrong with MCP](https://news.ycombinator.com/item?id=43676771).

### Inferences
- Most complaints are about server design (tool sprawl, descriptions, output size), not the protocol. This matches Schmid's "The servers don't [work]" framing and Block's and Anthropic's guidance.
- Reliability complaints focus on hosted remote servers (timeouts) and auth, which also fuels the 2026 "just use a CLI" sentiment among individual developers.

### Gaps
- No quantified rate of tool-poisoning incidents in the wild was found. The "~85% attack success under adaptive attacks" figure (secondary, attributed to a Mar 2026 arXiv paper) was not verified.
- No data on how many registry entries are duplicates.

## Q4. Quantified anecdotes (token cost, accuracy vs tool count, ideal counts)

### Takeaway
Hard numbers mostly come from Anthropic and a few practitioner benchmarks. Tool definitions commonly cost tens of thousands of tokens per server (GitHub ~26k for 35 tools, Slack ~21k for 11 tools), multi-server setups hit 55k–134k+ tokens, and tool search or retrieval measurably improves selection accuracy. Recommended tool counts are opinion: ~5–15 per server.

### Cited Findings
- [DATA, Anthropic internal] Advanced tool use (Nov 24, 2025) — [Anthropic](https://www.anthropic.com/engineering/advanced-tool-use):
  - **Per-server definition cost:** GitHub 35 tools ≈26K tokens; Slack 11 tools ≈21K; Sentry 5 ≈3K; Grafana 5 ≈3K; Splunk 2 ≈2K; Jira ≈17K.
  - **Totals:** a 5-server/58-tool setup ≈55K tokens before the conversation starts. Anthropic observed a peak of 134K before optimization.
  - **Tool Search Tool:** ~500 tokens upfront, ~8.7K total vs ~77K, an 85% reduction. MCP-eval accuracy improved from 49%→74% (Opus 4) and 79.5%→88.1% (Opus 4.5).
  - **Tool Use Examples:** complex-parameter accuracy 72%→90%.
  - **Programmatic tool calling:** 43,588→27,297 tokens (−37%) on complex research tasks.
- [DATA, Anthropic] Code execution with MCP (Nov 4, 2025): an example workflow dropped from 150,000 to 2,000 tokens (98.7%). A 10,000-row spreadsheet filtered in code shows the model only 5 rows — [Anthropic](https://www.anthropic.com/engineering/code-execution-with-mcp).
- [DATA] Anthropic: a `response_format` concise mode used about 1/3 of the tokens of detailed mode in its example — [Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents).
- [DATA, small n] Scalekit (Mar 11, 2026) — [Scalekit](https://scalekit.com/blog/mcp-vs-cli-use):
  - **Setup:** GitHub's official MCP server injects 43 tool schemas. Median tokens per task, CLI vs MCP: 1,365 vs 44,026 (32×); 1,648 vs 32,279 (20×); 9,386 vs 82,835 (9×); 5,010 vs 33,712 (7×); 8,750 vs 37,402 (4×).
  - **Success:** CLI 25/25, MCP 18/25.
  - **Caveats:** the intro claims "10–32×" while the table shows 4–32×. Cost projections ($3.20 vs $55.20 per 10k ops/month) are estimates.
  - **Conflicting figures:** a secondary summary gives 1,265 vs 54,035 for the simplest task — [MindStudio](https://www.mindstudio.ai/blog/mcp-servers-35x-more-tokens-cli-tools-reliability-benchmark). Prefer the Scalekit primary numbers. One search summary says a later replication (Blotato) found the token gap largely disappeared and attributed it to the client, but I could not verify this — [Blotato](https://www.blotato.com/blog/mcp-vs-rest-api-token-cost).
- [DATA, academic] RAG-MCP (arXiv 2505.03275, May 2025): retrieving tool schemas instead of loading all of them cut prompt tokens by >50% and raised tool-selection accuracy from 13.62% to 43.13% in an MCP stress test. The test is a needle-in-a-haystack setup with N distractor schemas. Accuracy reportedly degrades as the pool grows. — [arXiv](https://arxiv.org/html/2505.03275v1)
- [VENDOR-CLAIM / secondary] A deployment with GitHub + Slack + Sentry reportedly used 143K of a 200K context on tool schemas. A "93-tool GitHub MCP server ≈55K tokens" figure also circulates. Typical estimates: 100–500 tokens per tool definition; 5 servers × 30 tools = 30K–60K tokens. — [layered.dev](https://layered.dev/mcp-tool-schema-bloat-the-hidden-token-tax-and-how-to-fix-it/); [mcp.directory](https://mcp.directory/blog/mcp-context-bloat-fix-2026-tool-search-code-mode-progressive-disclosure); [Medium](https://medium.com/@lakshminp/your-mcp-servers-are-eating-your-context-549c472beaf2)
- [VENDOR-CLAIM] Cloudflare's full API (2,500+ endpoints) as MCP tools would be ~1.17M tokens. Code Mode collapses it to 2 tools (search/execute) at ~1,000 tokens (as reported by secondary source mcp.directory) — [mcp.directory](https://mcp.directory/blog/mcp-context-bloat-fix-2026-tool-search-code-mode-progressive-disclosure). The original Cloudflare Code Mode post (Sep 26, 2025) argues LLMs write code better than they make tool calls, but presents **no benchmark numbers** — [Cloudflare](https://blog.cloudflare.com/code-mode/).
- [VENDOR-CLAIM] HN algis-hn cites a "44K token cold-start cost" and says BM25 routing can expose only 3–5 relevant schemas per query — [HN](https://news.ycombinator.com/item?id=47380270). MCP Coordinator gateway claims ~15K→~500 tokens — [Glama](https://glama.ai/mcp/servers/@CyberClash/mcp_coordinator/blob/e76cc7692c999031e93b62d23a7f741894192511/README.md).
- [DATA, small] A browser-debugging CLI vs Chrome DevTools MCP on 5 workflows: the CLI scored 77 vs 60 with ~33% fewer tokens, while MCP was 27% faster (secondary summary) — [Mintlify docs](https://www.mintlify.com/szymdzum/browser-debugger-cli/agents/benchmarks).
- [DATA, project-reported] The Gitea MCP server consolidated 110→45 tools following the GitHub "method dispatch" pattern — [gitea-mcp](https://gitea.com/Mutex/gitea-mcp).
- [UNVERIFIED claim] "Tool selection accuracy drops threefold with bloated toolsets" — [Albato](https://albato.com/blog/publications/embedded-mcp-context-bloat-hallucinations). No study cited; treat as unsupported.
- **Ideal tool counts (opinion):** 5–15 per server ([Schmid](https://www.philschmid.de/mcp-best-practices)); 10–12 grouped areas for large catalogs (HN brookst, [HN](https://news.ycombinator.com/item?id=49002358)); 2 tools for Linear ([Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers)); 3-tool list/get/execute pattern (HN jabber86, [HN](https://news.ycombinator.com/item?id=47380270)). GitHub's dynamic toolsets mode reportedly starts with 4 tools and enables more on demand (newsletter) — [Main Branch newsletter](https://mainbranch.beehiiv.com/p/main-branch-the-one-where-it-s-not-an-api-issue-4).

### Inferences
- A practical eval heuristic emerges: measure the server's tool-definition token cost at connection (as tokens per tool and in total) and compare it with the 25K-token response cap and the context budget. Servers over roughly 15–20K tokens of definitions, like GitHub and Slack in Anthropic's data, are the ones practitioners complain about.
- Since Tool Search / deferred loading (Claude Code, late 2025 to early 2026), raw tool count matters less on modern clients. Description quality still matters, because search retrieves on names and descriptions.

### Gaps
- No controlled public study was found that sweeps tool count (e.g. 10/50/100) against accuracy on frontier models besides RAG-MCP's stress test. The full RAG-MCP accuracy-by-N table was not retrieved.
- Latency numbers per MCP server were not found in practitioner discussion.

## Q5. Vendor guidance on writing good MCP tools that implies evaluation criteria

### Takeaway
Anthropic, Block, Cloudflare and GitHub's own changes point the same way. Design around workflows, not endpoints. Consolidate and namespace tools. Return concise, human-meaningful, paginated output. Write descriptions like onboarding docs. Separate read and write risk. Evaluate with agentic task suites. Each principle doubles as a checklist item for judging third-party servers.

### Cited Findings
- **Anthropic** (Sep 11, 2025) — [Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents):
  - Don't mirror API endpoints; avoid overlapping tools.
  - Consolidate (e.g. `schedule_event`, `search_logs`, `get_customer_context`).
  - Namespace by service and resource (e.g. `asana_projects_search`). Prefix vs suffix choice affects results, so test it.
  - Return natural-language names over UUIDs, and offer a `response_format` concise/detailed option.
  - Paginate, filter and truncate with sensible defaults; give actionable errors.
  - Write descriptions "as you would to a new hire", with unambiguous params (`user_id`, not `user`). Refining descriptions alone improved Claude Sonnet 3.5 on SWE-bench Verified.
  - Use annotations for open-world and destructive tools.
- **Anthropic** (Nov 2025): code execution and progressive disclosure address definition overload and intermediate-result bloat — [Anthropic code execution](https://www.anthropic.com/engineering/code-execution-with-mcp). Tool Search, Tool Use Examples and programmatic calling — [Anthropic advanced tool use](https://www.anthropic.com/engineering/advanced-tool-use).
- **Block** (Jun 16, 2025, 60+ internal MCP servers) — [Block](https://engineering.block.xyz/blog/blocks-playbook-for-designing-mcp-servers):
  - Design top-down from workflows, and treat tool names and params as prompts.
  - Manage the token budget: check output sizes, then error, truncate with a note, or paginate.
  - Preserve prompt prefix caching by not injecting live data like timestamps.
  - Play to LLM strengths (SQL, text diagrams) and avoid long tool chains or strict JSON output.
  - Use OAuth with minimal scopes and the keyring; add server instructions and annotations; separate read-only from write/delete tools.
- **Cloudflare** (Sep 26, 2025): models write code better than they make tool calls, and large or complex tool sets reduce reliability, which pushes servers toward oversimplified APIs. Code Mode turns the schema into a typed TypeScript API. Implied criterion: documentation and type quality of the underlying API. No benchmarks given. — [Cloudflare](https://blog.cloudflare.com/code-mode/)
- **GitHub** (Oct 29, 2025): consolidated tools with a method parameter, server instructions, and fewer default toolsets. "Footprint" is an explicit quality target — [GitHub changelog](https://github.blog/changelog/2025-10-29-github-mcp-server-now-comes-with-server-instructions-better-tools-and-more).
- **Other practitioner and vendor guides:** Bump.sh blames problems on too many tools, verbose descriptions, oversized payloads and treating MCP like an API — [Bump.sh](https://bump.sh/blog/4-rules-to-build-an-efficient-mcp-server). Workato's field guide is drawn from 25+ enterprise MCP servers: "built for the model doing the reasoning" — [Workato PDF](https://workato.com/the-connector/wp-content/uploads/2026/04/How-We-MCP-Series.pdf).

### Inferences
- A practitioner checklist built from vendor guidance could cover:
  - tool count and overlap
  - namespacing
  - description and param completeness
  - definition token cost
  - default response size and pagination
  - actionable errors
  - read/write separation and annotations
  - auth scopes
  - cache-friendliness, i.e. no dynamic data in definitions
- Measure it with an agentic task suite on Anthropic's 5 metrics.
- **OpenAI caveat:** guidance here is under-sourced. I found no OpenAI-specific "writing tools for agents" MCP guidance in this pass.

### Gaps
- OpenAI's guidance on MCP tool design (e.g., Apps SDK / Agents SDK docs) was not retrieved.
- The Block "goose" blog's other MCP posts and Block's later (2026) updates were not reviewed.
- Primary Invariant Labs/Snyk posts were not fetched; security details rely on secondary sources.
