# Agent Payment & Commerce Protocols — State as of October 2026

Research date: 2026-10-12. Most of the sources below are secondary trackers, vendor blogs, or trade press. Primary-source confirmation is noted where available. Every figure carries a date. Anything from before 2026 is marked [pre-2026].

## 1. x402 (Coinbase / x402 Foundation / Cloudflare): spec, schemes, facilitators, chains, volume, Bazaar, integrations

### Takeaway
x402 is the de facto HTTP-native rail for agent-to-API micropayments. It is governed by the Linux Foundation, has 52 to 58 members including Visa, Mastercard, Stripe, Google, AWS, and Cloudflare, and has v2 plus `exact`, `upto`, and `batch-settlement` schemes. Raw transaction counts are large, about 200M cumulative, but filtered "real" commercial volume is small: roughly $15M to $26M cumulative, and only thousands of dollars per month that is clearly agent-moved. Its momentum is in governance and infrastructure, not yet in revenue.

### Cited Findings
**Spec / schemes timeline**
- x402 was created by Coinbase and introduced in May 2025 [pre-2026]. It uses HTTP 402 "Payment Required" to embed stablecoin payments in web requests. — [PYMNTS, 2026-09-25](https://www.pymnts.com/news/artificial-intelligence/2026/block-joins-x402-foundation-to-drive-agentic-commerce-standards/)
- v2 spec released 2025-12-11 [pre-2026]. — [Major Matters x402 Adoption Tracker (updated 2026-10-03)](https://majormatters.co/x402)
- `upto` scheme EVM spec added 2026-03-04. Solana (SVM) delegated-authorization for `upto` merged 2026-09-03 and 2026-09-09. — [Major Matters](https://majormatters.co/x402)
- The `upto` scheme is single-request and usage-based: the buyer authorizes a ceiling and the seller charges actual usage. It is available on EVM in TypeScript, Go, and Python. — [x402 docs: Payment Schemes](https://docs.x402.org/schemes/overview); [x402 FAQ](https://docs.x402.org/faq)
- Offer and Receipt extension added 2026-03-12, with a signer-authorization clarification merged 2026-07-23. — [Major Matters](https://majormatters.co/x402)
- Batch Settlement extension added 2026-05-11. Batch Settlement Solana (SVM) spec added 2026-08-21. — [Major Matters](https://majormatters.co/x402)
- How batch-settlement works on EVM: escrow plus off-chain vouchers, redeemed on-chain in batches so the seller doesn't settle every HTTP request separately. — [x402 docs: Batch Settlement](https://docs.x402.org/schemes/batch-settlement)
- An SVM batch-settlement PR (#3164) was still in review with "changes requested" when searched. — [GitHub x402-foundation/x402 PR #3164](https://github.com/x402-foundation/x402/pull/3164)
- PayAI Network's x402 batch settlement went live on Solana in public preview on 2026-09-30, devnet-first. Mainnet throughput is unverified. — [TradingView/CoinMarketCal, 2026-09-30](https://www.tradingview.com/news/coinmarketcal:4e3fbbb4b094b:0-solana-x402-batch-settlement-enters-public-preview-for-micropayments-30-sep-2026/)
- Auth-capture scheme spec added 2026-05-20 and v1.1 merged 2026-08-25. This is escrow-style, closer to card auth/capture. — [Major Matters](https://majormatters.co/x402)
- Non-EVM `exact`-scheme specs merged: XRPL (2026-07-03), Casper (2026-07-08), Starknet (2026-07-24), Canton (2026-08-07). — [Major Matters](https://majormatters.co/x402)
- Bitcoin Lightning: a commit on 2026-09-23 added `exact` Lightning support (network id `lnbtc`), contributed by Block. — [crypto.news](https://crypto.news/block-joins-x402-with-lightning-support/); [PYMNTS, 2026-09-25](https://www.pymnts.com/news/artificial-intelligence/2026/block-joins-x402-foundation-to-drive-agentic-commerce-standards/)
- Open governance issues: trust proposals #1777 (2026-03-23) and #2299 (2026-05-14), and dispute-handling issues #2887 (2026-07-17) and #3500 (2026-09-16). Neither trust/reputation nor disputes is standardized yet. — [Major Matters](https://majormatters.co/x402)
- A proposed escrow scheme for "work" released on a third party's signed acceptance (`knos-order`) is an open feature request. — [GitHub issue #3720](https://github.com/x402-foundation/x402/issues/3720)

**Foundation / backers**
- The x402 Foundation was announced 2026-04-02 (moving to the Linux Foundation), with Coinbase, Cloudflare, and Stripe as original developers. It launched operationally on 2026-07-14 with 40 members. — [Major Matters](https://majormatters.co/x402); [Yahoo Finance, 2026-08-04](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)
- The 17 premier members include Visa, Mastercard, Stripe, Google, AWS, Cloudflare, Coinbase, American Express, and the Solana Foundation. — [Yahoo Finance, 2026-08-04](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)
- Roster as of 2026-09-18: 52 members (17 Premier, 24 General, 11 Associate). The tracker header says 58, an internal inconsistency. Founding names include Shopify, Adyen, Fiserv, KakaoPay, Circle, Base, Polygon Labs, and Merit Systems. Microsoft, PPRO, thirdweb, and Sierra expressed intent in April but are absent from the July roster. — [Major Matters](https://majormatters.co/x402)
- Block joined on 2026-09-24. It also joined UCP and helped launch the Agentic AI Foundation (AAIF). Quote from Steve Reis of Block: "the agentic economy should be built on open rails." — [PYMNTS, 2026-09-25](https://www.pymnts.com/news/artificial-intelligence/2026/block-joins-x402-foundation-to-drive-agentic-commerce-standards/)

**Facilitator, fees, and Bazaar**
- CDP Facilitator pricing: the first 1,000 on-chain settlements per month are free, then $0.001 per on-chain transaction. Verification is always free. With batch settlement, vouchers are verified off-chain for free and claimed together, so one on-chain transaction can cover thousands of payments. — [Coinbase CDP docs: Facilitator](https://docs.cdp.coinbase.com/x402/seller/facilitator)
- Bazaar is the discovery layer for x402 services catalogued through the CDP Facilitator. Search is hybrid (full-text plus semantic). Listing is automatic: when the facilitator settles a payment on an endpoint with the Bazaar discovery extension, it indexes that endpoint's metadata. — [Coinbase CDP docs: Bazaar](https://docs.cdp.coinbase.com/x402/bazaar.md)
- Coinbase launched Agentic.Market (a service-discovery marketplace on top of x402) on 2026-04-21, per secondary coverage. — [Stellagent](https://stellagent.ai/insights/coinbase-agentic-market-x402)
- Critique: a third-party project reports that Bazaar listings are often "schema-less stubs or single-wallet factories" and that it does not cover chains unsupported by the CDP facilitator. — [HackQuest AgentPay Radar](https://hackquest.io/projects/AgentPay-Radar)
- Protocol fee is zero. The cost is gas: about $0.00025 per transaction on Solana and a fraction of a cent on Base. Settlement takes about 2 seconds. — [Yahoo Finance, 2026-08-04](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)

**Integrations (2026)** — all from [Major Matters](https://majormatters.co/x402) unless noted
- Cloudflare native x402 on Workers, live 2026-04-02. Bankr x402 Cloud, live 2026-04-02. Nevermined, live 2026-04-17.
- AWS Bedrock AgentCore Payments, preview 2026-05-07. AWS CloudFront + WAF x402, GA 2026-06-15.
- Arbitrum, live 2026-05-15 (secondary report). Fireblocks Agentic Payments Suite, live 2026-05-20, with Fireblocks joining the Foundation the same day.
- Casper mainnet facilitator, 2026-06-04. Ripple/XRPL, announced 2026-06-09 (testnet only; mainnet unverified).
- Cloudflare Monetization Gateway, announced 2026-07-01 as waitlist-only and not GA. — also [explainx.ai](https://explainx.ai/blog/cloudflare-monetization-gateway-x402-mcp-api-micropayments-2026)
- Stripe accepts x402 USDC on Base (documented; date unconfirmed, checked 2026-09-18).
- Tracker count: 14 integrations, 12 live and 2 announced.
- Small-seller reality check: GigSoul has 30 endpoints priced $0.005 to $2.00 and only 51 QA settlements totaling $5.78 since 2026-09-19 (as of 2026-10-03). One marketplace saw 1,183 probes, 5 settlements, and $0.11 revenue in late Q1 2026.

**Volume and transaction data (conflicting; note the windows)**
- Coinbase, late April 2026: about 165M cumulative transactions, about $50M cumulative volume, and about 69,000 active agents. Median payment is about $0.028 per call. — [DEV Community](https://dev.to/t49qnsx7qtkpanks/x402-hit-165-million-transactions-heres-what-it-still-cant-do-4f4d); [Eco support (via search)](https://eco.com/support/en/articles/14846276-build-an-mcp-server-with-x402-monetization)
- CoinDesk/Artemis, 2026-03-11: about $28,000 per day in real commercial volume and about 131,000 daily transactions averaging $0.20. About half of transactions are artificial. Elsewhere Artemis is cited as finding more than 95% of activity is "protocol signaling." — [Major Matters](https://majormatters.co/x402); [Yahoo Finance](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)
- Chainalysis, 2026-06-03, on Base:
  - 100M cumulative transactions through Q1 2026.
  - 3.1M transactions and $1.2M value in the 30 days to 2026-05-29.
  - Sellers up 23% and buyers up 37% over that window.
  - Transactions of $1 or more were 95% of volume in early 2026, up from 49% in early 2025.
  - Tester-to-payer conversion rose 4x over six months.
  - Q4 2025 had a meme-coin-driven surge that moderated in early 2026.
  - Sources: [Chainalysis](https://www.chainalysis.com/blog/x402-agentic-payments-adoption/); [Major Matters](https://majormatters.co/x402)
- Visa and Artemis, 2026-07-14: $15.0M adjusted volume across 109.6M transactions (May 2025 to 2026-04-21). Raw totals were $135.7M across 178.3M transactions, so adjustment removes about 89% of value. — [Major Matters](https://majormatters.co/x402)
- TRM Labs, 2026-09-09:
  - $52.7M across 198.9M settlements on Base, Solana, and Polygon since May 2025, or $25.62M after filtering.
  - 0.6% to 7.5% of screened value appears truly agentic.
  - Agent-moved volume is roughly $5,000 to $11,000 per month in 2026.
  - 99.6% of value settled in USDC.
  - Source: [Major Matters](https://majormatters.co/x402)
- x402 Foundation figure, reported around September 2026: 75.41M transactions and $24.24M volume over a recent 30 days. This is not reconcilable with Chainalysis's $1.2M per 30 days in May. The windows or definitions likely differ. — [search summary of crypto.news / bitcoin.com coverage](https://news.bitcoin.com/crypto-news/jack-dorseys-block-brings-lightning-network-to-x402/)
- Major Matters' changelog also lists unreconciled figures: about 72M transactions and $24M (June 26 changelog), about 94k buyers and 22k sellers, and "169M payments" (June 23). — [Major Matters](https://majormatters.co/x402)
- Over 200M cumulative transactions as of June 2026. — [Yahoo Finance, 2026-08-04](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)
- Chain split conflict: one tracker says about 85% of cumulative settled transactions are on Base. A Solana post (2026-09-22) claims Solana handles 76% of all x402 transactions (23.2M in four weeks), which suggests a recent shift to Solana by count. A "~$50 billion volume / 150,000 merchant endpoints" figure from a Solana/Coinbase webinar recap is very likely an error or a different metric. Do not use it. — [Presenc tracker](https://presenc.ai/research/x402-protocol-adoption-tracker-2026); [Cryptonews (403 on fetch; via search snippet)](https://cryptonews.com/news/x402-solana-news-ai-payments/)

### Inferences
- x402's raw counts are inflated by testing, meme-coin farming, and self-dealing. Filtered, the real economy is about $15M to $26M cumulative over roughly 16 months, with clearly agent-originated value in the low thousands to about $11k per month. The opportunity is real but early. A USDC-fee gateway should model revenue on filtered numbers, not headline transaction counts.
- The 2026 trend is toward non-per-request settlement (`upto`, batch-settlement, auth-capture, Lightning, multi-chain). The protocol is adapting to sub-cent, high-frequency agent calls and to escrow-for-work patterns, which suits an agent-introduction gateway that charges per match or introduction.
- Trust, reputation, and disputes are open issues in the x402 repo. That gap is where an introduction/reputation gateway could add value.
- The Solana share appears to be rising in H2 2026, so supporting both Base and Solana USDC looks necessary.

### Gaps
- I could not fetch x402scan or a Dune dashboard for current (October 2026) weekly volume trends. No weekly series was found.
- I did not find a primary x402.org/Coinbase statement on the exact current spec version (v2.x) or `upto` ratification status.
- The Solana 76% claim and the x402 Foundation "75.41M tx / $24.24M per 30 days" figure come from search snippets of articles I could not fully fetch.
- No independent number for count of facilitators (PayAI, CDP, Corbits, etc.) in October 2026.

## 2. Google AP2, A2A x402 extension, OpenAI/Stripe ACP, Stripe/Tempo MPP, Visa TAP / Intelligent Commerce, Mastercard Agent Pay, PayPal/Amazon

### Takeaway
Card-network and big-tech protocols (AP2, UCP, ACP, TAP, Agent Pay) focus on consumer checkout and authorization. They are pilot or early-production, and none publishes meaningful volume. OpenAI retreated from in-chat checkout in March 2026. The machine-to-machine micropayment layer has narrowed to two HTTP-402 rails: x402 and Stripe/Tempo's MPP. Visa and Mastercard are hedging across all of them.

### Cited Findings
**Google AP2 / UCP / A2A**
- AP2 was announced in September 2025 [pre-2026] with more than 60 partners, including PayPal, Mastercard, and AmEx. v0.2.0 shipped in April 2026 and added "Human Not Present" autonomous payments based on pre-authorized user instructions. — [Efficiently Connected / TNW search summary](https://thenextweb.com/news/google-universal-cart-agent-payments-shopping-io-2026); [The Paypers](https://thepaypers.com/payments/news/google-donates-agent-payments-protocol-to-fido-alliance)
- Google donated AP2 to the FIDO Alliance and published v0.2 at the same time. A Google–Mastercard co-developed "Verifiable Intent" standard, a tamper-proof log of user-authorized agent actions, is also being donated to FIDO. — [Google blog](https://blog.google/products-and-platforms/platforms/google-pay/agent-payments-protocol-fido-alliance/); [FIDO Alliance](https://fidoalliance.org/google-donates-agent-payments-protocol-to-fido-alliance/?cst)
- AP2 is positioned as an extension of A2A and is compatible with UCP. — [AP2 site](https://ap2-protocol.org/index.md); [Google Developers Blog: UCP](https://developers.googleblog.com/under-the-hood-universal-commerce-protocol-ucp/)
- The A2A x402 extension (google-agentic-commerce/a2a-x402) brings crypto payments to A2A: the merchant sends payment-required and the client returns a signed payment. The spec is at v0.1, and partner schemes are "experimental." — [GitHub a2a-x402](https://github.com/google-agentic-commerce/a2a-x402)
- UCP was announced 2026-01-11 at NRF. At Google I/O 2026 (May), Amazon, Meta, Microsoft, Salesforce, and Stripe joined the UCP Tech Council alongside Google, Shopify, Etsy, Target, and Wayfair. UCP checkout is live for eligible US retailers on Search and Gemini (Google Pay, PayPal) and is expanding to Canada, Australia, then the UK. — [TNW](https://thenextweb.com/news/google-universal-cart-agent-payments-shopping-io-2026); [Efficiently Connected](https://www.efficientlyconnected.com/google-io-2026-agentic-commerce-protocols-ucp-ap2/)
- Mastercard announced support for UCP around June 2026. — [ucptools.dev](https://ucptools.dev/blog/mastercard-backs-ucp-protocol-convergence)
- Most retailers do not integrate AP2 directly. Processors and networks handle it. — [AP2 explainer (search summary)](https://www.mintmcp.com/blog/ap2-agent-payments-protocol)

**OpenAI / Stripe ACP**
- ACP was co-developed by OpenAI and Stripe and launched with ChatGPT Instant Checkout on 2025-09-29 [pre-2026]. It is Apache 2.0. Stripe provides Shared Payment Tokens. — [Stripe newsroom](https://stripe.com/newsroom/news/stripe-openai-instant-checkout); [OpenAI](https://openai.com/index/buy-it-in-chatgpt/)
- In March 2026 (dated 2026-03-04 or 2026-03-17 depending on outlet), OpenAI scaled back Instant Checkout. Users are now redirected to merchant apps (Instacart, Target, Expedia) to pay. According to Shopify's president, only about 12 Shopify stores were actively using it. ACP survives as the commerce layer for ChatGPT Apps (Target, DoorDash, Instacart, Uber). — [Forkast](https://forkast.news/openai-built-in-chat-checkout-for-ai-commerce-five-months-later-it-walked-away/); [Shopifreaks](https://www.shopifreaks.com/openai-scales-back-its-integrated-commerce-plans/); [Stellagent](https://stellagent.ai/insights/openai-scales-back-instant-checkout)
- Visa's OpenAI integration (tokenized payments for shopping agents) was announced 2026-06-10, with no published consumer go-live date. — [ScriptMasterLabs](https://scriptmasterlabs.com/visa-trusted-agent-protocol); [Digital Applied](https://www.digitalapplied.com/blog/visa-openai-tokenized-agentic-commerce-payments-merchant-guide)

**Stripe / Tempo MPP (Machine Payments Protocol)**
- MPP was launched on 2026-03-18 by Stripe and Tempo, the same day Tempo mainnet went live. Visa contributed and is extending MPP to cards on the Visa Acceptance Platform. — [Silicon Republic](https://www.siliconrepublic.com/business/stripes-crypto-joint-venture-tempo-launches-payments-protocol-for-ai); [PYMNTS](https://www.pymnts.com/visa/2026/visa-scales-agentic-commerce-through-stripe-protocol-collaboration/)
- Mechanics: HTTP 402 with `WWW-Authenticate: Payment` (challenge), then `Authorization: Payment` (credential), then `Payment-Receipt`. Payment methods are Tempo stablecoins, Lightning, and cards via Stripe. Session mode means the agent deposits a reserve, pays per request with signed IOUs, and the server settles once. It has been submitted to the IETF as the "Payment HTTP Authentication Scheme." — [Forkast glossary](https://forkast.news/glossary/machine-payments-protocol/); [Tokenized Pod](https://www.tokenizedpod.com/learn/what-is-machine-payments-protocol)
- Adoption: about 30,000 MPP transactions from launch to August 2026. This is a single source; treat with caution. — [search summary; agitech.group](https://agitech.group/blog/machine-payments-protocol-mpp-stripe-ai-agents-2026)
- Note that Stripe sits on both sides: it is an x402 Foundation original developer, it accepts x402 USDC on Base, and it backs MPP, ACP, and UCP. — [Major Matters](https://majormatters.co/x402)

**Visa**
- Visa launched the Trusted Agent Protocol (TAP) in October 2025 [pre-2026]. On 2026-09-24, Cleverbridge, Visa, and Revolut ran what was described as France's first passkey-authenticated agentic purchase. Visa reported "hundreds" of agent-initiated transactions by late 2025 [pre-2026]. — [ScriptMasterLabs](https://scriptmasterlabs.com/visa-trusted-agent-protocol)
- Visa and Artemis published the x402 adjusted-volume analysis on 2026-07-14, showing Visa is tracking crypto rails directly. — [Major Matters](https://majormatters.co/x402)

**Mastercard**
- Agent Pay is reportedly in production in Singapore and Malaysia. A Santander transaction ran on live bank infrastructure in March 2026. — [ATXP](https://atxp.ai/blog/mastercard-agent-pay-stripe-acp-visa-x402-comparison-2026/); [Nevermined](https://nevermined.ai/blog/best-platforms-agentic-payments)
- On 2026-10-01, Mastercard added an "agent-initiated" probability score plus trust signals for issuers, in US testing. KYA identity is built with Skyfire, and Cloudflare works on privacy-preserving data. — [Contra Collective, Oct 2026](https://contracollective.com/blog/agentic-payments-protocols-mastercard-visa-stripe-2026); [FintechSpecs](https://fintechspecs.com/blog/mastercard-agent-pay-trust-intelligence-skyfire-kya-2026/)
- Mastercard completed its $1.8B acquisition of BVNK (stablecoin payments infrastructure, about $30B annualized volume) in August 2026. — [Yahoo Finance, 2026-08-04](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)

**PayPal / Amazon / Shopify / Meta**
- PayPal is an AP2 launch partner and an accepted method in UCP checkout. — [TNW](https://thenextweb.com/news/google-universal-cart-agent-payments-shopping-io-2026)
- On 2026-09-22, Shopify and Meta announced that Meta's AI shopping agent "Muse" can buy from Shopify merchants via Shop Pay. Within days, Amazon blocked Muse from its marketplace, citing unauthorized agent access, identity concealment, and credential collection. Amazon remains a walled garden while sitting on the UCP Tech Council and being an AWS x402 premier member. — [Contra Collective](https://contracollective.com/blog/agentic-payments-protocols-mastercard-visa-stripe-2026)
- Trade press counted eight "live" protocols as of 2026-10-01: MCP, A2A, ACP, UCP, AP2, TAP, Agent Pay, and MPP. They are described as stacking rather than competing. — [Contra Collective](https://contracollective.com/blog/agentic-payments-protocols-mastercard-visa-stripe-2026)

### Inferences
- For agent-to-agent purchases of data and services, which is the founder's use case, x402 and MPP are the relevant rails. AP2, UCP, ACP, TAP, and Agent Pay target consumer retail checkout with a human principal and card credentials.
- Amazon's block of Meta's Muse shows that agent identity and authorization (KYA) is becoming a gating factor for acceptance.

### Gaps
- No primary Visa or Mastercard volume figures for agentic transactions in 2026.
- No PayPal-specific agent-payments product update for July–October 2026 was found. PayPal's "Agent Ready" and similar products were not verified.
- AP2 v0.2 date and FIDO donation date: secondary sources say April 2026. I did not fetch the Google blog post to confirm the exact date.
- MPP adoption figure (30k transactions) is single-source.

## 3. Agent identity / reputation: ERC-8004, KYA, Skyfire KYAPay, agent cards

### Takeaway
ERC-8004 went live on mainnet on 2026-01-29 and has many registrations across 20+ chains, but little real reputation usage. KYA has become the card networks' framing: Mastercard is using Skyfire. The identity and reputation layer is fragmented and largely unused, which is a gap an introduction gateway could fill.

### Cited Findings
- ERC-8004 ("Trustless Agents") deployed to mainnet on 2026-01-29. It is still Draft status in the EIP registry. It has identity, reputation, and validation registries. — [Forbes, 2026-02-05](https://www.forbes.com/sites/digital-assets/2026/02/05/ai-agents-gain-trust-via-ethereum-erc-8004-on-mainnet/); [Bankless Times, 2026-01-28](https://www.banklesstimes.com/articles/2026/01/28/ethereum-erc-8004-set-for-mainnet-launch-to-enable-trustless-ai-agents/); [eip.tools](https://eip.tools/eip/8004)
- Registrations passed 10,000 within about 10 weeks. A secondary blog's claim of 200K+ across 20+ chains is unverified. BNB Chain surpassed Ethereum in registration count in March 2026. Deployments span Ethereum, Base, Arbitrum, Optimism, Polygon, and 20+ mainnets as of 2026-10-06. — [QuantEcon applied research](https://www.quantecon.ai/applied-research/erc-8004-participation); [Eco support](https://eco.com/support/en/articles/13221214-what-is-erc-8004-the-ethereum-standard-enabling-trustless-ai-agents)
- Of the first 10,000 mainnet agents, only 628 (6.28%) ever received reputation feedback and only 67 declared service endpoints. The study concludes registration counts are a weak adoption signal. A later analysis (data through 2026-05-13) found low active-participation rates of 3%, 4%, and 15% on Ethereum, BSC, and Base. — [QuantEcon](https://www.quantecon.ai/applied-research/erc-8004-participation)
- Risks flagged: identity spoofing, spam, and metadata manipulation. — [CCN](https://www.ccn.com/education/crypto/erc-8004-ai-agents-on-chain-ethereum-how-works-risks-explained/)
- Skyfire KYAPay issues signed JWTs that attest to the buyer agent, its principal, and its platform. Token types are `kya` (identity only), `pay`, and `kya-pay`. Settlement is in USDC from a pre-funded wallet. An IETF draft (draft-skyfire-kyapayprofile-01) was reported but not verified on the datatracker. — [Skyfire](https://skyfire.xyz/); [KYAPay whitepaper](https://kyapay.org/whitepaper); [Stablecoin Insider](https://stablecoininsider.org/how-to-create-a-skyfire-kyapay-token-for-usdc/)
- Mastercard is working with Skyfire to extend KYA into Agent Pay (reported 2026-09-30 and 2026-10-01). — [FintechSpecs](https://fintechspecs.com/blog/mastercard-agent-pay-trust-intelligence-skyfire-kya-2026/); [Contra Collective](https://contracollective.com/blog/agentic-payments-protocols-mastercard-visa-stripe-2026)
- KYA is framed as "the new KYC" compliance battleground, with a16z, Skyfire, and FATF involved. — [Bex, 2026-04-26](https://bex.co/blog/2026/04/26/kya-know-your-agent-new-kyc-a16z-skyfire-fatf-compliance-battleground)
- x402 has open "trust" proposals (#1777, #2299) and dispute issues (#2887, #3500), with no ratified reputation layer as of 2026-10-03. — [Major Matters](https://majormatters.co/x402)
- Agent cards: A2A Agent Cards are the discovery and identity document in A2A. AP2 and A2A-x402 build on them as extensions. — [AP2 site](https://ap2-protocol.org/index.md); [GitHub a2a-x402](https://github.com/google-agentic-commerce/a2a-x402)

### Inferences
- There is no dominant reputation standard. ERC-8004 is the on-chain candidate, but its feedback data is sparse. KYAPay and Visa TAP are winning on the network and merchant side. A gateway that bridges these, for example by reading ERC-8004 identities, issuing or accepting KYA tokens, and recording x402 receipts as reputation, fills a real gap.

### Gaps
- No verified count of Skyfire KYAPay transactions or merchants.
- Which major x402 facilitators consume ERC-8004 reputation was not established.
- Visa TAP signature spec adoption by CDNs (Cloudflare Web Bot Auth) in 2026 was not verified in this pass.

## 4. MCP and payments

### Takeaway
There is no official MCP payment standard. The de facto pattern is "free `tools/list`, paid `tools/call`" gated by x402 (per-call) or MPP (session). Cloudflare's Monetization Gateway, the main managed offering, was still waitlist-only in July 2026.

### Cited Findings
- Common pattern: free discovery and handshake, and an unpaid `tools/call` returns 402 with price. The agent pays USDC on Base and retries with a receipt. — [systemprompt.io guide](https://systemprompt.io/guides/monetize-mcp-server-x402); [DEV Community](https://dev.to/marcuschen-dev/i-wrapped-my-x402-pay-per-call-apis-in-an-mcp-server-and-got-into-the-official-registry-without-3gm2)
- Cloudflare's Agents SDK ships a paid-tools helper, and Coinbase has a reference implementation. The Cloudflare Monetization Gateway (x402 for MCP/APIs) opened a waitlist on 2026-07-01 and is not GA. — [explainx.ai](https://explainx.ai/blog/cloudflare-monetization-gateway-x402-mcp-api-micropayments-2026); [Major Matters](https://majormatters.co/x402)
- Rule of thumb from developer guides: x402 for a few calls, MPP session billing for hundreds. — [usagebox](https://usagebox.com/articles/how-to-charge-for-mcp-server-2026-per-call-subscription-x402)
- Paid servers can be listed in the official MCP Registry, which limits descriptions to 100 characters. It has no pricing or payment field. — [DEV Community](https://dev.to/marcuschen-dev/i-wrapped-my-x402-pay-per-call-apis-in-an-mcp-server-and-got-into-the-official-registry-without-3gm2)
- Other options: xpay MCP monetization proxy, and marketplaces such as Apify and MCPize that handle billing. — [xpay docs](https://docs.xpay.sh/en/products/mcp-monetization); [getchatads](https://www.getchatads.com/blog/tools-for-monetizing-mcp-servers/)
- Creator earnings claims ("$3k–$10k+/month top tier") are marketing, not audited figures. — [godberrystudios](https://godberrystudios.com/posts/how-to-monetize-mcp-servers-2026/)
- MCP is now under the Agentic AI Foundation (AAIF), which Block helped launch. — [PYMNTS, 2026-09-25](https://www.pymnts.com/news/artificial-intelligence/2026/block-joins-x402-foundation-to-drive-agentic-commerce-standards/)

### Inferences
- Discovery is the gap: neither the MCP Registry nor Bazaar provides quality signals or pricing metadata in a trusted way. An introduction or matchmaking gateway sits in that gap.

### Gaps
- No primary MCP spec SEP or registry announcement adding a payments/pricing field in 2026 was found.
- No aggregate revenue figures for paid MCP servers.

## 5. Stablecoin rails: chains, fees, settlement

### Takeaway
USDC dominates: 99.3% to 99.6% of x402 value. The main chains are Base and Solana, with Polygon third and a long tail (XRPL, Starknet, Casper, Canton, Lightning) added in July to September 2026. Fees are sub-cent and settlement takes about 2 seconds.

### Cited Findings
- 99.6% of x402 value settled in USDC (TRM Labs, 2026-09-09). Another report says 99.3%. — [Major Matters](https://majormatters.co/x402); [bitcoin.com](https://news.bitcoin.com/crypto-news/jack-dorseys-block-brings-lightning-network-to-x402/)
- Gas is about $0.00025 per transaction on Solana and a fraction of a cent on Base. Settlement takes about 2 seconds. The x402 protocol fee is zero. — [Yahoo Finance, 2026-08-04](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)
- CDP facilitator: $0.001 per on-chain settlement after 1,000 free per month. — [CDP docs](https://docs.cdp.coinbase.com/x402/seller/facilitator)
- Main chains: Base, Solana, Polygon (Visa/Artemis and TRM). Base has about 85% of cumulative transactions by one tracker, but Solana claims 76% of recent transactions (September 2026). — [Major Matters](https://majormatters.co/x402); [Presenc](https://presenc.ai/research/x402-protocol-adoption-tracker-2026)
- Tempo (Stripe-incubated L1) mainnet launched 2026-03-18 as the MPP stablecoin rail. — [Silicon Republic](https://www.siliconrepublic.com/business/stripes-crypto-joint-venture-tempo-launches-payments-protocol-for-ai)
- US regulatory backdrop: the GENIUS Act was signed in July 2025 [pre-2026]. — [Yahoo Finance](https://finance.yahoo.com/markets/crypto/articles/x402-foundation-activated-27-old-152440828.html)

### Gaps
- No verified Tempo on-chain volume data.
- No authoritative per-chain x402 dollar-volume split for Q3 2026.

## 6. Which rails are winning vs stalling

### Takeaway
x402 is the clear institutional winner for machine-to-machine micropayments, although real volume is small. MPP is a credible Stripe-backed challenger. On the consumer side, OpenAI's ACP checkout stalled, Google's UCP/AP2 is gaining coalition breadth, and the card networks are in pilots. Identity/KYA is the emerging battleground.

### Cited Findings
- **Winning, x402:** 52 to 58 Foundation members including Visa, Mastercard, AmEx, Google, AWS, Stripe, and Shopify. Block joined in September 2026. Cloudflare and AWS shipped infrastructure. Filtered volume is real but small: $15M to $26M cumulative and about $5k to $11k per month clearly agentic. Chainalysis reports sellers up 23% and buyers up 37% (30 days to 2026-05-29) and 4x tester-to-payer conversion. — [Major Matters](https://majormatters.co/x402); [Chainalysis](https://www.chainalysis.com/blog/x402-agentic-payments-adoption/)
- **Stalled, OpenAI Instant Checkout / ACP-in-chat:** scaled back in March 2026 with about 12 active Shopify stores. — [Forkast](https://forkast.news/openai-built-in-chat-checkout-for-ai-commerce-five-months-later-it-walked-away/)
- **Gaining coalition, Google UCP + AP2:** Amazon, Meta, Microsoft, Salesforce, and Stripe joined the UCP council (May 2026). Mastercard backs UCP. Block joined UCP. AP2 moved to FIDO (v0.2). — [TNW](https://thenextweb.com/news/google-universal-cart-agent-payments-shopping-io-2026); [PYMNTS](https://www.pymnts.com/news/artificial-intelligence/2026/block-joins-x402-foundation-to-drive-agentic-commerce-standards/)
- **Early, card networks:** Visa TAP passkey pilot (2026-09-24, France). Mastercard Agent Pay is live in SG/MY with US agent-probability testing from 2026-10-01. No volume disclosed. A 2027 to 2028 consumer adoption horizon is expected. — [ScriptMasterLabs](https://scriptmasterlabs.com/visa-trusted-agent-protocol); [Contra Collective](https://contracollective.com/blog/agentic-payments-protocols-mastercard-visa-stripe-2026)
- **Challenger, MPP:** about 30k transactions from March to August 2026, versus x402's millions per month. Its advantage is Stripe distribution and card fallback. — [agitech.group](https://agitech.group/blog/machine-payments-protocol-mpp-stripe-ai-agents-2026)
- A Forbes piece (2026-06-07) frames the contest as "Visa, Mastercard and Coinbase are fighting over how AI agents pay." — [Forbes](https://www.forbes.com/sites/digital-assets/2026/06/07/visa-mastercard-and-coinbase-are-fighting-over-how-ai-agents-pay/)

### Inferences
- For a USDC-fee agent-introduction gateway:
  - Build on x402 first, with `exact` for simple fees, `upto` for metered fees, and batch-settlement for high-frequency fees.
  - Support Base and Solana USDC.
  - List in Bazaar and the MCP Registry.
  - Plan for MPP compatibility, because both use HTTP 402 and similar headers.
  - Accept KYA tokens or ERC-8004 identities for trust.
- Treat headline x402 transaction counts skeptically when sizing the market. Filtered agentic revenue is currently tiny, so early revenue will depend on finding the few real buyers.

### Gaps
- No October 2026 weekly or monthly x402 volume series from a primary dashboard (x402scan or Dune) was retrieved, so whether volume is currently rising or falling in Q3 2026 is not firmly established. One aggregator mentioned a "steep volume decline" without data. — [letsdatascience (unverified)](https://letsdatascience.com/news/x402-reveals-approval-gap-in-agentic-micropayments-761bf8e7)
