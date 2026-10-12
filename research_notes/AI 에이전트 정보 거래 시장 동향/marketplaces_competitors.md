# AI Agent Marketplaces, Directories, Brokers & Discovery Services: Competitive Landscape (as of Oct 12, 2026)

Context: competitors for an "agent introduction gateway" that finds the best agent/API for a requesting agent (first introduction free, later re-introductions to better agents for a USDC fee). Research date: 2026-10-12. Sources are a mix of primary (company docs/blogs) and secondary (crypto/fintech press, analytics posts); secondary-only or vendor-authored claims are flagged.

## 1. Who the discovery/marketplace players are: what they do, business model, volume, funding, 2026 news

### Takeaway
The closest live analogues are Coinbase's x402 Bazaar + Agentic.Market (an auto-indexed discovery layer for paid x402 endpoints, free to use), Virtuals ACP (agent-to-agent job marketplace with a "Butler" routing agent), Fetch.ai Agentverse/ASI:One (agent directory + LLM router), and Olas Mech Marketplace (agent-to-agent task market, 15% fee). Payment-rail startups (Skyfire, Payman, Natural, Catena, Sapiom, Kite, Crossmint, Nevermined) are well funded in 2025–2026 but mostly sell wallets/identity/checkout, not discovery. Enterprise stores (Salesforce AgentExchange, AWS, Google, Microsoft) and MCP directories (Smithery, Glama, mcp.so, Composio, Pipedream) are catalogs for humans/developers, not agent-to-agent brokers.

### Cited Findings

**A. Crypto-native discovery / agent-to-agent marketplaces**

*Coinbase x402 Bazaar + Agentic.Market*
- Agentic.Market launched April 20, 2026 as a public marketplace for discovering, comparing and integrating x402-compatible services. No account/login needed; humans browse on the web, agents query the same data via MCP APIs. — [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402); [Crypto Briefing, Apr 20 2026](https://cryptobriefing.com/agentic-market-ai-agents-hub/)
- Bazaar is the backend index: when the CDP Facilitator settles a payment on an x402 endpoint with the Bazaar discovery extension enabled, it extracts and indexes that endpoint's metadata. Providers don't register separately. Coinbase calls it "self-learning" (it indexes from live payment traffic). — [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402)
- Listings at launch: 70+ curated services plus "thousands" of auto-detected ones, in 7 categories (Inference, Data, Media, Search, Social, Infrastructure, Trading). Examples include OpenAI, Venice, ElevenLabs, CoinGecko, Nansen, Allium, Bloomberg, Google Maps, Firecrawl, Browserbase and Exa. — [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402)
- Coinbase's x402 headline metrics at launch (Apr 2026): 165M+ cumulative transactions, ~$50M volume, 480,000+ transacting agents. In February 2026 (Agentic Wallets launch) the figure was 50M+ transactions. — [Crypto Briefing](https://cryptobriefing.com/agentic-market-ai-agents-hub/)
- June 2026: Coinbase and AWS let CloudFront publishers make their endpoints discoverable in Bazaar. Massive (market data) lists x402 routes that show up in Bazaar and Agentic.Market. — [Coinbase blog](https://www.coinbase.com/blog/coinbase-and-aws-let-publishers-accept-agents-as-customers-via-x402); [Massive](https://massive.com/blog/x402-payments-for-ai-agents)
- Fees: no marketplace or listing fee found in any source (Agentic.Market is positioned as "something that feels like a public utility"). — [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402)
- An independent scan of the x402 catalog covered 24,243 of 25,770 active endpoints. 53% scored "level 0" on Cloudflare's agent-readiness scanner. — [x402station](https://x402station.io/blog/cloudflare-x402-readiness) (small independent blog; unverified)

*Virtuals Protocol: Agent Commerce Protocol (ACP) + Butler*
- ACP is an agent-to-agent job marketplace (requestor, provider and evaluator roles) with USDC pricing since Aug 12, 2025. Butler is a consumer-facing agent that hires ACP agents on the user's behalf. Since Sep 5, 2025, Butler auto-retries with the "next best agent" after a failed job. — [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs)
- Metrics (page updated Oct 1, 2026): 81,908 agents launched, 2.5M jobs, 35.75K unique active wallets, 481.79M USDC "agentic GDP" (value processed, not revenue), 4.5M USDC total revenue. DeFiLlama fees: $74.32M all-time but only $0.62M in the last 30 days. — [CoinStats, Oct 2026](https://coinstats.app/ai/a/investment-analysis-virtual-protocol) (aggregator)
- Q1 2026: ~$479M agentic GDP, 1.77M jobs, 18,000+ agents. — [bex.co, Apr 4 2026](https://bex.co/blog/2026/04/04/virtuals-protocol-ai-economic-operating-system-on-chain-agent-economy) (secondary blog)
- Cumulative ACP commerce memos on Base: 12,361,002 as of Oct 12, 2026. The latest daily figures shown that day were 28 memos and 5 unique senders (possibly a partial UTC day). The tracker warns that memos are not completed purchases. — [agenteconomy.to](https://agenteconomy.to/virtuals-acp)
- Feb 2026: Virtuals launched the "Virtuals Revenue Network" (up to $1M/month distributed to agents selling via ACP). Mar 24, 2026: ACP announced for Arbitrum. — [search summary of bex.co / Virtuals coverage](https://bex.co/blog/2026/04/18/virtuals-protocol-arbitrum-agent-commerce-protocol-l2-choice). However, the ACP v2.0 changelog (Apr 2026) lists only Base Mainnet, Base Sepolia and BSC Testnet, not Arbitrum, so the two sources conflict. — [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs)
- Apr 2026 (ACP v2.0): the CLI `acp serve` deploys handlers as "x402, MPP, and ACP native endpoints," so Virtuals is converging with x402. — [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs)
- VIRTUAL token: roughly $0.70–0.80 in Oct 2026, ~84–86% below its $5.07 ATH. — [CoinStats](https://coinstats.app/ai/a/investment-analysis-virtual-protocol)

*Olas (Autonolas) Mech Marketplace + Pearl*
- The Mech Marketplace is an agent-to-agent market where agents hire "mechs" (AI tools/agents) for tasks, paid on-chain, deployed across 7 chains. Pearl is marketed as "The AI Agent App Store." — [Olas Mech](https://olas.network/agent-economies/mech); [Olas Q2 2026](https://olas.network/blog/q2-2026)
- Live counter as of Oct 12, 2026: 14,774,924 agent-to-agent transactions, $109,907.89 all-time marketplace turnover, and $851.55 all-time protocol fees (741.49 xDAI + 109.67 USDC + dust ETH). — [Olas Mech page via search snippet](https://olas.network/agent-economies/mech) (figures read from a search summary of the live page)
- Q2 2026 (Jul 1, 2026): 18.2M+ lifetime transactions, 13.2M+ of them agent-to-agent. Agents can now send requests off-chain (~a quarter of requests per one source); payment still settles on-chain. — [Olas Q2 2026](https://olas.network/blog/q2-2026)
- Volume is concentrated: a few mechs serving Olas's own prediction-market trader agents account for most of it. An independent dev analysis titled "2.1M micro-transactions, $104K total" makes the same point. — [DEV Community](https://dev.to/jiahui-miao/21m-micro-transactions-104k-total-what-the-data-says-about-the-agent-economy-n9g); [Olas blog on spam question](https://olas.network/blog/20-million-olas-agent-transactions)

*Fetch.ai Agentverse + ASI:One*
- Agentverse is an open agent directory/marketplace. ASI:One is an LLM chat/search interface that "interprets each query and routes it to the most relevant Agent function." Agents must be registered on Agentverse to appear in ASI:One. — [Agentverse docs](https://docs.agentverse.ai/documentation/search-for-agents/find-ai-agents); [Agentverse overview](https://docs.agentverse.ai/documentation/getting-started/overview)
- VentureBeat framed ASI:One as "The Google Search of AI agents," launching in beta alongside a Business tier, with Agentverse hosting >2M agents. — [VentureBeat](https://venturebeat.com/ai/the-google-search-of-ai-agents-fetch-launches-asi-one-and-business-tier-for)
- Crypto Briefing (June 14, 2026) reported ~2.7–3M registered agents. These are registration counts, not active agents (unverified). — [Crypto Briefing](https://cryptobriefing.com/fetch-ai-agent-marketplace-3-million-agents/)
- Nov 19, 2025: Fetch launched personalized multi-agent consumer tasks and a "Claim your agent" program against brand knock-offs. — [BusinessWire](https://www.businesswire.com/news/home/20251119088395/en/fetch-combines-personalized-ai-with-multi-agent-collaboration-to-handle-complex-consumer-tasks-launches-claim-your-agent-to-fight-brand-knock-offs)
- Reliability: a public GitHub issue reports that ASI:One cannot reach an active external proxy agent (the proxy resolver returns HTTP 500). — [GitHub issue #118](https://github.com/fetchai/agentverse/issues/118)

*Kite AI*
- Kite (formerly Zettablock) raised an $18M Series A (co-led by General Catalyst and PayPal Ventures) in Sept 2025, bringing its total to $33M. — [CoinDesk, Sep 2 2025](https://www.coindesk.com/business/2025/09/02/kite-raises-usd18m-to-bridge-stablecoin-payments-and-autonomous-agents)
- Mainnet and "Kite Agent Passport" (identity + payments) launched Apr 30, 2026; TokenPost describes it as Avalanche-based. — [The Block PR](https://www.theblock.co/press-releases/kite-launches-kite-chain-and-kite-agent-passport-enabling-autonomous-ai-agent-payments-399534); [TokenPost](https://tokenpost.com/news/technology/20518)
- Kite AIR includes an "Agent App Store" where agents programmatically discover and buy APIs and compute. This is described only in a pre-mainnet (Mar 2026) blog, and live status is unconfirmed. KITE was meant to be used for "AI services commissions." — [bex.co Mar 2026](https://bex.co/blog/2026/03/10/kite-ai-payment-l1-purpose-built-blockchain-ai-agent-economy); [Gate](https://www.gate.com/news/detail/15489848)
- Apr 2026: reported as the first crypto L1 inside Google's Agent Payments Protocol (AP2). — [bex.co Apr 22 2026](https://bex.co/blog/2026/04/22/kite-ai-l1-google-agent-payments-protocol-crypto-big-tech) (secondary)

**B. Agent payment rails / wallets (adjacent; mostly no discovery)**

- **Skyfire**: payments network plus "Know Your Agent" (KYA) identity and the KYAPay open protocol (Jun 2025). It raised $8.5M seed (Aug 2024); Tracxn lists $9.5M total (conflict). On Sept 30, 2026, Mastercard said it is working with Skyfire to extend KYA into Agent Pay. Its docs say USDC-on-Base funding is "near zero cost," and no KYAPay fee is published. — [TechCrunch 2024](https://techcrunch.com/2024/08/21/skyfire-lets-ai-agents-spend-your-money); [Tracxn](https://tracxn.com/d/companies/skyfire/__-gSNwLdAbLR2EH3jQO5ja24BZ2dqjmKWC_BS3-4pf1s); [FintechSpecs Sept 2026](https://fintechspecs.com/blog/mastercard-agent-pay-trust-intelligence-skyfire-kya-2026/); [BusinessWire KYAPay](https://www.businesswire.com/news/home/20250626772489/en/Skyfire-Launches-Open-KYAPay-Protocol-With-Agent-Checkout); [Skyfire docs](https://docs.skyfire.xyz/docs/wallet-funding)
- **Payman AI**: agentic banking and AI-to-human payouts. It has raised ~$13.8–14M total per aggregators (investors reportedly include Visa, Coinbase Ventures and Circle), with a $3M pre-seed in 2024. No 2026 round found. — [StartupHub](https://www.startuphub.ai/startups/payman-ai-1773747217006); [Tracxn](https://tracxn.com/d/companies/paymanai/__NSTYOZtZdNiGZxC0Vkul0dzUfj3ZUgPqDRNO08pHBUE/funding-and-investors) (aggregators; unverified)
- **Natural**: a $9.8M seed (Abstract and Human Capital; Oct 2025), then a $30M Series A led by Forerunner (Jul 2026), for >$40M total. It has six live products, including FDIC-insured agent wallets and receive-only "vaults." — [BusinessWire Oct 23 2025](https://www.businesswire.com/news/home/20251023151615/en/Fintech-Natural-Launches-With-$9.8M-Seed-Round-to-Power-Agentic-Payments); [FinTech Futures](https://www.fintechfutures.com/venture-capital-funding/natural-bags-30m-launches-agentic-payments-infrastructure); [The Next Web](https://thenextweb.com/news/natural-series-a-agentic-payments-ai-agents)
- **Catena Labs** (Sean Neville, Circle co-founder): a $30M Series A co-led by Acrew and a16z crypto (May 20, 2026), after an $18M seed, for $48M total (StartupHub says $36M; conflict). It filed for an OCC national trust bank charter. — [Fortune May 20 2026](https://fortune.com/2026/05/20/catena-labs-series-a-sean-neville-ai-native-bank/); [Crypto Briefing](https://cryptobriefing.com/catena-labs-30m-series-a-bank-charter/)
- **Sapiom**: a single integration that handles identity, wallets, policy, metering, billing and settlement so agents can buy APIs/SaaS. It raised a $15.75M seed led by Accel (investors include Anthropic, Coinbase Ventures, Okta Ventures and Menlo; TechCrunch Feb 5, 2026 says $15M). One aggregator reports a later $35M Series A (Dragonfly, Accel, Anthropic, Coinbase), date unconfirmed. — [Sapiom blog](https://www.sapiom.ai/blog/sapiom-raises-15m); [TechCrunch Feb 5 2026](https://techcrunch.com/2026/02/05/sapiom-raises-15m-to-help-ai-agents-buy-their-own-tech-tools); [Signalbase (unverified Series A)](https://www.trysignalbase.com/news/funding/sapiom-raises-350m-series-a-for-ai-agent-payments)
- **Crossmint**: agent wallets plus stablecoin rails. It launched an agentic card payments API on Visa Intelligent Commerce and Basis Theory (Jun 2, 2026) and the Agent Commerce Toolkit (agents pay with any card at any online store; Oct 8, 2026). — [Crossmint](https://www.crossmint.com/announcement/agentic-cards-api-launch-visa-basistheory); [GlobalFintechSeries](https://globalfintechseries.com/banking/digital-payments/crossmint-launches-agent-commerce-toolkit-enabling-ai-agents-to-pay-with-any-card-and-check-out-online-through-one-integration/)
- **Nevermined** (Zug, Switzerland): agent payments, metering and MCP monetization. Fees per its own site and blog are 1–2% on settled volume for merchants (1% stablecoin, 2% card), plus a 2% buyer charge on external services. Sources conflict, and all are vendor-authored. It integrated Visa Intelligent Commerce and x402 in Apr 2026. No funding round found. — [Nevermined home](https://nevermined.ai/); [Nevermined blog](https://nevermined.ai/blog/monetization-strategies-ai-voice-agents); [Nevermined 2026 platforms post](https://nevermined.ai/blog/best-platforms-agentic-payments)
- **Proxy (proxyhq)**: an MCP server and skills for agent payment intents and policy-bound virtual cards (requires KYC/KYB). No funding or company profile found. — [getclawkit listing](https://getclawkit.com/skills/official-proxyhq-proxy-payments) (third-party listing)
- **Allowance** (YC Spring 2026): scoped payment credentials for agents. — [neuronfeed](https://neuronfeed.com/startups/allowance)
- **Halliday**: no 2025–2026 information found (see Gaps).

**C. MCP / tool marketplaces and registries**

- **Glama**: ~32,700–37,000 MCP servers indexed (mid-2026). It runs a gateway with OAuth, logging and per-tool access control. Freemium plans are $9/$26/$80 per month, and there is no published creator revenue share. — [SEOSiri, Sept 2026](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html) (vendor-authored; secondary); [MCP directory roundup](https://mentionagent.ai/blog/mcp-server-directories/)
- **Smithery**: ~6,000–7,300 servers, a registry with one-click hosted deployment, and a "Toolbox" meta-router (a tool router that picks servers for an agent; closest MCP analogue to the gateway). Payout status is contested: one source cites an 80% creator split, while a 2026 review says creators earn nothing. Founded Dec 2024 by Henry Mao; backed by South Park Commons (amount unknown). — [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html); [tooldirectory.ai](https://tooldirectory.ai/tools/smithery)
- **mcp.so**: 20,000+ servers, free to list, no monetization. — [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html)
- **Official MCP Registry**: a metadata-only registry (Anthropic, GitHub, PulseMCP, Microsoft) under the Linux Foundation's Agentic AI Foundation (Dec 9, 2025). No payouts. — [bestmcptools](https://bestmcptools.org/glama-vs-smithery); [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html)
- **Composio**: a managed integration catalog with 500+ integrations, priced from free to $229/mo. No 2026 funding found in searches. — [bestmcptools / Composio comparison](https://composio.dev/content/smithery-alternative)
- **Pipedream**: Workday signed a definitive agreement to acquire it on Nov 19, 2025 (5,000+ customers, 3,000+ connectors). The close was reported in Feb 2026, and terms were not disclosed. — [PR Newswire](https://www.prnewswire.com/news-releases/workday-signs-definitive-agreement-to-acquire-pipedream-302619298.html); [Pipedream blog](https://pipedream.com/blog/pipedream-to-be-acquired-by-workday/); [Wikipedia: Tod Sacerdoti](https://en.wikipedia.org/wiki/Tod_Sacerdoti)
- Ecosystem: >11,000 active public MCP servers (early 2026), and fewer than 5% of listed servers have a monetization path (single source, no methodology). — [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html)

**D. Big-tech / enterprise agent stores**

- **Salesforce AgentExchange**: in April 2026, AppExchange, Slack Marketplace and the Agentforce ecosystem merged into AgentExchange (the AppExchange brand is retired). It has ~13,000 listings (10,000+ apps, 2,600+ Slack, 1,000+ Agentforce agents/tools/MCP servers) and 200+ launch partners (Google Cloud, Docusign, Box). — [SalesforceDevops.net, Apr 14 2026](https://salesforcedevops.net/index.php/2026/04/14/agentexchange-salesforces-bet-that-trust-can-scale-with-agentic-speed/); [Futurum](https://futurumgroup.com/insights/can-agentexchange-cement-salesforces-lead-in-the-agentic-ai-platform-race/)
- **AWS Marketplace "AI Agents and Tools"**: listing docs exist for SaaS/API-based AI agent products. The take rate is reported as 3% for public SaaS offers and 1.5–3% for private offers, not officially published. Agentforce 360 for AWS was sold exclusively via AWS Marketplace (early 2026). — [AWS docs](https://docs.aws.amazon.com/marketplace/latest/userguide/listing-saas-ai-agents.html); [Suger](https://www.suger.io/resources/blog/ai-agents-on-aws-marketplace/); [Salesforce](https://www.salesforce.com/news/stories/agentforce-360-for-aws-announcement/)
- **Google Cloud / Gemini Enterprise agent marketplace**: 3% revenue share and no listing fee (secondary). Buyers need a Gemini Enterprise Standard+ seat (~$30/user/mo); the Business edition is excluded. — [Clazar](https://clazar.io/blog/google-cloud-marketplace-fees); [SeldonFrame](https://www.seldonframe.com/guides/ai-marketplace-fees-compared)
- **Microsoft Marketplace / Agent Store**: 11,000 models and 4,000+ AI apps and agents claimed. — [AI Agent Marketplaces 2026 blog](https://shaffaybajwa.com/ai-agent-marketplace/) (secondary)

**E. Standards relevant to discovery/reputation**

- **ERC-8004 (Trustless Agents)**: a Draft standard created Aug 2025 with Identity, Reputation and Validation registries. On-chain reputation is minimal; scoring, Sybil resistance and aggregation are left to off-chain systems. — [Ethereum Magicians](https://ethereum-magicians.org/t/erc-8004-trustless-agents/25098); [eco.com](https://eco.com/support/en/articles/13221214-what-is-erc-8004-the-ethereum-standard-enabling-trustless-ai-agents)
- An empirical study (registry events through May 13, 2026) found only 3–15% of ERC-8004 registrations expose a valid registration file with at least one service endpoint, concluding that "raw registration volume is a poor proxy." — [arXiv 2606.26028](https://arxiv.org/html/2606.26028)
- **x402 governance**: the protocol moved to the Linux Foundation's x402 Foundation. Sources conflict on the date: April 2, 2026 (announcement) vs. July 14, 2026 (launch with 40 members). This may be announcement vs. formal launch. — [Crypto Briefing](https://cryptobriefing.com/agentic-market-ai-agents-hub/); [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/)

### Inferences
- Agentic.Market/Bazaar is the most direct incumbent threat: it is free, indexes automatically from real payments, is MCP-queryable by agents, and is backed by Coinbase and AWS distribution. A paid broker must offer something Bazaar does not: outcome-based quality ranking, matching across protocols, and switching recommendations.
- Payment-rail startups have raised >$150M combined in 2025–26 (Catena $48M, Natural $40M+, Kite $33M, Sapiom $15.75M+, Payman ~$14M, Skyfire ~$9M) but focus on wallets, identity and checkout. They are likely partners or integration targets, not discovery competitors, though Sapiom and Kite's "Agent App Store" edge toward "agents buying APIs."
- No well-funded, dedicated "agent broker / router" startup surfaced in searches (see Gaps).

### Gaps
- Halliday: no 2025–2026 information on an agent-commerce product or funding was found.
- Proxy (proxyhq): no company profile or funding found.
- Smithery and Composio 2025–2026 funding amounts were not found in searches. Nevermined funding was not found.
- No official take rates were found for AWS, Microsoft or Salesforce AgentExchange (only secondary ~3% claims and "70–80% publisher payout" claims).
- No usage numbers (calls routed, revenue) exist for Agentic.Market, Agentverse/ASI:One or Smithery's Toolbox.
- Sapiom's $35M Series A is reported by only one aggregator, with no date.

## 2. Which players do routing/recommendation or quality ranking, and how they rank

### Takeaway
Only a few do actual routing: Virtuals Butler (with auto-retry to the "next best agent"), Fetch.ai ASI:One (LLM routes queries to the agent function it ranks highest), Smithery Toolbox (MCP meta-router) and Coinbase Bazaar (semantic search plus curated boost). Ranking signals are mostly popularity/usage and self-reported metadata. Virtuals is the only one with explicit outcome metrics (success rate, aGDP, ratings). None found routes on independent evals or price-performance across protocols.

### Cited Findings
- **Virtuals ACP** has the most sophisticated public ranking:
  - Graduation requires 10 successful sandbox transactions plus manual review (Jul 2025). Agents are auto-ungraduated after 10 consecutive expired jobs from at least 3 unique buyers (Sep 2025).
  - Star ratings and written reviews were added Oct 24, 2025. A "Top Agents" leaderboard ranks by aGDP, job volume, unique users and success rate (Nov 10, 2025).
  - Semantic search with a reranker based on success metrics arrived Nov 27, 2025. New agents receive "estimated values so they can compete" (a cold-start fix).
  - ERC-8004 on-chain identity and reputation came Feb 1, 2026, with reviews written on-chain. Butler auto-retries with the next best agent after a failure (Sep 5, 2025).
  - — [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs)
- **Fetch.ai Agentverse/ASI:One**:
  - Each agent gets a "Rating score" reflecting "popularity and usefulness," driven by how often it appears in search, how often it is used, and how well its content matches user needs. README/metadata quality affects discoverability.
  - Filters cover Active/Inactive, Verified/Unverified, protocol, tags, location and interaction thresholds (`has:interactions>` from 1k to 100m). ASI:One routes queries to the most relevant agent function.
  - — [Agentverse docs](https://docs.agentverse.ai/documentation/search-for-agents/find-ai-agents)
  - A PageRank-like "AgentRank" based on agent-to-agent call graphs is described only in a Digg post (unverified). — [Digg](https://digg.com/tech/okrug0vj)
- **Coinbase Bazaar/Agentic.Market**: curated services get human-readable metadata enrichment and rank higher; auto-detected services are reachable by semantic search. The index uses on-chain payment activity as a signal of a service's existence. — [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402); [Crypto Briefing](https://cryptobriefing.com/agentic-market-ai-agents-hub/)
- **Smithery Toolbox**: a "meta-router" over its registry. The ranking method is not public. — [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html)
- **Olas Mech Marketplace**: no ranking/reputation features mentioned in the Q2 2026 roundup. Its "Agent Economy Explorer" shows daily active agents, transactions and an "accuracy" metric (values not given). — [Olas Q2 2026](https://olas.network/blog/q2-2026)
- **ERC-8004 Reputation Registry**: deliberately leaves scoring and aggregation to off-chain systems, which leaves room for third-party reputation aggregators. — [eco.com](https://eco.com/support/en/articles/13221214-what-is-erc-8004-the-ethereum-standard-enabling-trustless-ai-agents); [arXiv 2606.26028](https://arxiv.org/html/2606.26028)
- **OpenRouter**: publishes "App & Agent Rankings" by token usage, a popularity list rather than reputation. — [OpenRouter](https://openrouter.ai/apps)
- Adjacent "broker" startups found are not agent routers. Archestra raised a $10M seed (20VC, Jun 2, 2026) to broker agent access to enterprise data; it is in production at 4 Fortune 500 companies. — [SiliconANGLE](https://siliconangle.com/2026/06/02/archestra-raises-10m-broker-ai-agent-access-corporate-data/)

### Inferences
- Ranking in the market is mostly usage-based (calls, interactions, aGDP). That is vulnerable to wash activity (see section 4), which makes usage counts a weak quality signal. A gateway that ranks on verified outcomes (task success, latency, price per successful result, evaluator attestations) would be differentiated.
- Virtuals' "auto-retry with next best agent" is functionally close to the proposed "re-introduction to a better agent," but it is free and confined to the ACP ecosystem.
- Cold start is a recognized problem: Virtuals assigns estimated metrics to new agents. A gateway's "first introduction free" could also serve as a structured evaluation/exploration mechanism.

### Gaps
- Fetch.ai's "Testing and Ranking" documentation page was not retrieved, so its exact formula is unknown.
- Coinbase's Bazaar ranking algorithm (beyond the curated boost and semantic search) is not documented in the sources found.
- No source was found on any player using independent benchmark evals for agent ranking.

## 3. Fees: listing fees, take rates, per-call

### Takeaway
Discovery is generally free; monetization happens on settlement. Crypto agent-to-agent markets take 10–15% (Olas 15%; Virtuals ~10% treasury plus 1% Butler fee, in older docs). Payment rails take ~1–2%. Cloud enterprise marketplaces take ~3%. MCP directories charge hosting subscriptions and rarely share revenue with creators.

### Cited Findings
| Player | Listing fee | Take rate / fee | Source |
|---|---|---|---|
| Coinbase Agentic.Market / Bazaar | None found (auto-indexed) | No marketplace fee found | [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402) |
| Olas Mech Marketplace | n/a | 15% protocol fee on agent-to-agent payments (live Q2 2026 via DAO vote; OLAS-denominated fees burned, others to treasury) | [Olas Q2 2026](https://olas.network/blog/q2-2026) |
| Virtuals ACP | n/a | Older breakdown: 60% to provider agent, 30% buyback/burn of the agent's token, 10% to Virtuals Treasury; 1% of Butler transactions to the G.A.M.E Treasury. Docs conflict; current schedule unverified. Since Nov 2025 fund-managed jobs can use %-of-principal pricing. Agent-token trading fee is 1% (70% creator / 30% treasury). | [Messari](https://messari.io/report/understanding-virtuals-protocol-a-comprehensive-overview); [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs); [CoinStats](https://coinstats.app/ai/a/investment-analysis-virtual-protocol) |
| Fetch.ai Agentverse | No fee mentioned in docs | Not published | [Agentverse docs](https://docs.agentverse.ai/documentation/search-for-agents/find-ai-agents) |
| Nevermined | n/a | 1–2% of settled volume (merchant) plus 2% buyer on external services (vendor-stated, inconsistent) | [Nevermined](https://nevermined.ai/) |
| Skyfire / Payman / Natural | n/a | Pricing not publicly published (as of Jun 2026) | [FintechSpecs](https://fintechspecs.com/blog/skyfire-vs-payman-vs-natural-ai-agent-payment-infrastructure/) |
| AWS Marketplace | None | ~3% public SaaS; 1.5–3% private offers (secondary) | [SeldonFrame](https://www.seldonframe.com/guides/ai-marketplace-fees-compared); [Suger](https://www.suger.io/resources/blog/ai-agents-on-aws-marketplace/) |
| Google Cloud Marketplace (agents) | None | 3% (secondary); buyer needs Gemini Enterprise seat ~$30/user/mo | [Clazar](https://clazar.io/blog/google-cloud-marketplace-fees) |
| Glama | Free listing | No creator rev-share; user plans $9/$26/$80 per mo | [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html) |
| Smithery | Free listing | Contested: 80% creator split vs. none | [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html) |
| mcp.so / Official MCP Registry | Free | None | [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html) |
| Composio | n/a | SaaS plans free–$229/mo | [Composio](https://composio.dev/content/smithery-alternative) |

- Realized fee revenue at agent-to-agent scale is tiny. Olas collected $851.55 all-time on $109,907.89 turnover as of Oct 12, 2026. — [Olas Mech page via search snippet](https://olas.network/agent-economies/mech)
- The average x402 payment is ~14 cents (Artemis-adjusted, data as of Apr 21, 2026) or ~4 cents per transfer (Token Terminal, Aug 2026). — [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/)

### Inferences
- With average x402 payments of 4–14 cents, a percentage take rate on per-call volume yields negligible revenue. A flat USDC fee per introduction (the proposed model) decouples revenue from micro-payment size, but it must be priced below the value of switching to a better agent.
- The free-discovery norm (Bazaar, Agentverse, MCP registries) means a paid "first introduction" would struggle; the proposed free-first, paid-re-introduction structure fits the market norm.

### Gaps
- No current, official Virtuals ACP fee schedule was confirmed (the docs reportedly contain inconsistent splits).
- No public fee data for Kite's Agent App Store, Catena, Sapiom, Crossmint or Payman.

## 4. Signs of traction vs. failure in 2026

### Takeaway
2026 shows a hype-to-reality correction. x402 daily settlement volume fell ~93–95% from late-2025/Jan-2026 peaks to ~$28–41K/day by Aug–Sep 2026, with 25–89% of historical activity attributed to wash/test traffic depending on the measure. Virtuals' 30-day fees and daily ACP activity look very low against all-time totals. Olas put two agent products into maintenance mode. VC funding for payment rails nonetheless kept flowing (Catena, Natural, Sapiom), and incumbents (Coinbase, AWS, Mastercard, Visa, Salesforce) kept shipping.

### Cited Findings
- **x402 decline**:
  - Daily volume was ~$800K/day in Jan 2026 and ~$40K/day in Sept 2026. — [American Banker](https://www.americanbanker.com/payments/news/agentic-payment-rail-shows-volume-decline)
  - Helios (Jamie Coutts, Aug 12, 2026): -93% YTD and -55% over 3 months, with a 7-day average of ~$41.8K and the latest day ~$28.4K. Q4 2025 peaks neared $800K/day and occasionally passed $1M. — [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/); [Yahoo/CoinDesk](https://finance.yahoo.com/markets/crypto/articles/x402-settlement-volume-plunges-93-105710906.html)
  - Token Terminal: the week of Aug 17, 2026 saw ~8.7M transfers moving ~$368K. The all-time high was 20.1M transfers / $10.0M in the week of Nov 17, 2025. — [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/)
- **Wash activity**:
  - Coinbase's head of AI product, Lincoln Murr (Aug 23, 2026): 25–30% of x402 transactions "may have been generated by users trying to climb public leaderboards."
  - Artemis/Visa (data as of Apr 21, 2026) removed ~39% of transactions and 89% of dollar volume as wash/test/internal. That leaves ~109.6M transactions and ~$15.0M adjusted volume, versus ~$135.7M raw, and ~5,300 real sellers versus 22K on the counter.
  - The x402.org "last 30 days" counter (75.41M transactions / $24.24M / 94K buyers / 22K sellers) appears frozen since ~March 2026.
  - — [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/)
- **Chain mix**: Solana held ~70% of monthly x402 volume as of mid-Aug 2026. — [Crypto Briefing](https://cryptobriefing.com/solana-x402-market-share-dominance/)
- **Coinbase's own headline** (Apr 2026: 165M+ transactions, $50M volume, 480K+ agents) conflicts with Artemis's filtered figures. Coinbase's numbers are cumulative and unfiltered. — [Crypto Briefing](https://cryptobriefing.com/agentic-market-ai-agents-hub/); [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402)
- **Stripe MPP**: ~$25K across ~115K adjusted transactions in its first 33 days (Artemis). — [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/)
- **Virtuals**: $74.32M all-time fees versus $0.62M over the last 30 days (Oct 2026). ACP's daily memo count on Oct 12, 2026 was 28 from 5 unique senders, against 12.36M cumulative (possibly a partial day). — [CoinStats](https://coinstats.app/ai/a/investment-analysis-virtual-protocol); [agenteconomy.to](https://agenteconomy.to/virtuals-acp)
- **Olas**: Optimus and Agents.fun moved to maintenance mode "due to lower adoption." Polystrat was paused after a Polymarket wallet change, then fixed. Q2 2026 brought consolidation onto Pearl. — [Olas Q2 2026](https://olas.network/blog/q2-2026)
- **Kite**: KITE price has trended down since launch; a ~$12.35M unlock was flagged for early June 2026. — [CoinMarketCap AI](https://coinmarketcap.com/cmc-ai/kite/price-prediction/) (low-quality source)
- **Positive traction signals**:
  - Coinbase launched Agentic.Market (Apr 2026) and added the AWS CloudFront integration (Jun 2026). — [Coinbase](https://www.coinbase.com/blog/coinbase-and-aws-let-publishers-accept-agents-as-customers-via-x402)
  - Mastercard is extending Skyfire's KYA into Agent Pay (Sep 30, 2026). — [FintechSpecs](https://fintechspecs.com/blog/mastercard-agent-pay-trust-intelligence-skyfire-kya-2026/)
  - Crossmint shipped a Visa agentic cards API (Jun 2026) and the Agent Commerce Toolkit (Oct 8, 2026). — [Crossmint](https://www.crossmint.com/announcement/agentic-cards-api-launch-visa-basistheory)
  - Catena raised $30M (May 2026) and Natural raised $30M (Jul 2026). — [Fortune](https://fortune.com/2026/05/20/catena-labs-series-a-sean-neville-ai-native-bank/); [FinTech Futures](https://www.fintechfutures.com/venture-capital-funding/natural-bags-30m-launches-agentic-payments-infrastructure)
  - Salesforce consolidated its stores into AgentExchange (Apr 2026). — [SalesforceDevops.net](https://salesforcedevops.net/index.php/2026/04/14/agentexchange-salesforces-bet-that-trust-can-scale-with-agentic-speed/)
- **Consolidation**: Workday acquired Pipedream (announced Nov 2025, closed ~Feb 2026). — [PR Newswire](https://www.prnewswire.com/news-releases/workday-signs-definitive-agreement-to-acquire-pipedream-302619298.html)
- **ERC-8004**: registration-heavy but operationally shallow (3–15% of registrations have a usable endpoint, as of May 2026). — [arXiv 2606.26028](https://arxiv.org/html/2606.26028)
- **Expert commentary**: the decline is "a return to a more natural traffic level," though much of the remaining volume is probably still synthetic (Aaron McPherson). "It's very easy to manipulate or fake 'bot to bot' transactions" (Alex Witt, Verda Ventures). — [American Banker](https://www.americanbanker.com/payments/news/agentic-payment-rail-shows-volume-decline)

### Inferences
- Real agent-to-agent paid demand in Oct 2026 is likely in the low millions of USD per month or less across x402. Any broker's addressable fee pool today is small; the bet is on future growth plus enterprise/fiat agent commerce (Visa, Mastercard, Crossmint).
- Wash trading driven by leaderboards shows that usage-based rankings get gamed. That is a direct argument for a broker whose ranking resists Sybil attacks and is based on outcomes.
- The crypto-native agent marketplaces (Virtuals, Olas, Fetch) show token-driven activity spikes followed by decay. Their discovery layers serve their own ecosystems, leaving cross-ecosystem brokerage open.

### Gaps
- No official Coinbase figure on Agentic.Market usage (queries, click-through, services onboarded since launch).
- No time series for Virtuals ACP jobs/aGDP across 2026. Today's 28-memo reading may be a partial day.
- Fetch.ai active-agent or ASI:One query volume was not found.
- Agent-store usage metrics for Microsoft, Google and AWS are not public.

## 5. Gaps / unmet needs a new broker could fill

### Takeaway
The market has catalogs (Bazaar, Agentverse, MCP registries, enterprise stores) and rails (x402, KYA, wallets), but no neutral, cross-protocol broker. Such a broker would rank agents and APIs on verified outcomes and price-performance, resist wash/Sybil manipulation, and proactively re-route agents to better providers. Each incumbent's discovery is locked to its own protocol or ecosystem.

### Cited Findings
- Discovery is fragmented by protocol and ecosystem: x402 (Bazaar), ACP (Virtuals), Mech (Olas), Agentverse (Fetch), MCP registries, ERC-8004 registries, and AP2/Visa/Mastercard rails. Virtuals' ACP v2 now emits x402/MPP/ACP endpoints, so the protocols overlap. — [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs); [Crossmint protocol comparison](https://www.crossmint.com/learn/agentic-payments-protocols-compared)
- Quality signals are weak:
  - 53% of scanned x402 endpoints scored level 0 on agent-readiness. — [x402station](https://x402station.io/blog/cloudflare-x402-readiness)
  - Only 3–15% of ERC-8004 registrations have a usable endpoint. — [arXiv 2606.26028](https://arxiv.org/html/2606.26028)
  - Usage counts are polluted by wash/leaderboard farming. — [Daniel McGlynn](https://www.danielmcglynn.com/the-x402-counter-has-shown-the-same-four-numbers-since-march/)
- ERC-8004 explicitly leaves reputation scoring and aggregation to off-chain systems. — [eco.com](https://eco.com/support/en/articles/13221214-what-is-erc-8004-the-ethereum-standard-enabling-trustless-ai-agents)
- MCP creators lack monetization: fewer than 5% of servers have a monetized path, and the major directories have no rev-share (single, vendor-authored source). — [SEOSiri](https://www.seosiri.com/2026/09/mcp-monetization-gap-glama-smithery-developer-losses.html)
- Reliability: Virtuals auto-ungraduates agents that let jobs expire, and Butler retries the next-best agent. This shows failover/re-routing is a real need inside one ecosystem. — [ACP Changelogs](https://whitepaper.virtuals.io/acp/acp-changelogs)
- Searches for a dedicated "agent router/broker" startup returned none. The closest are Archestra (data-access broker) and OpenRouter (LLM routing and popularity rankings). — [SiliconANGLE](https://siliconangle.com/2026/06/02/archestra-raises-10m-broker-ai-agent-access-corporate-data/); [OpenRouter](https://openrouter.ai/apps)
- Liability and trust questions ("who's liable when an agent starts wildly subscribing to APIs?") remain open, and the KYA/identity players (Skyfire with Mastercard, Kite Passport) address the identity part only. — [Sapiom coverage/commentary](https://news.ainauten.com/en/story/sapiom-raises-15m-to-help-ai-agents-buy-their-own-tech-tools); [FintechSpecs](https://fintechspecs.com/blog/mastercard-agent-pay-trust-intelligence-skyfire-kya-2026/)

### Inferences
- **Opportunities for a broker**:
  - Cross-protocol meta-discovery across Bazaar, ACP, Agentverse, MCP registries and ERC-8004.
  - Outcome-verified ranking: success rate, latency, price per successful result, evaluator/attestation data. These could be written back to ERC-8004 Reputation as a public good, building trust.
  - Wash-resistant reputation weighted by buyer diversity and stake.
  - Continuous monitoring with proactive "better agent available" re-introductions (Virtuals' Butler does this only reactively, after a failure, within ACP).
  - Neutrality: Coinbase and Virtuals each favor their own rail/token.
- **Risks**:
  - Coinbase could add quality ranking to Agentic.Market for free, and agents could call Bazaar's MCP directly.
  - Intro fees on 4–14-cent payments must be justified by measurable savings or quality gains.
  - Real current demand is small (x402 at ~$30–40K/day in Aug–Sep 2026).
  - Re-introduction fees could be seen as rent-seeking if the "better agent" claim is not transparent and verifiable.
- A defensible wedge is probably B2B: selling routing and reputation data and SLAs to agent builders and to marketplaces themselves (similar to how OpenRouter monetizes LLM routing), rather than relying on per-introduction fees alone.

### Gaps
- No primary data on how often agents switch providers or what they would pay for a better match (willingness to pay).
- No evidence on whether Coinbase plans outcome-based ranking for Bazaar.
- No reliable public data on the share of x402 or ACP calls that fail or underperform, which would quantify the value of re-routing.
