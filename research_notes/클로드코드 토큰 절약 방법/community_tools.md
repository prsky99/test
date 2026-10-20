# Community tools, skills, plugins, hooks and MCP servers for cutting tokens and context bloat in Claude Code (as of 2026-10-20)

Note on star counts: unless marked otherwise, star counts come from the GitHub repository search API, read on 2026-10-20 (the research date). Stars show attention, not quality. Several reviewers say outright that viral star counts are a marketing metric ([andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)).

Catalog summary (stars on 2026-10-20, from GitHub search):

| Tool | Category | Stars | Mechanism | Savings claim (who measured) |
|---|---|---|---|---|
| JuliusBrussee/caveman | Output-style skill/plugin (+ proxy) | 113,855 | Terse "caveman" replies; caveman-compress rewrites CLAUDE.md | 65% output (vendor); about 3% vs "Answer concisely." baseline (vendor's current README); 5-15% of bill (reviewer estimate) |
| drona23/claude-token-efficient | CLAUDE.md drop-in | 6,102 | Terse-response rules | none found |
| rtk-ai/rtk | Bash-output filter via PreToolUse hook | 84,087 | Rewrites `git status` → `rtk git status`, filters, groups, dedupes | 60-90% (vendor); 49.6% over 1,456 cmds (Soba Labs) |
| headroomlabs-ai/headroom | Local compression proxy/library/MCP | 76,735 | Content-type-aware compression of tool outputs; reversible cache | 20% coding agents, 60-95% JSON (vendor benchmarks, N=100 evals) |
| mksglu/context-mode | MCP + hooks plugin | 31,351 | Runs tools in sandbox, only stdout/indexed snippets enter context; PreCompact snapshot | "315 KB → 5.4 KB, 98%" (vendor) |
| colbymchenry/codegraph | Code knowledge graph MCP | 74,538 | tree-sitter + SQLite symbol/call graph | −57% tokens, −35% cost median over 7 repos x 4 runs (vendor) |
| tirth8205/code-review-graph | Code graph MCP/CLI | 32,285 | tree-sitter graph → minimal file set | 6.8x reviews, 49x best case (author); 8.2x avg, 49x "cherry-picked" (DEV reviewer) |
| oraios/serena | LSP-based semantic retrieval/edit MCP | 30,501 | Symbol-level reads/edits instead of whole files | only anecdotal / unverified "~70%" |
| zilliztech/claude-context | Semantic code search MCP | 12,632 | AST chunking + hybrid BM25/vector (Milvus) | ~40% at equal retrieval quality (vendor) |
| thedotmack/claude-mem | Memory plugin | 101,956 | Captures sessions, AI-compresses, re-injects relevant context | no verified number found |
| alexgreensh/token-optimizer | Audit + compression skill/plugin | 2,608 | Ghost-token finder, structure maps, compaction checkpoints | 95-99% on structure maps, $1.5-2.5k/month (self-reported) |
| ccusage/ccusage | Usage reporting CLI | 19,095 | Parses local JSONL transcripts | n/a (meter) |
| Maciek-roboblog/Claude-Code-Usage-Monitor | Real-time limit monitor | 8,751 | Burn rate + P90 limit prediction | n/a |
| sirmalloc/ccstatusline | Statusline | 13,352 | Customizable status line | n/a |
| voicetreelab/lazy-mcp | MCP lazy-loading proxy | 114 | On-demand tool activation | none; mostly made redundant by built-in Tool Search |

## Q1. Which skills or plugins focus on token efficiency (terse output, handoff, compression, memory)?

### Takeaway
The best-known token-efficiency skill is caveman (about 114k stars). Its own current benchmark shows only about 3% extra output savings over a plain "Answer concisely." instruction, and output is a small share of a Claude Code bill, so the real-world effect is modest. Handoff-then-/clear skills and memory plugins (claude-mem, context-mode's session snapshots) target re-reading and compaction cost instead. None has an independent benchmark.

### Cited Findings
**caveman (JuliusBrussee/caveman)**
- Stars: 113,855 on 2026-10-20. Description: "Viral skill + proxy for coding agents that cuts 65% of tokens by talking like a caveman." Created 2026-04-04 — [GitHub search API](https://github.com/JuliusBrussee/caveman)
- Mechanism: tells the model to drop articles, pleasantries and filler. Code blocks, quoted errors and technical terms stay unchanged. Detects 30+ agents (Claude Code, Codex, Cursor, Windsurf, Cline, Aider) — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code)
- Levels: lite, full and ultra, plus "Wenyan" (classical Chinese, about 80%). Drops caveman mode automatically for security warnings, confirmations of irreversible actions and multi-step sequences — [Pasquale Pillitteri](https://pasqualepillitteri.it/en/news/846/claude-code-caveman-mode-token-saving)
- Claims over time. The original vendor benchmark (10 prompts, `benchmarks/` scripts) showed a 65% mean output reduction, range 22-87%. An earlier "75%" headline was retired in v1.9.1. The current README tests 10 developer questions on claude-opus-5-5 against an "Answer concisely." baseline: `/caveman` cuts only about 3% more output at the median, `/ultracave` about 35% more — [andrew.ooo review, dated 2026-05-05, re-checked 2026-10-20](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)
- Input side: the vendor claims 33.2% fewer input tokens per session. `caveman-compress` rewrites CLAUDE.md-style files for about 46% fewer input tokens and keeps a `<file>.original.md` backup. Because Claude Code re-injects CLAUDE.md every session, that saving recurs each session. `caveman-shrink` is MCP middleware that compresses tool, prompt and resource descriptions (metadata only in v1) — [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)
- Community tests:
  - A Reddit "Caveman vs 'be brief'" test (24 prompts, 5 arms) found a one-line "be brief" instruction captured most of the savings.
  - A hand-written 6-line prompt beat the full skill on quality versus tokens.
  - An r/ClaudeCode thread reported 30-50% real-world output savings.
  - The reviewer's estimate: output is about 10-30% of a Claude Code bill, so the bill falls about 5-15%.
  
  Source: [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)
- Another reviewer estimates whole-session savings at only 4-5%, or 8-10% when combined with memory-file compression — summarized in search results for [Pasquale Pillitteri / utsavworks coverage](https://pasqualepillitteri.it/en/news/846/claude-code-caveman-mode-token-saving). I could not confirm which of these pages the 4-5% figure comes from.
- Criticisms:
  - Ultra mode can drop caveats and edge cases.
  - Codex drifts back to verbose output, and Cursor is inconsistent.
  - Terse output is harder for juniors to learn from.
  - v4.0 (2026-10-13) made `@caveman-ai/cli` the recommended install, with telemetry on by default (`caveman telemetry off` or `DO_NOT_TRACK=1`).
  - Relicensed to Apache-2.0 in v3.0.0 (2026-09-30).
  
  Source: [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)
- The "most polarising" of the cost-cutters; output "reads weird at first"; affects output only — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code)
- Install: `claude plugin marketplace add JuliusBrussee/caveman` then `claude plugin install caveman@caveman`, or `npx skills add JuliusBrussee/caveman -g` (Node 22.13+ for the CLI) — [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)
- Related brevity research: an arXiv preprint (2604.00025, March 2026) argues brevity constraints can improve accuracy by up to 26 percentage points on some benchmarks. It is still a preprint — [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)

**Other terse-output / CLAUDE.md drop-ins**
- drona23/claude-token-efficient: "One CLAUDE.md file. Keeps Claude responses terse." 6,102 stars — [GitHub](https://github.com/drona23/claude-token-efficient)
- alexgreensh/attention-span: "ADHD-friendly output styles… pay attention, not tokens," 1,480 stars, created 2026-08 — [GitHub](https://github.com/alexgreensh/attention-span)

**Handoff / session-summary skills (alternatives to /compact)**
- simplybychris/handoff-skill: `/handoff` writes a markdown note to `session-logs/` early, at about 50-60% context. You then `/clear`, and `/pickup` reads only the newest note and checks repo state — [GitHub](https://github.com/simplybychris/handoff-skill)
- thepushkarp/handoff: a PreCompact hook writes `docs/handoff/HANDOFF.md`, and a SessionStart (matcher `compact`) hook re-injects the latest entry — [GitHub](https://github.com/thepushkarp/handoff)
- samzilverberg/claude-handoff: stages a handoff at end of turn when context crosses a threshold. You type `/clear` (no auto-clear unless T3_AUTOCLEAR), then `/handoff:resume` — [GitHub](https://github.com/samzilverberg/claude-handoff)
- REMvisual/claude-handoff: a `/compact-handoff` mod that replaces the conversation with a validated handoff, like /compact but with your own summary — [GitHub](https://github.com/REMvisual/claude-handoff)
- Anthropic's own guidance contrasts `/clear` (new session, usually with a brief you've distilled) with compacting (summarize and continue) — [Claude blog](https://claude.com/blog/using-claude-code-session-management-and-1m-context)
- Critique: AI Hero argues a handoff mostly helps portability (new harness, directory or colleague), and that /compact covers ordinary end-of-phase cases — [AI Hero](https://www.aihero.dev/skills-handoff). An HN commenter prefers handoffs because the context ends up portable — [HN](https://news.ycombinator.com/item?id=49300800)

**Memory / knowledge-base plugins (avoid re-reading files)**
- thedotmack/claude-mem: "Captures everything your agent does during sessions, compresses it with AI, and injects relevant context back into future sessions." 101,956 stars; uses ChromaDB/SQLite per topics — [GitHub](https://github.com/thedotmack/claude-mem)
- cytostack/openwolf: portable project memory plus "token accounting measured from harness transcripts," 2,395 stars — [GitHub](https://github.com/cytostack/openwolf)
- lucasrosati/claude-code-memory-setup: Obsidian + Graphify, claims "up to 71.5x fewer tokens per session" (self-claimed), 1,038 stars — [GitHub](https://github.com/lucasrosati/claude-code-memory-setup)
- alexgreensh/token-optimizer (2,608 stars) — [GitHub](https://github.com/alexgreensh/token-optimizer). Per Tokenade's review it includes:
  - AST structure maps
  - session-continuity checkpoints
  - 16 bash output handlers
  - Coach mode with 11 waste detectors
  - an HTML dashboard
  
  It claims 95-99% compression on structure maps and "$1,500-$2,500/month" savings over 942 sessions (self-reported, not reproducible). License is PolyForm Noncommercial; needs Python 3.9+ — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)

### Inferences
- For output tokens, a one-line "be concise" instruction in CLAUDE.md captures most of what caveman offers. caveman-compress, which shrinks CLAUDE.md input that is re-sent every session, may be the more durable saving.
- Handoff skills are mostly workflow conventions (hooks + markdown). Their benefit is control over what survives a reset, not a measured token number.

### Gaps
- No independent, controlled benchmark found for claude-mem, the handoff skills or openwolf.
- I could not pin the exact source of the 4-5% whole-session caveman estimate.

## Q2. Usage-monitoring tools and how people use them to avoid limits

### Takeaway
ccusage (now `ccusage/ccusage`, rewritten in Rust, about 19k stars) is the standard meter. Claude-Code-Usage-Monitor adds live burn-rate and limit prediction, and statuslines such as ccstatusline keep usage visible all the time. These tools save nothing themselves. They tell you when to /clear, switch models or stop.

### Cited Findings
- ccusage: repo is now `ccusage/ccusage` (description "npx ccusage"), primary language Rust, 19,095 stars on 2026-10-20 — [GitHub](https://github.com/ccusage/ccusage)
- ccusage reads local Claude Code JSONL transcripts and produces daily, weekly, monthly and session reports with cache breakdowns. Supports 15 agent environments; MIT. "Only a meter; it lowers no spend by itself." The review put it at about 15k stars as of 2026-06-02 — [Tokenade review](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- Maciek-roboblog/Claude-Code-Usage-Monitor (8,751 stars): live progress bars and burn-rate analysis. It predicts when you'll hit the session limit from a 90th-percentile analysis of the last 8 days and auto-detects your plan — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code); stars from [GitHub](https://github.com/Maciek-roboblog/Claude-Code-Usage-Monitor)
- phuryn/claude-usage (2,275 stars): localhost:8080 dashboard (Python stdlib only, Chart.js) that refreshes every 30s and shows a plan-limit progress bar for Pro/Max — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code)
- Other trackers found via GitHub search (2026-10-20): getagentseal/codeburn 11,534 stars ("track AI coding token usage and cost across 37 tools… by model, project, and task"), kenn-io/agentsview 6,215, matt1398/claude-devtools 3,990 ("inspect session logs, tool calls, token usage, subagents, and context window"), graykode/abtop 3,756 ("htop for AI coding agents… tokens, context window, rate limits"), Javis603/token-monitor 3,224, xiufengsun/TokenTracker 2,098 — [GitHub search](https://github.com/getagentseal/codeburn)
- Statuslines: sirmalloc/ccstatusline 13,352 stars and Owloops/claude-powerline 1,173 stars — [GitHub](https://github.com/sirmalloc/ccstatusline), [GitHub](https://github.com/Owloops/claude-powerline)
- DeployHQ's view: for Pro users the gain from these tools is mainly longer sessions, not lower cost. Its "$100+/month" saving figure for Max users comes with no methodology — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code)

### Inferences
- The usual pattern is to watch context % in the statusline and burn rate in a monitor, then /clear or hand off before auto-compaction or limits hit. The tools inform these decisions but don't make them.

### Gaps
- I did not verify which ccstatusline widgets show context-window % (the repo description only says "highly customizable").
- No survey data found on how widely these monitors are used beyond star counts.

## Q3. Hooks and tools that shrink tool output or replace whole-file reads (output filters, code search/index MCPs, repo maps)

### Takeaway
The most-adopted approach is RTK (about 84k stars), a PreToolUse hook that filters Bash output. One team measured 49.6% savings on routed commands, but RTK misses Claude's built-in Read, Grep and Glob. Broader layers include Headroom (proxy compression), context-mode (sandboxed execution) and code-graph MCPs (codegraph, code-review-graph, Serena, claude-context). Nearly all published savings numbers are self-reported, and the one competitive benchmark (THOL) was published by a competing tool's author.

### Cited Findings
**RTK — Rust Token Killer (rtk-ai/rtk)**
- 84,087 stars; "CLI proxy that reduces LLM token consumption by 60-90% on common dev commands. Single Rust binary, zero dependencies" — [GitHub](https://github.com/rtk-ai/rtk)
- `rtk init -g` installs a PreToolUse hook that rewrites Bash commands, for example `git status` → `rtk git status`. Filtering strategies: smart filtering, grouping, truncation and deduplication. Falls back to raw output on filter failure and saves the full log via tee. `rtk gain` reports cumulative savings. On native Windows there's no auto-rewrite hook (CLAUDE.md fallback instead) — [search summary of RTK sources incl. rtk-ai.app, dev.to](https://dev.to/arshtechpro/how-rtk-reduces-llm-token-usage-for-ai-coding-agents-2kfd)
- Vendor examples: `cargo test` 155 lines → 3; `npm install` about 4,000 lines → about 15 — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code)
- Independent measurement by Soba Labs (2026-07-13, a few weeks of daily use on their own machines):
  - 1,456 commands, 1.3M → about 645K input tokens, so 49.6% saved
  - under 800 ms average overhead
  - file reads saved the most in absolute terms (333.7K)
  - `git log` with patches filtered 98.4%
  - grep was the most frequent command (444 calls) at 20.9% per call
  - `rtk discover` over 2,229 sessions and 37,238 commands estimated 4.3M more tokens missed by commands that bypassed the hook
  
  Source: [Soba Labs](https://sobalabs.ai/blog/halving-claude-code-token-usage-with-rtk/)
- Soba Labs caveats:
  - Token savings ≠ cost savings because of prompt caching.
  - Filtering is lossy (`rtk proxy` gives raw output).
  - Only Bash is intercepted.
  - The Codex integration is best-effort via AGENTS.md.
  - The README's 60-90% figures are project estimates, and independent evidence is thin.
  
  Source: [Soba Labs](https://sobalabs.ai/blog/halving-claude-code-token-usage-with-rtk/)
- In Tokenade's THOL benchmark, RTK showed "no measurable saving." Tokenade's author wrote the benchmark and ranks his own tool #1, which is a conflict of interest — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)

**Headroom (headroomlabs-ai/headroom)**
- 76,735 stars; Apache-2.0. "Compress tool outputs, logs, files, and RAG chunks before they reach the LLM. 20% fewer tokens for coding agents, 60-95% fewer tokens for JSON, same answers." — [GitHub](https://github.com/headroomlabs-ai/headroom)
- Forms: library, local proxy, `headroom wrap claude` (routes Claude Code through the proxy; also installs Serena by default) and an MCP server (`headroom_compress`, `headroom_retrieve`, `headroom_stats`). It routes content by type to SmartCrusher (JSON), an AST CodeCompressor, or a HuggingFace "Kompress-v2-base" model for prose. Originals are cached locally (CCR) for retrieval. CacheAligner and "live-zone" compression aim to keep the prompt-cache prefix byte-identical — [GitHub README](https://github.com/headroomlabs-ai/headroom)
- Vendor proof table (offline, seeded): code search 21%, SRE debugging 57%, codebase exploration 42%, issue triage 30%. Accuracy evals at N=100: GSM8K unchanged at 0.870; SQuAD v2 and BFCL retained 97%. Prose and dense output barely compress. Telemetry beacon on by default (`HEADROOM_TELEMETRY=off` / `DO_NOT_TRACK=1`) — [GitHub README](https://github.com/headroomlabs-ai/headroom)
- Related: gglucass/headroom-desktop menu-bar app claims about 50% cuts (615 stars) — [GitHub](https://github.com/gglucass/headroom-desktop)

**context-mode (mksglu/context-mode)**
- 31,351 stars; "Sandboxes tool output (98% reduction), persists session memory, and enforces routing across 17 platforms via MCP + hooks." — [GitHub](https://github.com/mksglu/context-mode)
- Mechanism:
  - `ctx_execute` runs code in a subprocess, and only stdout enters context.
  - For output over 5 KB with an intent, the full output is indexed in SQLite FTS5 (BM25 + trigram, RRF) and only matching sections are returned.
  - A PreCompact hook builds a session snapshot of about 2 KB, and SessionStart restores it.
  
  Vendor examples: 315 KB → 5.4 KB; 47 file reads (about 700 KB) vs one script (about 3.6 KB). Measurement method not stated on the README (refers to BENCHMARK.md). Install: `/plugin marketplace add mksglu/context-mode` → `/plugin install context-mode@context-mode`. Requires Node 22.5+ on Linux. License shows ELv2. Instruction-file-only platforms reach about 60% compliance — [GitHub README](https://github.com/mksglu/context-mode)

**Code-index / graph / semantic-search MCPs**
- colbymchenry/codegraph: 74,538 stars; "Pre-indexed code knowledge graph… fewer tokens, fewer tool calls, 100% local" — [GitHub](https://github.com/colbymchenry/codegraph)
  - Mechanism: SQLite + FTS5 graph built from tree-sitter, 20+ languages.
  - Claims: median −35% cost, −57% tokens and −71% tool calls across 7 repos (4 runs each), advertised by the project with documented methodology.
  - Reviewer caution: only 4 runs per repo, and the gains are navigation-only.
  
  Source: [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- tirth8205/code-review-graph: 32,285 stars — [GitHub](https://github.com/tirth8205/code-review-graph)
  - Author claims: 6.8x fewer tokens on reviews (6 commits), 49x on a Next.js monorepo, and about 63x median per question on 6 repos (358x max). Quality scored +1.6 on a subjective 1-10 rubric by the author.
  - A DEV skeptic found an 8.2x average, 3.7x on FastAPI and 4.6x on httpx, and called 49x a cherry-picked best case. No independent benchmark found.
  
  Sources: [DEV Community](https://dev.to/emperorakashi20/how-code-review-graph-cuts-claude-code-token-usage-by-49x-and-whether-its-actually-worth-it-4kn1), [HN](https://news.ycombinator.com/item?id=47314090). The initial build takes about 10 s for 500 files — [DeployHQ](https://www.deployhq.com/blog/free-github-repos-for-claude-code)
- oraios/serena: 30,501 stars; "semantic retrieval and editing capabilities - the IDE for your agent" (LSP-based) — [GitHub](https://github.com/oraios/serena)
  - Users report fewer tokens for edits and code walks, which let one user "stay on Opus longer" — [Serena discussion #545](https://github.com/oraios/serena/discussions/545)
  - Onboarding costs a lot of tokens up front — [clien.net](https://www.clien.net/service/board/cm_ai/19073472)
  - Setup friction reported — [Classmethod](https://dev.classmethod.jp/articles/20250804-story-about-how-i-got-stuck-trying-to-add-serena-to-mcp-with-claude/)
  - No measured benchmark found; a "~70%" figure is from an unverified vendor-style guide.
- zilliztech/claude-context: 12,632 stars — [GitHub](https://github.com/zilliztech/claude-context)
  - Mechanism: AST chunking, hybrid BM25 + vector search, Merkle-tree incremental indexing.
  - Claim: "~40% token reduction under the condition of equivalent retrieval quality" (self-reported).
  - Needs Milvus/Zilliz Cloud and an embedding API key unless you use Ollama.
  
  Source: [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- aovestdipaperino/tokensave (672 stars): Rust call-graph MCP. Its `tokensave bench` reports 88% retrieval savings (142.8k → 5.5k tokens over 10 queries) on its own repo — self-measured, not a paired session test — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- Other code-retrieval MCPs with big self-claims (GitHub, 2026-10-20):
  - jgravelle/jcodemunch-mcp: 2,790 stars; "Cut AI token costs 95%+ on code exploration"
  - Mibayy/token-savior: 1,183 stars; claims 97.9% vs 78.3% on "a real coding benchmark at -80% active tokens"
  - Houseofmvps/codesight: 1,420 stars; repo-map context generator
  
  Source: [GitHub search](https://github.com/jgravelle/jcodemunch-mcp)
- yamadashy/repomix (28,936 stars) packs a whole repo into one AI-friendly file. It suits one-shot context loading and is the opposite of selective retrieval — [GitHub](https://github.com/yamadashy/repomix)

**Other compression tools**
- pi-infected/tokenade: only 10 stars, created 2026-10-18; npm only. Combines command rewriting, output filtering, semantic search and MCP output optimization. Claims "39% cheaper on long sessions" on THOL, its author's own benchmark — [GitHub](https://github.com/pi-infected/tokenade), [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- squeez (Rust, Apache-2.0): dedupes and compacts shell output and file reads. No measurable saving in THOL — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- teamchong/pxpipe (7,539 stars, created 2026-05): "cut Claude Code token usage by rendering text context as images" — [GitHub](https://github.com/teamchong/pxpipe)
- Paritok-official/paritok-4b-v1 (1,460 stars): compression gateway using a 4B model. Claims 25% on turn 1, rising past 85% in long sessions (self-claimed) — [GitHub](https://github.com/Paritok-official/paritok-4b-v1)
- Gateways that bundle RTK and caveman: diegosouzapw/OmniRoute (78,962 stars; "RTK+Caveman compression saves 15-95% tokens") and decolua/9router (31,125 stars; "RTK -40% tokens"). Both mainly route to free or third-party model providers — [GitHub](https://github.com/diegosouzapw/OmniRoute), [GitHub](https://github.com/decolua/9router)
- Hook collections: disler/claude-code-hooks-mastery 3,945 stars; karanb192/claude-code-hooks 547 stars ("safety, cost, observability, productivity") — [GitHub](https://github.com/disler/claude-code-hooks-mastery), [GitHub](https://github.com/karanb192/claude-code-hooks)
- Built-in safeguard (Anthropic docs):
  - Claude Code warns when MCP tool output exceeds 10,000 tokens.
  - The default limit is 25,000 tokens (`MAX_MCP_OUTPUT_TOKENS`).
  - Larger results are saved to a file in `tool-results/` and referenced by path.
  - Text over 50,000 chars is always offloaded to a file.
  
  Source: [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)

### Inferences
- The tools split by which token stream they target:
  - Bash output: RTK, squeez
  - all tool output / proxy level: Headroom, context-mode, Tokenade
  - file reads / navigation: code graphs, Serena, claude-context
  - model output: caveman
  
  They stack, but overlapping hooks can conflict, and lossy filtering can hide information the model needed.
- Savings are biggest for large repos and noisy commands (test logs, `git log -p`, `npm install`) and smallest for short sessions and prose.
- With prompt caching, a cut in raw token count can produce a much smaller cut in billed cost or plan-limit usage (Soba Labs caveat).

### Gaps
- No neutral third-party benchmark compares these tools head to head. THOL is run by Tokenade's author, and the code-graph benchmarks are by their authors.
- No measured data on whether compression or filtering lowers task success rate in Claude Code, beyond Headroom's small N=100 evals and anecdotes.

## Q4. Tools that reduce MCP tool-definition overhead

### Takeaway
Anthropic's built-in MCP Tool Search (on by default since about v2.1.7) defers tool schemas. It has largely made community lazy-loading proxies such as lazy-mcp (114 stars) unnecessary. The remaining levers are per-project server toggles in `/mcp` and `disabled*` settings, plus caveman-shrink-style description compression.

### Cited Findings
- Pre-fix overhead reports: one GitHub issue measured 7 MCP servers at 67,300 tokens (33.7% of context); a user saw 66,000 tokens gone before typing; another burned 42,000 tokens on tool definitions with only three servers — [claude-code issue #7336](https://github.com/anthropics/claude-code/issues/7336), [issue #11364](https://github.com/anthropics/claude-code/issues/11364), [VentureBeat](https://venturebeat.com/orchestration/claude-code-just-got-updated-with-one-of-the-most-requested-user-features)
- Tool Search shipped in Claude Code 2.1.7. It defers MCP tools when their descriptions exceed 10% of the context window, loads a small search index (about 500 tokens) instead of full schemas, and is on by default. The "about 85% reduction" figures come from secondary and community sources — [tessl](https://tessl.io/blog/anthropic-brings-mcp-tool-search-to-claude-code), [Cyrus](https://www.atcyrus.com/stories/mcp-tool-search-claude-code-context-pollution-guide), [jpcaparas/Medium](https://jpcaparas.medium.com/claude-code-finally-gets-lazy-loading-for-mcp-tools-explained-39b613d1d5cc)
- The official docs confirm Tool Search is on by default. It is unavailable with a custom `ANTHROPIC_BASE_URL`, with `ENABLE_TOOL_SEARCH=false`, and on some older models on Google Cloud — [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)
- Implication for proxies: a custom `ANTHROPIC_BASE_URL` disables Tool Search, so base-URL compression proxies (Headroom proxy, Paritok, OmniRoute/9router) may bring back the tool-definition overhead. Headroom's `wrap` exposes a `--tool-search` flag, probably for this reason — [Claude Code MCP docs](https://code.claude.com/docs/en/mcp); [Headroom README](https://github.com/headroomlabs-ai/headroom)
- Per-project disabling: toggling a server off in `/mcp` is saved per project in `~/.claude.json` as `disabledMcpServers` / `enabledMcpServers`. Project `.mcp.json` servers use `enabledMcpjsonServers` / `disabledMcpjsonServers`. claude.ai connectors can be turned off with `disableClaudeAiConnectors: true` or `deniedMcpServers`. Headless runs can use `--strict-mcp-config` — [Claude Code MCP docs](https://code.claude.com/docs/en/mcp)
- Community workarounds before the built-in fix included skills-inactive directories, lazy-mcp proxies and manual MCP toggling — [issue #44536](https://github.com/anthropics/claude-code/issues/44536). voicetreelab/lazy-mcp, an "MCP proxy server with lazy loading support," has only 114 stars — [GitHub](https://github.com/voicetreelab/lazy-mcp)
- Enterprise gateways (docker/mcp-gateway 1,609 stars, microsoft/mcp-gateway 889, agentic-community/mcp-gateway-registry 1,003 with "dynamic tool discovery") are mainly about governance and routing, not token savings — [GitHub search](https://github.com/docker/mcp-gateway)
- A critique argues the bigger problem with many MCP servers is tool-list bloat degrading agent accuracy, not token cost — [Towards AI](https://pub.towardsai.net/every-mcp-server-you-add-makes-claude-code-dumber-the-token-bill-was-never-the-real-problem-7f881916216b)
- caveman-shrink compresses MCP tool, prompt and resource descriptions (metadata only, v1) — [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)

### Inferences
- In 2026, third-party lazy-loading proxies are mostly obsolete for Claude Code. They matter only where Tool Search is off, such as custom base URLs and some cloud providers.

### Gaps
- I could not read the docs section "Scale with MCP tool search" (the page was truncated), so the exact current threshold and auto-mode settings rest on secondary sources.
- No first-party measurement of Tool Search savings was found.

## Q5. Benchmarks and credible measurements — verified vs marketing

### Takeaway
Few measurements are independent. The most credible are Soba Labs' RTK field measurement (49.6% on routed Bash commands), the caveman vendor's own revised benchmark (about 3% over a "be concise" baseline), and the community caveman tests. Nearly every other headline figure is the vendor's own claim: 60-90%, 98%, 49x, 95%+ and 71.5x.

### Cited Findings
- Independent or semi-independent:
  - RTK: 49.6% over 1,456 commands with `rtk gain` accounting — [Soba Labs](https://sobalabs.ai/blog/halving-claude-code-token-usage-with-rtk/)
  - code-review-graph: re-analysis gives 8.2x average vs the 49x headline — [DEV](https://dev.to/emperorakashi20/how-code-review-graph-cuts-claude-code-token-usage-by-49x-and-whether-its-actually-worth-it-4kn1)
  - caveman: community tests show "be brief" captures most of the gain — [andrew.ooo](https://andrew.ooo/posts/caveman-claude-code-skill-token-savings-review/)
- Benchmark by an interested party: THOL (by Tokenade's founder) ranks Tokenade first (39% cheaper on long sessions) and found no measurable saving for RTK or squeez — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
- Vendor or self-reported only:
  - RTK 60-90% — [rtk-ai/rtk](https://github.com/rtk-ai/rtk)
  - context-mode 98% — [README](https://github.com/mksglu/context-mode)
  - Headroom 20% / 60-95% JSON — [README](https://github.com/headroomlabs-ai/headroom)
  - codegraph −57% tokens — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
  - claude-context ~40% — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
  - token-optimizer $1.5-2.5k/month — [Tokenade](https://tokenade.net/en/articles/best-claude-code-token-optimizers)
  - jcodemunch 95%+ — [GitHub](https://github.com/jgravelle/jcodemunch-mcp)
  - claude-code-memory-setup 71.5x — [GitHub](https://github.com/lucasrosati/claude-code-memory-setup)

### Inferences
- Measure your own baseline first, with ccusage, `rtk gain` or `/context`, before and after adopting a tool. Published ratios depend heavily on the baseline (verbose prompts, "read everything" navigation).

### Gaps
- No peer-reviewed or neutral lab benchmark of Claude Code token-saving tools found.
- No data found on how token reductions translate into Pro/Max plan-limit headroom given prompt caching.
