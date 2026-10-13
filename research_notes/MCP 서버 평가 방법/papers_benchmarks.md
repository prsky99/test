# Academic papers and benchmarks that evaluate MCP servers and tool use over MCP (through Oct 2026)

Research date: 2026-10-13. Unless noted otherwise, figures come from arXiv abstract pages or HTML full text, read through a fetch tool that summarizes pages. Most arXiv abstract pages were paraphrased, not quoted verbatim, so the numbers below are as the summary reported them. Verify any number before quoting it in a final deliverable. The arXiv API was rate-limited during this session, so the paper inventory came from arXiv web search plus general web search. It is broad but probably not exhaustive: arXiv returned 184 hits for the abstract search `"Model Context Protocol" benchmark`, and I read only the newest ~38.

## Q1. Which MCP benchmarks and evaluation papers exist, and what does each measure and how?

### Takeaway
The field splits into four families:
- **Agent-task benchmarks.** An LLM agent runs tasks against real or simulated MCP servers and is scored by execution-based checkers, LLM judges, or both. Examples: MCP-Universe, MCP-Bench, LiveMCPBench, MCPMark, MCP-Atlas, MCP-AgentBench, MCPToolBench++, MCP-RADAR, DynamicMCPBench, MCPWorld/OSWorld-MCP.
- **Tool retrieval and discovery work.** Examples: MCP-Zero, LiveMCPBench, Cartograph.
- **Description-quality ("smell") studies.** Examples: Hasan et al. 2602.14878, Wang et al. 2602.18914.
- **Ecosystem measurement studies.** Examples: Hasan et al. 2506.13538, Guo et al. 2509.25292, MCPZoo 2512.15144, Afsar 2609.10962.

Even the best frontier models typically solve only about 30-75% of realistic MCP tasks, depending on the benchmark and the strictness of scoring.

### Cited Findings

**Agent / LLM tool-use benchmarks (chronological)**
- **MCP-RADAR** (Gao, Xie, Zhai, Ma, Shen; arXiv 2505.16700; submitted 22 May 2025, revised 12 Oct 2025)
  - Bills itself as "the first comprehensive benchmark specifically designed to evaluate LLM performance within the MCP framework."
  - 507 tasks across 6 domains: math, web search, email, calendar, file management, terminal.
  - Uses authentic MCP tools plus high-fidelity simulations.
  - Metrics: answer correctness, operational accuracy, computational resource efficiency, number of successful tool-invocation rounds.
  - Finding: "a significant trade-off between accuracy and efficiency." — [arXiv 2505.16700](https://arxiv.org/abs/2505.16700)
- **MCP-Zero: Active Tool Discovery for Autonomous LLM Agents** (Fei, Zheng, Feng; arXiv 2506.01056; 1 Jun 2025)
  - The agent requests the tools it needs instead of having all schemas injected.
  - Builds the MCP-tools dataset from the official MCP repository: 308 servers, 2,797 tools.
  - Selects tools accurately from nearly 3k candidates spanning 248.1k tokens.
  - Cuts token consumption by 98% on APIBank while accuracy stays "high"; the abstract gives no accuracy figure. — [arXiv 2506.01056](https://arxiv.org/abs/2506.01056)
- **MCPWorld** (Yan et al., BUPT and Pengcheng Lab; arXiv 2506.07672; Jun 2025)
  - Testbed for API, GUI and hybrid computer-use agents on "white-box" apps, so completion is checked by monitoring app behavior, not with an LLM judge.
  - 201 tasks; 75.12% task completion with one agent framework.
  - A secondary summary reports GUI-only 70.65%, MCP-only 53.23%, hybrid 75.12% (from emergentmind, not verified against the paper). — [arXiv 2506.07672](https://arxiv.org/pdf/2506.07672)
- **MCPEval** (Liu, Qiu, Wang, Zhang et al., Salesforce AI Research; arXiv 2507.12806; 17 Jul 2025; cited as EMNLP 2025 System Demos)
  - Open-source framework that "automates end-to-end task generation and deep evaluation of LLM agents" over MCP, across 5 domains.
  - MCP-Universe's comparison table says MCPEval uses LLM-as-a-Judge and lacks real-world integration. — [arXiv 2507.12806](https://arxiv.org/abs/2507.12806); [MCP-Universe](https://arxiv.org/pdf/2508.14704)
- **LiveMCPBench: "Can Agents Navigate an Ocean of MCP Tools?"** (Mo, Zhong, Chen, … Han, Sun; arXiv 2508.01780; 3 Aug 2025, v2 26 Feb 2026)
  - 95 real-world daily tasks.
  - Ships a deployable suite of 70 servers / 527 tools, so no scattered API configurations are needed.
  - Uses an LLM-as-a-Judge that checks outcomes, which tolerates changing data and multiple valid solution paths.
  - 12 LLMs evaluated: Claude-Sonnet-4 reached 78.95% success, most models 30-50%.
  - Retrieval errors cause "nearly half of all failures." — [arXiv 2508.01780](https://arxiv.org/abs/2508.01780)
- **MCPToolBench++** (Fan, Ding, Zhang, Mo, Ant Group; arXiv 2508.07575; 11 Aug 2025)
  - Built on "over 4k MCP servers from more than 40 categories" collected from marketplaces and GitHub as of July 2025.
  - Covers single-step and multi-step tool calls.
  - Motivations listed: varied response formats, unpredictable success rates of real servers, context-window limits on tool count.
  - I could not retrieve its exact metric definitions; it is reportedly AST/Pass@K style, but this is unverified. — [arXiv 2508.07575](https://arxiv.org/abs/2508.07575)
- **MCP-Universe** (Luo, Shen, Yang, … Savarese, Xiong, Li, Salesforce AI Research; arXiv 2508.14704; 20 Aug 2025)
  - 6 domains: location navigation, repository management, financial analysis, 3D design, browser automation, web search.
  - 11 real MCP servers, 231 tasks.
  - Execution-based evaluators of three types:
    - format evaluators (compliance)
    - static evaluators (time-invariant content)
    - dynamic evaluators (fetch real-time ground truth)
  - Scores: GPT-5 43.72%, Grok-4 33.33%, Claude-4.0-Sonnet 29.44%.
  - Findings: input tokens grow quickly with each step (a long-context problem), agents are unfamiliar with how to use the servers, and Cursor does not beat plain ReAct. — [arXiv 2508.14704](https://arxiv.org/abs/2508.14704)
- **MCP-Bench** (Wang, Chang, Patel, … Bao, Siow, Accenture Center for Advanced AI / UC Berkeley; arXiv 2508.20453; 28 Aug 2025)
  - Scale: 28 servers, 250 tools; 104 tasks (56 single-server, 30 two-server, 18 three-server); 20 LLMs; up to 20 rounds per task.
  - "Fuzzy" task variants omit tool names; 10 distractor servers add more than 100 tools per task.
  - Hybrid scoring: rule-based trace checks plus an o4-mini judge (1-10 per sub-dimension, normalized to [0,1], 5 prompt shuffles averaged).
  - Top overall scores: gpt-5 0.749, o3 0.715, gpt-oss-120b 0.692, gemini-2.5-pro 0.690, claude-sonnet-4 0.681; lowest llama-3.1-8b 0.428.
  - Average effort: gpt-5 used 9.2 rounds / 78.9 tool calls per task, llama-3.1-8b 17.3 rounds / 155.6 calls. — [arXiv 2508.20453](https://arxiv.org/html/2508.20453)
- **MCP-AgentBench** (Guo, Xu, Zhu, Hong, Wang, Mao; arXiv 2509.09734; 10 Sep 2025)
  - Testbed of 33 operational servers / 188 tools; 600 queries in 6 complexity categories.
  - Evaluated with "MCP-Eval," an outcome-oriented method; the judge details were not in the abstract.
  - Do not confuse it with a different paper, **MCPAgentBench** (arXiv 2512.24565). — [arXiv 2509.09734](https://arxiv.org/abs/2509.09734); [arXiv 2512.24565](https://arxiv.org/html/2512.24565v1)
- **MCPMark** (Wu, Liu, Zhang + 12 others; arXiv 2509.24002; 28 Sep 2025; ICLR 2026 poster)
  - 127 tasks co-created by experts and agents.
  - Each task has a curated initial state and a **programmatic verification script**, so no LLM judge is used.
  - Results:
    - gpt-5-medium: 52.56% pass@1, 33.86% pass^4
    - claude-sonnet-4 and o3: below 30% pass@1 and below 15% pass^4
  - Averages: 16.2 turns and 17.4 tool calls per task. — [arXiv 2509.24002](https://arxiv.org/abs/2509.24002); [ICLR 2026](https://iclr.cc/virtual/2026/poster/10006866)
- **OSWorld-MCP** (Alibaba; arXiv 2510.24563; Oct 2025): hybrid GUI+MCP benchmark with 158 MCP tools across 7 applications. — [arXiv 2510.24563](https://arxiv.org/html/2510.24563v1)
- **ETOM**: a five-level benchmark for tool orchestration in the MCP ecosystem (arXiv 2510.19423). Seen in search results only; details not retrieved. — [arXiv 2510.19423](https://arxiv.org/pdf/2510.19423)
- **MCP-SafetyBench**: safety evaluation of LLMs with real-world MCP servers (arXiv 2512.15163; Dec 2025). Seen in search results only. — [arXiv 2512.15163](https://arxiv.org/pdf/2512.15163)
- **MCP-Atlas** (Bandi, Dumitru + 21 others, Scale AI; arXiv 2602.00933; 31 Jan 2026, v3 19 May 2026)
  - 1,000 human-written and human-verified tasks (500 public / 500 private), 36 real servers, 220 tools, 3-6 tool calls per task.
  - Prompts never name tools or servers, and plausible distractors are present.
  - **Claim-level rubric**: the final answer is checked against atomic factual claims grounded in tool outputs, so alternative tool paths still get credit.
  - 20 frontier models: pass rates reach 82.2% at a 0.75 claim-coverage threshold.
  - Failures sorted into an 11-category taxonomy; 63.3% of diagnosed failures were "cognitive" (understanding, synthesis, parsing, stopping), not tool-call failures.
  - Code: github.com/scaleapi/mcp-atlas. — [arXiv 2602.00933](https://arxiv.org/abs/2602.00933)
- **DynamicMCPBench** (Kamiński et al.; arXiv 2607.20531; 10 Jul 2026, v2 31 Aug 2026; accepted to EMNLP 2026)
  - Framework that generates goals, runs them live against MCP servers, and distills the successful trajectory into "path-agnostic effect checkpoints." Agents are scored on reproducing those effects, not on the final answer.
  - Scale: 24 models, 121 servers, 750 tasks (15 categories × 50), scored with **pass^3** (all three attempts must succeed).
  - Results: the best agents solve about 50%; 31% of tasks are solved by no model; accuracy falls from 39% on the shortest tool chains to 13% on the longest.
  - Agreement with human judgment: 0.76 (chance-corrected). — [arXiv 2607.20531](https://arxiv.org/abs/2607.20531)
- **Other 2026 MCP-based benchmarks** seen in an arXiv listing (Oct 2026); abstract numbers only, not deeply verified:
  - RecToolBench (2609.30717): more than 1,200 tasks, 13 MCP servers, 32 tools.
  - ToolVerse (2607.15660): about 400 MCPs, about 4,500 tools.
  - CivBench (2609.02459): 76 MCP tools.
  - MCP hardware-design benchmark (2608.26199).
  - Cartograph (2609.30293): retrieval over 22 servers / 374 tools exposed as 3 proxy tools; R@5 0.816 vs 0.592 baseline; 475 vs 42,450 tokens.
  - — [arXiv listing](https://arxiv.org/search/?query=%22Model+Context+Protocol%22+benchmark&searchtype=abstract&abstracts=show&order=-announced_date_first&size=200)

### Inferences
- The evaluation methodology has been moving away from LLM-as-judge on final answers (MCPEval, LiveMCPBench, MCP-Bench's judge half) toward deterministic verification:
  - programmatic state checks (MCPMark, MCPWorld)
  - claim rubrics (MCP-Atlas)
  - effect checkpoints with pass^k (DynamicMCPBench)

  Two reasons are visible in these papers: judges disagree with humans, and live data drifts.
- Benchmarks almost all evaluate the **LLM/agent**, with the MCP servers held fixed. Only the description-smell and ecosystem papers treat the **server** as the object being evaluated.

### Gaps
- I did not retrieve exact metric definitions for MCPToolBench++, MCPEval or MCP-AgentBench, nor the LiveMCPBench judge model or its human-agreement figures.
- MCP-SafetyBench and ETOM were not examined.

## Q2. Which metrics are used?

### Takeaway
Common metrics:
- task success / pass@1, pass@k, pass^k
- tool-name validity / tool selection accuracy
- schema compliance / parameter accuracy
- execution success rate
- rounds, tool calls and token usage (efficiency)
- LLM-judge rubric scores (fulfillment, grounding, planning)
- retrieval recall@k

Latency is rarely a headline metric.

### Cited Findings
- **MCP-Bench rule-based metrics** (computed from execution traces):
  - Valid Tool Name Rate: share of calls that name an existing tool.
  - Schema Compliance: share of valid-tool calls whose parameters match the input schema.
  - Execution Success: share of calls that run without runtime error.
- **MCP-Bench LLM-judge dimensions**: Task Fulfillment, Information Grounding, Tool Appropriateness, Parameter Accuracy, Dependency Awareness, Parallelism & Efficiency. — [MCP-Bench](https://arxiv.org/html/2508.20453)
- **MCP-RADAR**: answer correctness, operational accuracy, computational resource efficiency, successful tool-invocation rounds. — [arXiv 2505.16700](https://arxiv.org/abs/2505.16700)
- **MCPMark**: pass@1, pass@4, pass^4 (consistency across repeated runs), average turns, average tool calls. — [arXiv 2509.24002](https://arxiv.org/abs/2509.24002)
- **DynamicMCPBench**: pass^3 over effect checkpoints, plus agreement with human judgment (0.76). — [arXiv 2607.20531](https://arxiv.org/abs/2607.20531)
- **MCP-Atlas**: claim coverage threshold (for example 0.75) and failure-taxonomy shares. — [arXiv 2602.00933](https://arxiv.org/abs/2602.00933)
- **MCP-Zero and Cartograph**: token consumption (−98% for MCP-Zero; 475 vs 42,450 tokens for Cartograph), retrieval recall@5, added latency (+5 ms, 0.8%). — [MCP-Zero](https://arxiv.org/abs/2506.01056); [arXiv listing, Cartograph 2609.30293](https://arxiv.org/search/?query=%22Model+Context+Protocol%22+benchmark&searchtype=abstract&abstracts=show&order=-announced_date_first&size=200)
- **Server-side metrics** (Afsar 2609.10962): initialize-handshake success rate, fatal JSON Schema violation count, safety-annotation omission rate, description near-duplication by cosine similarity. — [arXiv 2609.10962](https://arxiv.org/abs/2609.10962)

### Inferences
- Rule-based metrics need only the trace and the tool list, so they are cheap: name validity, schema compliance, execution success, handshake, schema validity. MCP-Bench shows they can sit next to LLM-judge metrics in a single score.

### Gaps
- Latency and dollar cost per task are seldom reported as first-class metrics in these benchmarks. I found none in the MCP-Bench, MCPMark or DynamicMCPBench abstracts.

## Q3. What do studies find about tool description quality and its effect on agent success?

### Takeaway
Poor descriptions are close to universal: 97.1% of 856 tools in 103 servers had at least one smell, and across 10,831 servers repeated tool names affected about 73%. Fixing descriptions has a measurable but modest and uneven effect:
- +5.85 pp median task success, at the price of +67% steps and regressions in 16.67% of cases
- +8.8 to +11.6% in tool selection under mutations
- 72% vs 20% selection probability among functionally equivalent servers

### Cited Findings
- **"Model Context Protocol (MCP) Tool Descriptions Are Smelly! Towards Improving AI Agent Efficiency with Augmented MCP Tool Descriptions"** (Hasan, Li, Rajbahadur, Adams, Hassan; arXiv 2602.14878; 16 Feb 2026, v3 31 May 2026)
  - Data: 856 tools across 103 servers.
  - Rubric with six components, each scored 1-5; a score below 3 counts as a smell:
    - Purpose → Unclear Purpose
    - Guidelines → Missing Usage Guidelines
    - Limitations → Unstated Limitations
    - Parameter Explanation → Opaque Parameters
    - Length/Completeness → Underspecified
    - Examples → Exemplar Issues
  - Prevalence: 97.1% of tools have at least one smell; 56% have Unclear Purpose. — [arXiv 2602.14878](https://arxiv.org/abs/2602.14878)
  - Scanner: an LLM-as-Jury of gpt-4.1-mini, claude-haiku-3.5 and qwen3-30b-a3b, with scores averaged.
    - Agreement between models (ICC): 0.62 (Examples) to 0.90 (Parameters).
    - Agreement with 2 human raters on 90 tools: weighted κ 0.72-0.89. — [HTML 2602.14878](https://arxiv.org/html/2602.14878)
  - Augmentation experiment:
    - Setup: run on MCP-Universe (231 tasks, 202 tools) with GPT-4.1, Qwen3-Coder-480B, GLM-4.5, plus Qwen3-Next-80B.
    - Gains: median +5.85 pp success rate; +15.12% evaluator score / partial goal completion.
    - Costs: steps +67.46%; regressions in 16.67% of cases.
    - Compact variants with fewer components often kept reliability while cutting token overhead.
  - Cost: a full MCP-Universe run is estimated at 200-300M tokens, about $75-$600 depending on provider. — [HTML 2602.14878](https://arxiv.org/html/2602.14878); [abs](https://arxiv.org/abs/2602.14878)
- **"From Docs to Descriptions: Smell-Aware Evaluation of MCP Server Descriptions"** (Peiran Wang, Ying Li, Yuqiang Sun, Chengwei Liu, Yang Liu, Yuan Tian; arXiv 2602.18914; 21 Feb 2026)
  - Data: 10,831 servers from GitHub, MCP.so, Glama, PulseMCP and Smithery, collected around March 2025.
  - Standard: 4 dimensions (accuracy, functionality, completeness, conciseness) and 18 smells.
  - Detection pipeline:
    - AST extraction of tool metadata from code
    - gpt-4o-mini comparing each description with its code to list candidate problems
    - incremental card sorting into categories, with manual mapping to the standards
    - no agreement statistics reported
  - Prevalence, as counts / approximate % of 10,831:

    | Smell | Count | ≈% |
    |---|---|---|
    | Repeated tool names | 7,894 | 72.9 |
    | Confusing functional description | 3,572 | 33.0 |
    | Wrong parameter meaning | 3,449 | 31.8 |
    | No description of return values | 3,093 | 28.6 |
    | No trigger conditions | 2,972 | 27.4 |
    | Clutter with irrelevant details | 2,904 | 26.8 |
    | Confusing trigger conditions | 1,583 | 14.6 |
    | No parameter description | 1,285 | 11.9 |
    | Unclear boundaries | 1,137 | 10.5 |

    The percentages are a summarizer's computation; only the 73% figure is stated in the paper.
  - The authors call this a "code-first, description-last" pattern.
  - Mutation study (gpt-4o-mini as tool selector; 1,000 queries over 10 server types):
    - Smells significantly affect selection (p < 0.001).
    - Largest effects: functionality +11.6%, then accuracy +8.8%.
  - Competition study (10 groups of 5 equivalent servers, 1,000 queries): standard-compliant descriptions reached 72% selection probability vs a 20% baseline (+260%). — [abs](https://arxiv.org/abs/2602.18914); [HTML](https://arxiv.org/html/2602.18914)
- **Afsar 2609.10962** (random registry draw)
  - Across 2,766 tools from 195 running servers: zero fatal JSON Schema violations.
  - The real problem is optional metadata: safety annotations are omitted on 58.8% of tools in a random draw vs 41.5% in a curated frame.
  - Description near-duplication: 2.8% at cosine 0.70, all within single servers, 0.0% across authors.
  - Benchmark corpora are far more repetitive: BFCL v4 16.7% near-duplicates; raw BFCL rows are 68.8% exact repeats and raw UltraTool 85.6%, vs 0.4% for real MCP. — [arXiv 2609.10962](https://arxiv.org/abs/2609.10962)
- **MCP-Universe**: agents "lack familiarity with the precise usage of MCP servers," which points to documentation and description quality as a bottleneck. — [arXiv 2508.14704](https://arxiv.org/abs/2508.14704)
- **Related claims I did not verify**:
  - "Agents Don't Paginate" (2608.26130): on SWE-bench Verified, a phrasing change lifted p1 from 24.2% to 35.0%, while metadata signals cost −4.8 pts. This shows that the wording of tool interfaces moves results.
  - Closed-World Resolution (2609.19425): counted 154 MCP tool hallucinations. — [arXiv listing](https://arxiv.org/search/?query=%22Model+Context+Protocol%22+benchmark&searchtype=abstract&abstracts=show&order=-announced_date_first&size=200)

### Inferences
- The two smell studies disagree on scale. One finds 97% of tools smelly (strict LLM-jury rubric, 103 popular servers); the other gives per-smell rates of about 1-73% (gpt-4o-mini plus card sorting, 10,831 servers). "% poor descriptions" therefore depends heavily on the rubric and the threshold.
- Better descriptions trade success against cost (+67% steps). A description-quality score for a server should probably reward compactness, not only completeness.

### Gaps
- Neither smell paper gives a cost per server or per tool for its scanner.
- I found no study that uses purely rule-based (non-LLM) description linting and validates it against agent success.

## Q4. Ecosystem-scale studies measuring thousands of servers

### Takeaway
Registries are large but noisy:
- about half of listed entries are invalid or low-value
- only about 49% of randomly sampled npm/stdio servers finish an MCP initialize handshake
- 66% have code smells; 5.5% show tool poisoning

All of these studies run largely without LLMs, using crawlers, static analyzers and live handshakes.

### Cited Findings
- **"MCP at First Glance: Studying the Security and Maintainability of MCP Servers"** (Hasan, Li, Fallahzadeh, Rajbahadur, Adams, Hassan; arXiv 2506.13538; 16 Jun 2025, v5 13 Apr 2026)
  - 1,899 open-source servers: 343 official plus 1,556 mined from GitHub.
  - Method: hybrid pipeline of a general static analyzer plus an MCP-specific scanner. The tools are not named on the abstract page.
  - Health: "strong health metrics."
  - Security and quality:
    - 8 distinct vulnerabilities, only 3 of which overlap with traditional software vulnerabilities
    - general vulnerabilities in 7.2% of servers
    - tool poisoning in 5.5%
    - code smells in 66%
    - 10 known bug patterns in 14.4% — [arXiv 2506.13538](https://arxiv.org/abs/2506.13538)
- **"A Measurement Study of Model Context Protocol Ecosystem"** (Guo, Hao, Zhang, Xu, Lv, Chen, Cheng; arXiv 2509.25292; 29 Sep 2025, v3 15 Nov 2025)
  - MCPCrawler covered 6 markets in a 14-day campaign: 17,630 raw entries yielded 8,401 valid projects (8,060 servers, 341 clients).
  - "More than half of listed projects are invalid or low-value."
  - Risks found: dependency monocultures (for example, Java servers built mostly on Spring) and uneven maintenance. A search snippet cited 8,656 (49.1%) valid entries; the abstract says 8,401 valid projects, so the snippet figure may come from another version. — [arXiv 2509.25292](https://arxiv.org/abs/2509.25292); [HTML v1](https://arxiv.org/html/2509.25292v1)
- **MCPZoo** (Wu, Chen, Hong, … Pan, Dai, Yang; arXiv 2512.15144; 17 Dec 2025)
  - 129,059 server entries (56,053 distinct).
  - 16,356 instances "deployed and verified as runnable and interactable," with no manual deployment needed. — [arXiv 2512.15144](https://arxiv.org/abs/2512.15144)
- **"What a Random Draw from the MCP Registry Contains"** (Afsar; arXiv 2609.10962; 10 Sep 2026)
  - Census of 24,135 registry servers; a seeded random sample of 400 npm/stdio servers was probed live.
  - Results:
    - 48.8% completed initialize, vs 66.7% for a hand-curated frame measured with the same instrument
    - the dominant failure was "never starts" (37.5%), not missing credentials (13.3%)
    - zero fatal schema violations across 2,766 tools
  - No LLM appears in the pipeline. Code: github.com/itguruhaseeb/mcp-probe (Zenodo-archived).
  - The author argues that curated or repaired samples overstate quality. — [arXiv 2609.10962](https://arxiv.org/abs/2609.10962)
- **"From REST to MCP"** (arXiv 2507.16044): empirical study of API wrapping and automated MCP server generation. — [arXiv 2507.16044](https://arxiv.org/html/2507.16044v4)
- **"An Empirical Study of MCP Applications"** (arXiv 2607.25635): studies how 2,297 GitHub client applications configure and use servers. — [arXiv 2607.25635](https://arxiv.org/html/2607.25635v1)
- **Scale context**:
  - LiveMCPBench cites "more than 10,000 MCP servers" (Aug 2025). — [arXiv 2508.01780](https://arxiv.org/abs/2508.01780)
  - MCPToolBench++ crawled more than 4k servers (Jul 2025). — [arXiv 2508.07575](https://arxiv.org/abs/2508.07575)

### Inferences
- Availability ("does it start and answer `initialize`/`tools/list`") is the first-order quality signal; only about half of random servers pass it.
- Schema validity is close to a non-issue among servers that start. The better differentiators are description and annotation completeness, plus maintenance signals (commit recency, dependency health).

### Gaps
- I did not retrieve the specific maintenance or availability percentages from Guo et al.'s full text (stars, last-commit distributions), nor the names of the static tools used by Hasan et al.

## Q5. Which methods run fully automatically without an LLM, which need one, and what is the approximate cost?

### Takeaway
- **No LLM needed**:
  - registry crawling
  - live handshake / `tools/list` probing
  - JSON Schema validation
  - static code and security analysis
  - embedding-based duplicate detection (needs an embedding model, not a generative LLM)
  - programmatic task verifiers once the tasks exist
- **LLM needed**:
  - description-smell scoring (LLM jury / gpt-4o-mini)
  - LLM-as-judge benchmarks
  - every agent task run

Full agent benchmarks are expensive: a full MCP-Universe run is about 200-300M tokens, roughly $75-600, and many real servers need third-party credentials.

### Cited Findings
- **No-LLM methods**:
  - Afsar's probe (handshake, schema, annotations, cosine dedup) is fully scripted and reproducible from a seed. — [arXiv 2609.10962](https://arxiv.org/abs/2609.10962)
  - Hasan et al. 2506.13538 used static analysis plus an MCP-specific scanner. — [arXiv 2506.13538](https://arxiv.org/abs/2506.13538)
  - MCPCrawler measured 6 markets over 14 days. — [arXiv 2509.25292](https://arxiv.org/abs/2509.25292)
- **Deterministic verification of agent runs**:
  - MCPMark: per-task programmatic verification scripts. — [arXiv 2509.24002](https://arxiv.org/abs/2509.24002)
  - MCP-Universe: execution-based format, static and dynamic evaluators. — [arXiv 2508.14704](https://arxiv.org/abs/2508.14704)
  - MCPWorld: white-box app state monitoring. — [arXiv 2506.07672](https://arxiv.org/pdf/2506.07672)
  - DynamicMCPBench: effect checkpoints. An LLM is still the agent under test, and its trajectories are recorded by running live. — [arXiv 2607.20531](https://arxiv.org/abs/2607.20531)
- **LLM-dependent methods**:
  - MCP-Bench judge: o4-mini with 5 prompt shuffles per task. — [MCP-Bench](https://arxiv.org/html/2508.20453)
  - LiveMCPBench: LLM-as-judge. — [arXiv 2508.01780](https://arxiv.org/abs/2508.01780)
  - Smelly-descriptions scanner: a 3-model jury of gpt-4.1-mini, claude-haiku-3.5, qwen3-30b-a3b. — [HTML 2602.14878](https://arxiv.org/html/2602.14878)
  - Docs-to-Descriptions: gpt-4o-mini plus AST extraction. — [HTML 2602.18914](https://arxiv.org/html/2602.18914)
- **Human labels**:
  - MCP-Atlas: 1,000 tasks written and verified by experts. — [arXiv 2602.00933](https://arxiv.org/abs/2602.00933)
  - MCPMark: tasks co-created by experts and agents. — [arXiv 2509.24002](https://arxiv.org/abs/2509.24002)
  - Smelly paper: a 90-tool human validation sample. — [HTML 2602.14878](https://arxiv.org/html/2602.14878)
  - DynamicMCPBench: validation against humans (agreement 0.76). — [arXiv 2607.20531](https://arxiv.org/abs/2607.20531)
- **Cost**: a full MCP-Universe run is estimated at 200-300M tokens, about $75-$600 by provider (cited prices: Qwen3-Next $0.10/M tokens, Kimi-K2 $0.456/M). — [HTML 2602.14878](https://arxiv.org/html/2602.14878)
- **Effort per task**: MCP-Bench's gpt-5 averages 78.9 tool calls per task; MCPMark averages 17.4 calls and 16.2 turns. — [MCP-Bench](https://arxiv.org/html/2508.20453); [MCPMark](https://arxiv.org/abs/2509.24002)
- **Credentials and setup**:
  - Missing credentials blocked 13.3% of randomly sampled servers. — [arXiv 2609.10962](https://arxiv.org/abs/2609.10962)
  - LiveMCPBench ships a deployable 70-server suite specifically to avoid "scattered API configurations." — [arXiv 2508.01780](https://arxiv.org/abs/2508.01780)

### Inferences
- **No-LLM checks**: per-server cost is effectively compute only. Seconds to minutes per server for a handshake plus `tools/list`, schema validation and static analysis.
- **LLM-jury description scoring**: likely around $0.001-0.01 per tool with mini-class models. This is my estimate, not a sourced figure; it assumes about 1-2k tokens per tool per judge with 3 judges.
- **Agent-task evaluation**: likely dollars to hundreds of dollars per benchmark run. Per server, the cost depends on how many tasks touch that server. This is an inference from the $75-600 per MCP-Universe run for 11 servers, roughly $7-55 per server-run.
- A practical tiered pipeline:
  1. automatic liveness / schema / annotation / static checks for every server
  2. cheap LLM description scoring
  3. expensive agent task runs only for a subset

### Gaps
- No paper I found reports explicit dollar cost per server for evaluation.
- Credential requirements per benchmark (for example which MCP-Universe servers need GitHub or Maps keys) were not verified.
