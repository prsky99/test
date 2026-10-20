# Official built-in ways to control context and token usage in Claude Code (as documented by Anthropic, Oct 2026)

Source base: code.claude.com/docs (current docs reference Claude Code versions up to ~v2.1.305 and models Opus 5.5 / Sonnet 5.5 / Haiku 5.5 / Fable 5.1), support.claude.com help-center articles, and the Anthropic engineering blog. All fetched 2026-10-20. Version numbers below are as stated by the docs.

## 1. How usage is counted and why long sessions cost more

### Takeaway
Every request re-sends the entire context (system prompt + tools + CLAUDE.md/memory + full conversation + tool results); prompt caching makes re-reads cheaper but they still count, so usage grows with session length. Subscription plans meter usage on a rolling 5-hour window plus a weekly window, shared across Claude chat, Claude Code (CLI/IDE/desktop/cloud) and Cowork.

### Cited Findings
**Plan limits**
- Pro and Max both have a five-hour session limit and a weekly limit; Max also has a separate weekly limit for Fable. Claude and Claude Code share these limits; IDE usage counts too. Warnings appear as you approach a limit — [Use Claude Code with your Pro or Max plan](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- "Wrap-up allowance" (rolling out gradually): if the 5-hour limit is hit mid-response, Claude Code may keep working briefly to finish the current step ("Usage limit reached · wrapping up"); it is small, capped, counts toward the weekly limit; Pro: up to once per weekly period; Max: each time a 5-hour limit is reached — [same](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- If `ANTHROPIC_API_KEY` is set, Claude Code uses that key instead of the subscription and usage is billed at API rates. Check remaining allocation with `/status` (docs now point to `/usage`) — [same](https://support.claude.com/en/articles/11145838-using-claude-code-with-your-pro-or-max-plan)
- Max 5x = "five times the Pro plan's per-session usage allowance", Max 20x = "20 times"; the session limit "will reset every five hours"; Max weekly limit covers all models and resets at a fixed time assigned to the account (visible in Settings > Usage); Anthropic may apply other limits (weekly/monthly caps, model/feature usage) — [What is the Max plan?](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)
- Team/Enterprise: each member's Claude Code usage draws from a per-seat allowance that resets on a rolling five-hour window and a weekly window, shared with Claude chat and Cowork; size depends on seat tier (Standard/Premium) — [Manage costs effectively](https://code.claude.com/docs/en/costs)
- "You've hit your session limit"/"weekly limit" is shared across all models, so switching with `/model` doesn't restore access; after a model-specific "You've hit your Opus limit"/"Sonnet limit", switching to another family does keep you working. v2.1.234+ can wait and auto-continue after the reset (`autoContinueAtUsageLimit`, `/rate-limit-options`) — [costs](https://code.claude.com/docs/en/costs)
- Cloud sessions (Claude Code on the web) count toward the plan's usage limits alongside other Claude usage; no separate charge for the cloud VM; "Running multiple tasks in parallel consumes more rate limits proportionately" — [Use Claude Code in the cloud](https://code.claude.com/docs/en/claude-code-on-the-web)
- Enterprise average (API-billed deployments): ~$13 per developer per active day, $150–250 per developer per month, below $30/active day for 90% of users — [costs](https://code.claude.com/docs/en/costs)
- Budget more for a coding seat than a chat seat: "each Claude Code turn carries file contents, tool calls, and multi-step reasoning, so one debugging session can consume more than a day of chat" — [costs](https://code.claude.com/docs/en/costs)
- API team rate-limit recommendations (TPM/RPM per user): 1–5 users 200k–300k / 5–7; 5–20: 100k–150k / 2.5–3.5; 20–50: 50k–75k / 1.25–1.75; 50–100: 25k–35k / 0.62–0.87; 100–500: 15k–20k / 0.37–0.47; 500+: 10k–15k / 0.25–0.35 — [costs](https://code.claude.com/docs/en/costs)

**Why long sessions cost more**
- "Each time you send a message in Claude Code, it makes a new API request. The model doesn't remember anything between requests, so Claude Code re-sends the full context: the system prompt, your project context, every prior message and tool result, and your new message." — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- "Claude Code sends your full conversation with every request, and each time Claude uses tools it sends another request carrying that batch of tool results ... a one-line question in a session that has been open all day still draws usage for the whole conversation." — [costs: Why usage climbs in a long session](https://code.claude.com/docs/en/costs)
- Other listed causes of climbing usage: cache misses after a break longer than the cache lifetime; session-scoped scheduled tasks (`/loop`) firing while idle, each sending full context; cross-session messages delivered as new turns (set `crossSessionInbound` to `hold`); `/goal` idle check-ins (max 3 per goal between prompts since v2.1.246; disable with `CLAUDE_CODE_GOAL_CHECKIN_MINUTES=0`); subagents and workflow agents; agent teammates; compaction itself ("`/compact` reads the conversation it summarizes ... When you want a fresh start instead of continuity, `/clear` costs nothing") — [costs](https://code.claude.com/docs/en/costs)
- Help center: each turn resends the conversation so far, project context (CLAUDE.md and files read) and the new prompt; history grows fastest and drives both cost and context-limit issues; caching makes turns cheaper but content still occupies context — [Models, usage, and limits in Claude Code](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)
- Background token usage: summarization for `claude --resume` and status checks such as `/usage` — "typically under $0.04 per session"; prompt suggestions send a short mostly-cache-read request after each response (skipped near usage limit; can be turned off) — [costs](https://code.claude.com/docs/en/costs)

**Prompt caching and TTL**
- Cache matches the exact request prefix; "a change anywhere in the prefix recomputes everything after it. There is no per-file or per-segment caching." Layer order: system prompt + tool definitions → project context (CLAUDE.md, auto memory, unscoped rules) → conversation — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Two TTLs: 5 minutes and 1 hour (1-hour charges a higher cache-write rate). Defaults: Claude subscription within plan usage → main conversation 1 hour; subagents/compaction/workflows/etc. 5 minutes (except some server-controlled helpers). Usage credits, API key, or cloud provider → 5 minutes for everything. When a subscriber goes over the plan limit onto usage credits, the main conversation drops to 5 minutes — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Controls (v2.1.242+): `promptCacheTtl` setting / `CLAUDE_CODE_PROMPT_CACHE_TTL` (main), `subagentPromptCacheTtl` / `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL` (everything else), values `5m` or `1h`; precedence: `FORCE_PROMPT_CACHING_5M=1` > bucket env var > bucket setting > subagent `experimental.cacheTtl` frontmatter (v2.1.248+) > `ENABLE_PROMPT_CACHING_1H=1` > default — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Actions that invalidate the cache: switching models (each model has its own cache; `opusplan` toggles are model switches); changing effort (except on Opus 5.5/Sonnet 5.5/Haiku 5.5/Fable 5.1 with API key or subscription); turning on fast mode (once per conversation); connecting/removing MCP servers when tools load upfront; enabling/disabling plugins that provide MCP servers; denying an entire tool (only when tool search is off); compaction; accumulating many images; upgrading Claude Code — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Actions that keep the cache: editing repo files, editing CLAUDE.md mid-session (edit doesn't apply until `/clear`, `/compact` or restart), changing permission mode, changing output style (applies next message since v2.1.251), invoking skills/commands, `/recap`, `/rewind`, spawning a subagent — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Tip: "Pick your model and effort level at the top of a session, then save `/compact` for natural breaks between tasks." — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- `/compact` while cache is warm reads the prefix from cache "so a mid-session `/compact` costs a fraction of what the context size suggests"; after a break longer than the TTL it reprocesses the full history uncached — "why `/compact` costs the most when you resume an old session". Rewinding "truncates back to a prefix that is already cached" — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Idle compaction: on the 1-hour TTL in a terminal session, Claude Code can compact a long idle conversation shortly before the cache expires; disable with `idleCompaction: false` (v2.1.290+); threshold `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` default 200000 (min 100000) — [Prompt caching](https://code.claude.com/docs/en/prompt-caching); [env vars](https://code.claude.com/docs/en/env-vars)
- `/usage` "Prompt cache (main)" line (v2.1.251+): request count, % input from cache, misses (likely cause named since v2.1.260), expected rebuilds, warm/cold with TTL — [costs](https://code.claude.com/docs/en/costs)
- Cache is effectively scoped to one machine+directory; parallel sessions in the same directory share cache — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)

### Inferences
- The two biggest levers on subscription consumption are (a) total context size per request and (b) number of requests; caching discounts (a) but cache misses (idle > TTL, model/effort switches) remove the discount for one turn.
- Because the main conversation gets a 1-hour TTL on subscriptions but subagents get 5 minutes, bursts of subagent work after idle periods are relatively more expensive.

### Gaps
- No official per-plan message or hour counts for Pro / Max 5x / Max 20x were found in current help-center articles (only multipliers relative to Pro). The date weekly limits were introduced (widely reported as late Aug 2025) was not confirmed from a primary source in this research.
- Exact cache read/write price multipliers were not fetched (docs link to platform.claude.com pricing).

## 2. Commands: /clear, /compact, auto-compact, /autocompact, /context, /usage (/cost, /stats), /resume, /rewind and "Summarize from here", /btw, others

### Takeaway
Anthropic's primary recommendation is `/clear` between unrelated tasks (free), `/compact <focus>` at natural breaks (costs a summarization request), `/rewind` to abandon wrong paths (cache-friendly), `/btw` for side questions (never enters history), and `/context` + `/usage` to see what's consuming space and plan limits.

### Cited Findings
- `/clear [name]`: "Start a new conversation with empty context. Pass a name to label the previous conversation in the `/resume` picker." Aliases `/reset`, `/new`. Restorable via `/resume` or the rewind menu's previous-session entry — [Commands](https://code.claude.com/docs/en/commands)
- Recommendation: "Use `/clear` to start fresh when switching to unrelated work. Stale context wastes tokens on every subsequent message. Use `/rename` before clearing so you can find the session later, then `/resume` to return to it." — [costs](https://code.claude.com/docs/en/costs)
- "If you've corrected Claude more than twice on the same issue in one session ... Run `/clear` and start fresh with a more specific prompt ... A clean session with a better prompt almost always outperforms a long session with accumulated corrections." — [Best practices](https://code.claude.com/docs/en/best-practices)
- `/usage` session totals reset on `/clear` (since v2.1.211) — [costs](https://code.claude.com/docs/en/costs)
- `/compact [instructions]`: "Free up context by summarizing the conversation so far. Optionally pass focus instructions" e.g. `/compact Focus on code samples and API usage`. Compaction can also be customized in CLAUDE.md, e.g. a "# Compact instructions" section, or "When compacting, always preserve the full list of modified files and any test commands" — [Commands](https://code.claude.com/docs/en/commands); [costs](https://code.claude.com/docs/en/costs); [Best practices](https://code.claude.com/docs/en/best-practices)
- What survives compaction: system prompt & output style still apply; project-root CLAUDE.md, unscoped rules and auto memory re-injected from disk; skill descriptions rebuilt (v2.1.304+); plan file re-injected; path-scoped rules and nested CLAUDE.md reload on demand; up to five most recently modified read/edited files re-read (a file over 5,000 tokens comes back only as a path reference); invoked skill bodies re-injected capped at 5,000 tokens per skill and 25,000 total; hook-added context is summarized; SessionStart hooks matching `compact` run again. Since v2.1.198 the summarization inherits the session's extended-thinking config — [Explore the context window](https://code.claude.com/docs/en/context-window)
- Auto-compaction: "Claude Code automatically compacts conversation history when you approach context limits." Default thresholds: compaction at the model's limit, except Sonnet 4.6/Opus 4.6 without extended context compact at 200K; 1M-native models compact at about 967K tokens; with `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` 1M-native models compact at 200K; unknown model IDs assumed 200K — [Model configuration](https://code.claude.com/docs/en/model-config)
- `/autocompact [auto|<tokens>]` (v2.1.221+; per-model saving v2.1.288+): sets how full the window gets before auto-compaction, e.g. `/autocompact 500k`; also `autoCompactWindow` setting, `claude --autocompact <size>` flag, and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` env var (overrides all). Accepted 100K–1M tokens — [Commands](https://code.claude.com/docs/en/commands); [Model configuration](https://code.claude.com/docs/en/model-config)
- `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`: percentage (1–100) of the auto-compact window at which auto-compaction triggers; can only lower, not raise; applies to main conversation and subagents. `DISABLE_AUTO_COMPACT=1` disables auto + idle compaction (manual `/compact` remains; overrides `autoCompactEnabled` setting). `DISABLE_COMPACT=1` disables all compaction — [Environment variables](https://code.claude.com/docs/en/env-vars)
- Best-practice note: "run `/compact` at a natural break in your work, such as between tasks, instead of waiting for auto-compaction to trigger mid-task. If you've gone down a path you want to abandon entirely, `/rewind` to an earlier turn instead." — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- `/rewind` (aliases `/checkpoint`, `/undo`; or Esc+Esc): restore conversation, code, or both to a checkpoint, or summarize from a selected message. "Summarize from here" condenses messages from that point forward keeping earlier context intact; "Summarize up to here" condenses earlier messages keeping recent ones in full. Every prompt that starts a turn creates a checkpoint; checkpoints only track changes from Claude's file-editing tools, not Bash — [Commands](https://code.claude.com/docs/en/commands); [Best practices](https://code.claude.com/docs/en/best-practices)
- `/context [all]`: "Visualize current context usage as a colored grid. Shows optimization suggestions for context-heavy tools, memory bloat, and capacity warnings." Also shows which CLAUDE.md and auto memory files loaded — [Commands](https://code.claude.com/docs/en/commands); [context window](https://code.claude.com/docs/en/context-window)
- `/usage` (aliases `/cost`, `/stats`): session cost (API estimate at list price), plan usage bars, and on Pro/Max/Team/Enterprise a breakdown attributing recent usage to skills, subagents, plugins and individual MCP servers, plus Recommendations (rows ≥10% share, e.g. "Trim ~/code/api/CLAUDE.md · 49k tokens per request", "Switch from max to high effort · /effort high", "Compact before you step away · run /compact") and heaviest `/loop` tasks (v2.1.242+); `d`/`w` toggles 24h/7d; `f` applies fixes (v2.1.305+). Computed from local history only — [costs](https://code.claude.com/docs/en/costs)
- `/btw [question]`: side question; "The answer never enters conversation history, so you can check a detail without growing context." It sees full context, has no tool access — [Best practices](https://code.claude.com/docs/en/best-practices); [Subagents](https://code.claude.com/docs/en/sub-agents)
- `/recap`: one-line session summary appended as output (keeps cache, unlike `/compact`) — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- `/resume` (alias `/continue`), `claude --continue`, `claude --resume`; name sessions with `/rename` "and treat them like branches"; `/branch` creates a branch of the conversation; `/fork` copies into a background session; `/subtask` spawns a forked subagent whose result returns — [Commands](https://code.claude.com/docs/en/commands); [Best practices](https://code.claude.com/docs/en/best-practices)
- `/insights`: HTML report of up to 200 recent sessions (friction points, suggestions); costs tokens; not available in cloud sessions — [costs](https://code.claude.com/docs/en/costs)
- `/doctor` (alias `/checkup`) proposes cuts to a checked-in CLAUDE.md for content derivable from the codebase; `/doctor prompt-audit` audits instructions (v2.1.283+) — [Best practices](https://code.claude.com/docs/en/best-practices); [Commands](https://code.claude.com/docs/en/commands)
- `/statusline` can display context usage/cost continuously; status-line scripts can read `current_usage` and `prompt_cache` fields — [costs](https://code.claude.com/docs/en/costs); [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Spinner token count = output of the current turn only, not input context — [costs](https://code.claude.com/docs/en/costs)

### Inferences
- Order of cheapness for freeing context: `/clear` (free) < `/rewind` (reuses cached prefix) < `/compact` while warm < `/compact` after idle (full uncached read).

### Gaps
- No published fixed percentage for when the auto-compact warning appears; docs describe thresholds in tokens per model instead.

## 3. Settings and environment variables affecting context or token spend

### Takeaway
Key knobs are model (`/model`, `opusplan`, subagent model), effort (`/effort`, default medium on Opus/Sonnet/Haiku 5.5), thinking budget (`MAX_THINKING_TOKENS`, only on fixed-budget models), auto-compact window/percent, output caps, tool-output caps (Bash 30k chars, file read 25k tokens, MCP 25k tokens), tool search, and cache TTL.

### Cited Findings
**Model selection**
- "Sonnet handles most coding tasks well and costs less than Opus. Reserve Opus for complex architectural decisions or multi-step reasoning. Use `/model` to switch models mid-session, or set a default in `/config`." A switch to Opus also applies to subagents that inherit the session model; for simple subagent tasks specify `model: haiku` — [costs](https://code.claude.com/docs/en/costs)
- Help center: Opus "uses meaningfully more of your quota" and costs "several times more per turn than Sonnet, and Sonnet more than Haiku"; common pattern: plan with Opus, execute with Sonnet via `/model opusplan` — [Models, usage, and limits](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)
- Contrasting view: Anthropic's power-user tips say the Claude Code team uses Opus with thinking for everything, as it is "almost always faster than using a smaller model in the end" — [Power user tips](https://support.claude.com/en/articles/14554000-claude-code-power-user-tips)
- Default model for Pro, Max, Team, Enterprise, API, Bedrock, Vertex: Opus 5.5 (Foundry: Sonnet 4.5). Aliases: `default`, `best`, `fable`, `sonnet`, `opus`, `haiku`, `sonnet[1m]`, `opus[1m]`, `opusplan`. Unexpectedly high spend "usually traces back to long sessions that were never cleared or to Opus left as the default model" — [Model configuration](https://code.claude.com/docs/en/model-config); [costs](https://code.claude.com/docs/en/costs)
- 1M context default on Fable 5.x, Sonnet 5+, Haiku 5.5, Opus 4.7+; `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` forces 200K windows. Haiku 5.5: prompts over 100K tokens cost more — [Model configuration](https://code.claude.com/docs/en/model-config)
- `CLAUDE_CODE_SUBAGENT_MODEL` sets default model for subagents/teammates/workflow agents; `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` (v2.1.257+) forces it over frontmatter — [env vars](https://code.claude.com/docs/en/env-vars); [Subagents](https://code.claude.com/docs/en/sub-agents)
- `ANTHROPIC_DEFAULT_HAIKU_MODEL` controls background functionality model (`ANTHROPIC_SMALL_FAST_MODEL` deprecated) — [Model configuration](https://code.claude.com/docs/en/model-config)

**Effort and thinking**
- Effort levels `low`, `medium`, `high`, `xhigh`, `max` (Opus/Sonnet 4.6: no `xhigh`). Defaults: `high` on most models, `medium` on Opus 5.5/Sonnet 5.5/Haiku 5.5, `xhigh` on Opus 4.7. Set via `/effort <level>`, `--effort`, `CLAUDE_CODE_EFFORT_LEVEL`, `effortLevel` setting, skill/subagent frontmatter `effort:`; `max` is session-only unless set via env var — [Model configuration](https://code.claude.com/docs/en/model-config)
- Guidance: low for quick exchanges; medium for clearly scoped day-to-day work; high for bug fixes/verification-heavy work; xhigh deeper reasoning; max for hard problems (warning about diminishing returns) — [Model configuration](https://code.claude.com/docs/en/model-config). "Max burns through usage limits faster, so activate it per session." — [Power user tips](https://support.claude.com/en/articles/14554000-claude-code-power-user-tips)
- "Thinking tokens are billed as output tokens, and the default budget can be tens of thousands of tokens per request depending on the model." Reduce via `/effort`, or disable thinking in `/config` (not possible on Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable). On fixed-budget models set `MAX_THINKING_TOKENS` e.g. `8000`; adaptive-reasoning models ignore nonzero budgets — [costs](https://code.claude.com/docs/en/costs)
- `MAX_THINKING_TOKENS`: capped one below max output tokens, never below 1,024; `0` disables thinking on the API (except the always-thinking models). Always-adaptive models: Fable, Sonnet 5+, Haiku 5.5, Opus 4.7+; on Opus/Sonnet 4.6, `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` reverts to fixed budget. Thinking toggle: Option+T / Alt+T; `alwaysThinkingEnabled` in `/config`; `ultrathink` keyword for one turn — [env vars](https://code.claude.com/docs/en/env-vars); [Model configuration](https://code.claude.com/docs/en/model-config)
- On Opus 5.5/Sonnet 5.5/Haiku 5.5/Fable 5.1 with API key or subscription, changing effort keeps the cache; on other models it invalidates the cache — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)

**Output and tool-result caps**
- `CLAUDE_CODE_MAX_OUTPUT_TOKENS`: max output for most requests (unknown model default 32000, cap 128000); "Increasing this value reduces the effective context window available before auto-compaction triggers." — [env vars](https://code.claude.com/docs/en/env-vars)
- `BASH_MAX_OUTPUT_LENGTH`: chars of bash output read back (default 30000, max 150000; `bashOutputMaxChars` setting overrides). `CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS`: default file read limit 25,000 tokens. `CLAUDE_CODE_MAX_TURNS` caps agentic turns — [env vars](https://code.claude.com/docs/en/env-vars)
- `MAX_MCP_OUTPUT_TOKENS` default 25000; warning above 10,000 tokens; text results over 50,000 chars saved to file — [env vars](https://code.claude.com/docs/en/env-vars); [MCP](https://code.claude.com/docs/en/mcp)

**Output style, other**
- Output style can be switched with `/output-style` (v2.1.269+) or `/config`; mid-session switch keeps the cache — [Commands](https://code.claude.com/docs/en/commands); [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Fast mode: first request with fast mode on is uncached and billed at fast mode rates — "turning it on at the start of a session costs less than turning it on deep into a long one" — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- `DISABLE_AUTOUPDATER=1` to control when upgrades apply (an upgrade causes one uncached first turn) — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- `--bare` for non-interactive use: "roughly 10× faster startup", skips auto-discovery of CLAUDE.md, settings and MCPs — [Power user tips](https://support.claude.com/en/articles/14554000-claude-code-power-user-tips)
- `--max-budget-usd` CLI flag counts session cost — [costs](https://code.claude.com/docs/en/costs)
- `MCP_TIMEOUT` = MCP server startup timeout (default 30000 ms) — it is a latency/reliability setting, not a token setting; `MCP_TOOL_TIMEOUT` default ~28 hours — [env vars](https://code.claude.com/docs/en/env-vars)

### Inferences
- `MCP_TIMEOUT` (named in the brief) does not reduce tokens; it is unrelated to context size.
- Since Opus 5.5 is the default for subscriptions and 5.5 models default to `medium` effort, the most impactful single setting change for a heavy user is likely `/model sonnet` (or `opusplan`) and avoiding `max` effort.

### Gaps
- Exact default thinking budgets per model and per-model `CLAUDE_CODE_MAX_OUTPUT_TOKENS` defaults were not listed in the fetched text.

## 4. CLAUDE.md, @-imports, rules, memory, skills, subagents, plan mode

### Takeaway
Anything loaded at startup (CLAUDE.md + imports, unscoped rules, auto memory first 200 lines/25KB, skill descriptions, subagent descriptions, MCP tool names) is paid on every request; Anthropic recommends < 200 lines per CLAUDE.md, moving specialized content into skills (only descriptions load until invoked) or path-scoped rules, and delegating verbose work to subagents (separate context, only summary returns, but still counts toward usage).

### Cited Findings
**CLAUDE.md / imports / rules / memory**
- "Your CLAUDE.md file is loaded into context at session start ... Skills load on-demand only when invoked, so moving specialized instructions into skills keeps your base context smaller. Aim to keep CLAUDE.md under 200 lines by including only essentials." — [costs](https://code.claude.com/docs/en/costs)
- "Size: target under 200 lines per CLAUDE.md file. Longer files consume more context and reduce adherence." Imports "help you organize a long file but don't reduce its context cost" — [Memory](https://code.claude.com/docs/en/memory)
- `@path/to/import`: imported files expanded and loaded at launch; recursive imports max depth four hops; backtick-wrapped paths are not imported — [Memory](https://code.claude.com/docs/en/memory)
- Help center: "Use bare paths when saving tokens, since `@` injects the full file"; trim logs/stack traces to about 20–30 lines; add a CLAUDE.md note only after correcting Claude twice; ask for a plan before changes touching more than two or three files ("a plan costs a few hundred tokens") — [Models, usage, and limits](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)
- Ancestor CLAUDE.md/CLAUDE.local.md load at launch; subdirectory CLAUDE.md files load on demand when Claude touches files there; `claudeMdExcludes` skips files by glob (monorepos); block-level HTML comments in CLAUDE.md are stripped before injection ("without spending context tokens on them") — [Memory](https://code.claude.com/docs/en/memory)
- `.claude/rules/` with `paths:` frontmatter load only when Claude reads/edits matching files; rules without `paths` load at launch. Path-scoped rules are summarized away on compaction — [Memory](https://code.claude.com/docs/en/memory); [context window](https://code.claude.com/docs/en/context-window)
- Auto memory: loaded every session, first 200 lines or 25KB — [Memory](https://code.claude.com/docs/en/memory)
- Best-practices table: exclude anything Claude can figure out from code, standard conventions, detailed API docs, frequently changing info, long tutorials, file-by-file descriptions. "Bloated CLAUDE.md files cause Claude to ignore your actual instructions!" — [Best practices](https://code.claude.com/docs/en/best-practices)

**Skills (progressive disclosure)**
- "Skill descriptions are loaded into context so Claude knows what's available. Full skill content loads only when the skill is invoked." `description` + `when_to_use` truncated at 1,536 characters. `disable-model-invocation: true` → description not in context at all. Keep `SKILL.md` under 500 lines; supporting files load only when needed; scripts are executed, not loaded. Once invoked, the rendered SKILL.md stays in the conversation ("Every line is a recurring token cost once the skill loads"); re-invocation with identical content adds a short "already loaded" note — [Skills](https://code.claude.com/docs/en/skills)
- Skill listing budget: `SLASH_COMMAND_TOOL_CHAR_BUDGET`, "scales dynamically at 1% of the context window, with a fallback of 8,000 characters" — [env vars](https://code.claude.com/docs/en/env-vars)
- `skillOverrides` setting: `on` / `name-only` / `user-invocable-only` / `off`; `/skills` press `t` to sort by token count; `/skill-doctor` (v2.1.252+) shows each skill's context cost and flags never-invoked skills — [Skills](https://code.claude.com/docs/en/skills); [Commands](https://code.claude.com/docs/en/commands)
- A "codebase-overview" skill can give architecture context instead of spending tokens reading many files — [costs](https://code.claude.com/docs/en/costs)

**Subagents**
- "Delegate verbose operations to subagents ... the verbose output stays in the subagent's context while only a summary returns to your main conversation. The subagent's own requests still draw on your usage." — [costs](https://code.claude.com/docs/en/costs)
- Subagent requests "count toward the same usage limits as your main conversation"; subagent descriptions consume context every session (startup warning above 15,000 tokens combined); non-fork subagents load CLAUDE.md (unless `omitClaudeMd: true`, v2.1.271+), git status, preloaded skills, but not conversation history; built-in Explore and Plan skip CLAUDE.md; define your own `Explore` with `model: haiku` for cheaper exploration; `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` disables them (puts reads into main context); subagent `autoCompactWindow` frontmatter (v2.1.296+); default concurrency 20, nesting depth 3 — [Subagents](https://code.claude.com/docs/en/sub-agents)
- Subagents get a 5-minute cache TTL even on subscriptions; forks inherit the parent's prefix and read its cache — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Engineering blog: sub-agents may use tens of thousands of tokens exploring but return condensed summaries "often 1,000-2,000 tokens" (Sept 29, 2025) — [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Agent teams: "approximately 7x more tokens than standard sessions when teammates run in plan mode"; disabled by default (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`); use Sonnet for teammates, keep teams small, shut down when done — [costs](https://code.claude.com/docs/en/costs)

**Plan mode, prompting, hooks**
- Plan mode (Shift+Tab, `/plan`, `--permission-mode plan`) "preventing expensive re-work when the initial direction is wrong"; but "Plan mode is useful, but also adds overhead ... If you could describe the diff in one sentence, skip the plan." Plan mode and skill loading append as messages so the cached prefix stays intact — [costs](https://code.claude.com/docs/en/costs); [Best practices](https://code.claude.com/docs/en/best-practices); [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Write specific prompts: "Vague requests like 'improve this codebase' trigger broad scanning." — [costs](https://code.claude.com/docs/en/costs)
- Hooks preprocessing: e.g. grep a 10,000-line log for ERROR "reducing context from tens of thousands of tokens to hundreds"; PreToolUse hook example filters test output to failures — [costs](https://code.claude.com/docs/en/costs)
- Code intelligence (LSP) plugins: "go to definition" replaces grep + reading multiple files — [costs](https://code.claude.com/docs/en/costs)
- Prefer CLI tools (`gh`, `aws`, `gcloud`, `sentry-cli`): "the most context-efficient way to interact with external services" — [Best practices](https://code.claude.com/docs/en/best-practices)
- Interview → write SPEC.md → start a fresh session to implement ("clean context focused entirely on implementation") — [Best practices](https://code.claude.com/docs/en/best-practices)
- Context engineering principles: context rot, attention budget, compaction keeps the five most recently accessed files, tool result clearing as lightest-touch compaction, structured note-taking (NOTES.md / to-dos), just-in-time retrieval via glob/grep — [Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

### Inferences
- `@`-mentioning a file in a prompt or CLAUDE.md is a full read into context; giving a bare path lets Claude read selectively.
- Subagents save main-context space (and thus compaction frequency) but do not necessarily save total plan usage; they may increase it.

### Gaps
- No official token count for the base system prompt + built-in tools was found (the context-window page uses "representative" numbers only, in an interactive visual not captured as text).

## 5. MCP tool definitions and lazy loading (tool search)

### Takeaway
MCP tool definitions are deferred by default (tool search): only tool names and server instructions load at start; full schemas load on demand. Anthropic still says CLI tools are more context-efficient than MCP, and recommends disabling unused servers in `/mcp`.

### Cited Findings
- "MCP tool definitions are deferred by default, so only tool names and server instructions enter context until Claude uses a specific tool. Run `/context` to see what's consuming space." Prefer CLI tools ("they don't add any per-tool listing"); "Disable unused servers: Run `/mcp`" — [costs](https://code.claude.com/docs/en/costs)
- "Tool search keeps MCP context usage low by deferring tool definitions until Claude needs them ... adding more MCP servers has minimal impact on your context window. Claude Code doesn't impose a fixed per-server tool cap" — [MCP](https://code.claude.com/docs/en/mcp)
- `ENABLE_TOOL_SEARCH`: unset = all deferred (falls back to upfront on models before Opus 4/Sonnet 4, older Vertex models, non-first-party `ANTHROPIC_BASE_URL`, Foundry-on-Azure); `true` = keep deferred through proxies; `auto` = load upfront while definitions total < 10% of context window, defer once ≥10%; `auto:N` custom %; `false` = all upfront. `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS` keeps it off; HIPAA config disables it — [MCP](https://code.claude.com/docs/en/mcp)
- Description limits: server instructions and upfront tool descriptions cut at 4,096 chars; deferred tool descriptions at 16,384 chars (before v2.1.296 the short limit was 2,048); override with `CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH` (v2.1.280+) — [MCP](https://code.claude.com/docs/en/mcp)
- `alwaysLoad: true` per server (or `_meta["anthropic/alwaysLoad"]` per tool) exempts from deferral — "each upfront tool consumes context"; `alwaysLoad: false` defers all of a server's tools (v2.1.287+) — [MCP](https://code.claude.com/docs/en/mcp)
- With tools deferred, connecting/disconnecting a server mid-session doesn't invalidate the cache; with tools loaded upfront, it does — [Prompt caching](https://code.claude.com/docs/en/prompt-caching)
- Toggle servers off in `/mcp` (`/mcp disable <server>|all`), stored as `disabledMcpServers`; disable claude.ai connectors with `disableClaudeAiConnectors: true` or `ENABLE_CLAUDEAI_MCP_SERVERS=false` — [MCP](https://code.claude.com/docs/en/mcp); [Commands](https://code.claude.com/docs/en/commands)
- `/usage` attributes usage per MCP server (counting only requests that consumed one of its tool results, fixed in v2.1.222) — [costs](https://code.claude.com/docs/en/costs)
- MCP output: warning > 10,000 tokens, default cap 25,000 (`MAX_MCP_OUTPUT_TOKENS`), > 50,000 chars saved to file; per-tool `anthropic/maxResultSizeChars` up to 500,000 — [MCP](https://code.claude.com/docs/en/mcp)

### Inferences
- With deferred loading the residual per-server cost is names + instructions (≤ 4,096 chars per server), plus full schemas only for tools actually used, which then stay in the conversation.

### Gaps
- The introduction date/version for default-on tool search in Claude Code was not stated in the fetched text (only that before v2.1.221 it was off on Vertex by default).

## 6. Claude Code on the web (cloud sessions) vs local CLI

### Takeaway
Cloud sessions share the same plan limits (no VM charge), support `/compact` and `/context` but not `/clear` (start a new session instead), and pre-set `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` so compaction triggers earlier than locally.

### Cited Findings
- Cloud sessions available on Pro, Max, Team, and Enterprise premium / Chat + Claude Code seats; count toward plan usage limits; no separate charge for the VM — [Claude Code in the cloud](https://code.claude.com/docs/en/claude-code-on-the-web)
- Context commands in cloud: `/compact` yes (accepts focus instructions), `/context` yes, `/clear` no — "Start a new session from the sidebar instead"; terminal-only commands such as `/plugin`, `/resume` unavailable; `/model`, `/effort` take arguments — [same](https://code.claude.com/docs/en/claude-code-on-the-web)
- "Cloud sessions set `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` themselves, so compaction triggers partway through the auto-compact window rather than when the window fills." Your own value for that var is overridden; to change, set `CLAUDE_CODE_AUTO_COMPACT_WINDOW` in environment variables or run `/autocompact` — [same](https://code.claude.com/docs/en/claude-code-on-the-web)
- Subagents work the same; agent teams off by default — [same](https://code.claude.com/docs/en/claude-code-on-the-web)
- Limitations: cloud sessions share rate limits with all other usage; parallel tasks consume proportionately more; sessions stop after inactivity and the VM is reclaimed (conversation history restored on reopen, background work not) — [same](https://code.claude.com/docs/en/claude-code-on-the-web)
- `/insights` not available in cloud sessions — [Commands](https://code.claude.com/docs/en/commands)
- Recommended pattern: plan locally in plan mode, commit the plan, then `claude --cloud "Execute the migration plan in docs/migration-plan.md"` — [same](https://code.claude.com/docs/en/claude-code-on-the-web)

### Inferences
- In cloud sessions, the equivalent of `/clear` is opening a new session; since `/clear` is unavailable, long cloud threads are more likely to accumulate context.

### Gaps
- The exact percentage that cloud sessions set for `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` and the inactivity timeout duration were not published in the fetched page.

## 7. Official best-practice summary (concrete recommendations)

### Takeaway
Anthropic's guidance converges on: context is the most important resource; clear often, compact deliberately, keep startup context lean, pick the cheapest adequate model/effort, delegate verbose work, scope prompts, and monitor with `/context` and `/usage`.

### Cited Findings
- "Most best practices are based on one constraint: Claude's context window fills up fast, and performance degrades as it fills." — [Best practices](https://code.claude.com/docs/en/best-practices)
- Manage-costs checklist: `/clear` between tasks; custom compaction instructions; choose the right model; reduce MCP overhead; code intelligence plugins; offload to hooks and skills; move CLAUDE.md content to skills (< 200 lines); adjust extended thinking; delegate verbose ops to subagents; manage agent-team costs; write specific prompts; plan mode for complex tasks; course-correct early with Esc / `/rewind`; give verification targets; test incrementally — [costs](https://code.claude.com/docs/en/costs)
- Failure patterns: kitchen-sink session (fix: `/clear`), correcting over and over (after two failed corrections `/clear`), over-specified CLAUDE.md (prune / convert to hook), infinite exploration (scope narrowly or use subagents) — [Best practices](https://code.claude.com/docs/en/best-practices)
- Help-center habits: clear between tasks; match model to job; point at files by path; keep CLAUDE.md ~200 lines; plan before >2–3 file changes — [Models, usage, and limits](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)
- Power user tips: `/effort xhigh` "for deeper reasoning than high without the full token cost of max"; `PostCompact` hook to re-inject critical instructions; `/statusline` for remaining context and cost; slash commands with inline Bash pre-compute info without extra model calls — [Power user tips](https://support.claude.com/en/articles/14554000-claude-code-power-user-tips)
- General usage best practices (Claude apps): plan conversations, batch related requests into one message, use projects (cached content counts less) — summarized from search snippet of [Usage limit best practices](https://support.claude.com/en/articles/9797557-usage-limit-best-practices) (not fetched in full; second-hand via search summary)

### Inferences
- There is mild tension in Anthropic's own guidance: docs and help center recommend Sonnet for most coding to save usage, while the power-user tips article reports the Claude Code team using Opus for everything for speed/steerability. The report should present both.

### Gaps
- "Usage limit best practices" article content was only seen via search summary, not fetched.
- The blog post "Lessons from building Claude Code: Prompt caching is everything" (claude.com/blog) is linked from the docs but was not fetched.
