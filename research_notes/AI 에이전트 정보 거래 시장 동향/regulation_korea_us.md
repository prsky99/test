# Regulatory and legal environment for an AI-agent-to-AI-agent introduction service that charges fees in USDC (Korea, US, EU), as of October 2026

> Disclaimer: These are research notes, not legal or tax advice. Many points below are still pending legislation or rulemaking as of 2026-10-12. Items marked **[UNCERTAIN]** are interpretations that have not been confirmed by a regulator or court. A Korean law firm should confirm them before launch, and if needed the FIU, MOEF or NTS should be asked for a formal interpretation (유권해석).

## Q1. South Korea: digital asset law status, won stablecoins, VASP (특금법) registration, foreign exchange law, and treatment of USDC receipts

### Takeaway
As of October 2026, Korea's comprehensive stablecoin law, the Digital Asset Basic Act (디지털자산기본법, "phase-2 legislation"), has **not been passed, and the government bill has not even been submitted**. The FSC chair said at the 2026-10-08 National Assembly audit that he would push it "as quickly as possible", and the ruling party is aiming to pass it within 2026. Separately, an **amendment to the Foreign Exchange Transactions Act passed on 2026-05-07 and takes effect around 2026-12-03**. It requires VASPs that move crypto across borders to register and report. Our service would receive USDC fees as payment for an introduction/brokerage service. Whether that alone makes it a VASP under the 특금법 has **no regulatory interpretation that we could find**, so it is a gray area **[UNCERTAIN]**.

### Cited Findings
**Digital Asset Basic Act and won stablecoins (legislative status)**
- 2026-10-08, National Assembly Political Affairs Committee audit of the FSC: FSC chair 이억원 said the government would prepare the phase-2 bill (stablecoin institutionalization) "as quickly as possible", that the content is already drafted and in final consultation, and gave **no specific submission date**. The government bill is **not yet submitted**. — [뉴스웨이 2026-10-08](https://newsway.co.kr/news/view?ud=2026100821481030074)
- When phase 1 (the 가상자산이용자보호법) was enacted in 2023, the National Assembly attached a non-binding opinion asking for a phase-2 bill within one year. That deadline was not met. Rep. 민병덕 has said he will start public hearings and subcommittee review right after the audit, without waiting for the government bill, and pass it within the year. — [뉴스웨이](https://newsway.co.kr/news/view?ud=2026100821481030074); [검색 요약: 이데일리/네이트 등](https://m.news.nate.com/view/20260824n33451)
- 2026-08-21, Democratic Party seminar at the National Assembly: lawmakers said they would pass the 디지털자산기본법 in the second half of the year. Rep. 김현정 said the legal basis for won stablecoins should be in place "by the end of this year at the latest". The dispute over the issuing consortium's ownership (bank majority vs. tech-company led) is still unresolved. — [ZDNet Korea 2026-08-21](https://zdnet.co.kr/view/?no=20260821152355)
- Main issues reported: a cap on major shareholders' stakes in exchanges (15–20% discussed), a consortium in which banks hold 50% + 1 share, an issuer licensing (인가) regime, and reserves of 100% or more in safe assets such as government bonds. The FSC and the Bank of Korea disagree on issuance rules. — [서울경제](https://www.sedaily.com/article/20015028); [한국금융신문 2026-07-15](https://www.fntimes.com/html/view.php?ud=2026071519045471140f4390e77d_18); [토큰포스트](https://www.tokenpost.kr/news/policy/319834)
- Late August 2026 report: the ruling party planned to introduce a party–government combined bill based on the FSC draft "next month", per Rep. 유동수. We **could not confirm** that it was actually introduced. — [네이트뉴스 2026-08-24](https://m.news.nate.com/view/20260824n33451)
- On foreign stablecoins: at the audit, Rep. 이강일 pointed out that a Cayman Islands entity had issued a won-denominated stablecoin. The FSC chair answered only that it would be handled by policy, and the article describes **no concrete rule for foreign stablecoins (USDC etc.)**. — [뉴스웨이](https://newsway.co.kr/news/view?ud=2026100821481030074)
- MOEF and FSC listed "rules for cross-border stablecoin transactions (including a Foreign Exchange Transactions Act amendment)" as a task for H2 2026. — [검색 요약(한국금융신문 등)](https://www.fntimes.com/html/view.php?ud=2026071519045471140f4390e77d_18)

**Foreign Exchange Transactions Act amendment (cross-border crypto transfers)**
- Passed at the 2026-05-07 plenary session, **effective 2026-12-03**. A VASP that wants to conduct 가상자산이전업무 (moving crypto between Korea and abroad through purchase, sale, exchange, or similar acts) must register with the Minister of Economy and Finance. Registration requires a completed 특금법 VASP filing, a connection to the Bank of Korea's foreign exchange data system, and staffing and facility requirements. Transfer data can be shared with the FSC, NTS, Korea Customs Service, FSS and others. **The exact scope of covered acts is left to the enforcement decree.** — [김앤장 뉴스레터](https://www.kimchang.com/ko/insights/detail.kc?sch_section=4&idx=34975)
- Promulgated 2026-06-02 as Act No. 21714. A law firm blog explains that the scope is expected to include transfers between Korean VASPs and personal wallets. — [디센트 법률사무소](https://blog.decentlaw.io/crypto-remittance-foreign-exchange-law); [아시아경제 2026-05-26](https://view.asiae.co.kr/article/2026052609425726001)
- Penalties: for payment-procedure violations intended to obtain unjust gains, up to 1 year in prison or a fine of up to KRW 100 million (previously a fine of up to KRW 50 million). — [김앤장](https://www.kimchang.com/ko/insights/detail.kc?sch_section=4&idx=34975)

**특금법 (VASP filing)**
- Businesses that must file: those that buy or sell crypto, exchange one crypto for another, broker, arrange or act as agent for those acts, or store and manage crypto as a business. Operating without filing carries up to 5 years in prison or a fine of up to KRW 50 million. Foreign operators serving Korean users in Korea are also covered. — [검색 요약: 김앤장/광장 뉴스레터](https://www.bkl.co.kr/law/insight/newsletter/6318); [금융위 보도자료](https://fsc.go.kr/no010101/78323)
- December 2025 FIU press release: every business other than the 27 filed VASPs is "illegal". Examples given include stablecoin exchanges through Telegram or open chat rooms, SNS promotion and referrals for unfiled operators, and crypto-based 환치기 through currency exchange shops. — [금융위 보도자료](https://fsc.go.kr/no010101/87177)

### Inferences
- **[UNCERTAIN] VASP status:** If the service only provides an "AI agent introduction service" and receives a USDC fee **directly as the merchant (payee)**, that is not a business of buying, selling, exchanging, brokering or custodying crypto for others. Under the current text of the 특금법 it is therefore likely **outside** the VASP filing requirement. Simple payment acceptance is similar to a business taking crypto as payment for goods. The risk rises in these cases:
  1. **Escrow:** the platform holds USDC from agent A and passes it to agent B.
  2. **Wallet custody:** the platform manages users' wallets or keys.
  3. **USDC conversion:** the platform converts USDC to KRW or other crypto on users' behalf.
  4. **Facilitating trades:** the introductions themselves facilitate crypto trades.

  In any of these, the activity could be seen as brokering, arranging or custodying crypto, which may trigger the VASP filing requirement (and in practice requires ISMS certification and a real-name bank account, which is close to impossible for a small company).
- **[UNCERTAIN] FX law:** The 2026-12-03 FX amendment targets VASPs. A non-VASP company receiving fees from overseas counterparties into its own wallet is probably not directly required to register. However, the enforcement decree may include transfers involving personal wallets. Converting USDC to KRW, or receiving crypto through a Korean exchange, also leaves a record in the reporting system. Paying for services in crypto instead of through a foreign exchange bank could also raise questions under the FX law's general rules on payment methods and cross-border settlement (지급등의 방법). Monitor the enforcement decree published around December 2026.
- **Foreign stablecoin (USDC):** Even after the phase-2 law passes, the reported drafts center on won stablecoins. There is a real possibility of new rules on the domestic circulation of foreign stablecoins (e.g., limits on distributing them, or on which channels may handle them) **[UNCERTAIN]**. Most current analysis is that holding or receiving USDC itself is not illegal.
- **Practical cash-out issue:** USDC cannot be traded against KRW on Korean exchanges (no USDC/KRW market is being tracked in sources, and listing is restricted) **[UNCERTAIN — not verified in this research]**. Converting to KRW may therefore require an overseas exchange, which would add FX reporting issues.

### Gaps
- We found no FIU interpretation or FAQ answering whether a business that receives crypto as payment for services must file as a VASP. We recommend requesting a formal interpretation from the FIU.
- The final text of the FX enforcement decree (the scope of 가상자산이전업무) had not been released as of research.
- We could not confirm whether the party–government combined bill was introduced in September 2026, or its bill number.
- We found no concrete government position on how foreign stablecoins such as USDC will be distributed or used domestically.

## Q2. Korea: tax treatment of crypto income, VAT, and the Electronic Commerce Act / AI Basic Act

### Takeaway
Taxation of **individuals' crypto investment income starts 2027-01-01** (separate taxation as "other income", 22% including local tax, KRW 2.5 million annual deduction, first filing in May 2028). However, these sources are mostly secondary (blogs and commentary). Our USDC fees are **compensation for services**, not crypto investment gains. They are therefore business income or corporate taxable income, valued at the market price on receipt **already in 2026, regardless of the investment-tax start date**. For VAT, introduction/platform services are taxable services. Several tax-firm sources state that **if the fee is received in crypto, the 0% VAT rate for exports does not apply**, even when the client is overseas.

### Cited Findings
- Gains from selling or lending crypto are "other income" taxed separately at 22% including local tax (20% + 2%), with a KRW 2.5 million annual deduction. The tax applies from 2027-01-01, with the first return due May 2028. The market price on 2026-12-31 can be used as the acquisition cost for crypto bought earlier. — [wikidocs (2026년 8월 기준 해설)](https://wikidocs.net/blog/@Insight_Lab/28203/); [로톡](https://www.lawtalk.co.kr/posts/159885)
- Conflicting views: some sources say another postponement is possible, while an August 2026 commentary says that after the tax reform proposal "it goes ahead as planned this time". We **did not find primary sources** from the NTS or the Ministry of Economy and Finance. — [wikidocs](https://wikidocs.net/blog/@Insight_Lab/28203/); [glasswallet](https://glasswallet.com/calculate/crypto-tax/taxation-system-guide/)
- Supplying crypto itself is outside VAT. However, crypto-related brokerage, advisory and **platform services** are supplies of services and are subject to VAT. If the fee is received in crypto, sales are generally recognized at the crypto's market price when the service is completed. Any later difference on conversion to cash is treated as a loss on disposal of intangible assets or similar. — [세무법인 블로그(mstacc)](https://blog.mstacc.com/?p=918); [흠택스](https://www.heumtax.com/contents/posts/untitled-1743742595212)
- The 0% VAT rate for services supplied abroad requires payment through a method the tax law specifies (e.g., receiving foreign currency through a foreign exchange bank). **If the service fee is received in crypto, the 0% rate does not apply.** If the essential part of the service is performed in Korea, the 0% rate may also be denied. — [mstacc 칼럼](https://blog.mstacc.com/columns/blockchain/1492); [bznav](https://help.bznav.com/hc/ko/articles/53282397984409)
- The AI Basic Act (인공지능 발전과 신뢰 기반 조성 등에 관한 기본법) and its enforcement decree **took effect 2026-01-22**. They impose transparency and safety obligations on providers of high-impact AI and generative AI. Fines are reportedly in a grace period of one year or more (sources differ on the length). — [법무법인 세종 뉴스레터](https://shinkim.com/kor/media/newsletter/3114); [요즘IT](https://yozm.wishket.com/magazine/detail/3568)

### Inferences
- **Individual vs. corporation:** If an individual repeatedly receives USDC as compensation for services, it is most likely **business income** (taxed at progressive comprehensive income tax rates) or other income, not "crypto investment income" **[UNCERTAIN, depends on facts]**. A corporation includes the market value at receipt in revenue for corporate income tax, and later gains or losses on converting the USDC also go into taxable income. Corporations have been taxed on crypto gains all along, regardless of the 2027 investment-tax start.
- **VAT impact:** Even if the clients are overseas AI agent operators, receiving payment in crypto loses the 0% rate. The service would then effectively bear 10% VAT, or there is a risk that the business is not recognized as an export business. Charging overseas clients through card or bank channels instead could be one way around this **[UNCERTAIN]**.
- **Electronic Commerce Act / mail-order brokerage:** If the platform brokers transactions between human users (or their agents) in Korea, it may count as a **통신판매중개업자** (mail-order broker). It would then need to register as a mail-order business and would have obligations to disclose seller information and handle disputes. If the operator is the party to the transaction, it is a mail-order seller (통신판매업자) instead. This is not directly sourced in this research; it is an inference from the general structure of the Electronic Commerce Act. For pure B2B (business to business) transactions, consumer-protection provisions may apply less **[UNCERTAIN]**.
- **AI Basic Act:** If the introduction service itself relies on generative AI, the generative-AI labeling and transparency obligations may apply. It is unlikely to be classified as "high-impact AI" **[UNCERTAIN]**.

### Gaps
- We could not confirm the NTS's official guidance (기본통칙 or interpretations) on receiving crypto as payment for services. Primary sources are needed for income classification and the valuation timing.
- We found no primary source on whether the 2025–2026 tax reform proposals changed the 2027 start date (e.g., the Income Tax Act amendment text).
- We could not verify the latest interpretations or cases on the scope of 통신판매중개업 under the Electronic Commerce Act (amended 2025–2026) through searches.

## Q3. Korean government and industry moves on AI agent payments (2026)

### Takeaway
On the industry side, **Kakao Pay announced on 2026-09-15 that it had completed a PoC of x402-based stablecoin AI agent payments**. It covered both buying and selling. On the selling side, it tested sellers of data such as weather and map ratings receiving stablecoin payments from external AI agents, which is very close to this business model. We **found no specific FSC policy, guideline or regulatory sandbox designation** for AI agent payments.

### Cited Findings
- Kakao Pay (2026-09-15): the user gives an AI agent a wallet with policies such as purchase authority and spending limits. The agent then pays in stablecoins within those limits, using the x402 protocol. The test covered wallet linking, payment, settlement, and balance, limit and policy management. Users can see payment history, limits and merchants in the Kakao Pay app. On the selling side, sellers of APIs or web resources (map ratings, weather data, etc.) sold data to external AI agents and settled in stablecoins. Kakao Pay said it plans to commercialize "while strengthening user protection in line with domestic digital asset regulation". It gave no service launch date. — [뉴스핌 2026-09-15](https://www.newspim.com/news/view/20260915000308); [KMJ](https://www.kmjournal.net/news/articleView.html?idxno=13638)
- Naver: monthly active users and average daily conversations for its shopping AI agent grew about fivefold from March to August. Consumer surveys show a preference for keeping final approval with the user. — [CBC뉴스](https://www.cbci.co.kr/news/articleView.html?idxno=614010); [뉴스웨이 2026-06-24](https://www.newsway.co.kr/news/view?ud=2026062412001566687)
- Toss: Toss Insight published a report on how AI agents will reshape competition in finance. We found no concrete plan for agent payments. — [검색 요약](https://www.newsway.co.kr/news/view?ud=2026062412001566687)
- Industry sees allocation of liability, protection of personal data, user authentication, delegation of authority and spending limits as the key institutional issues. — [CBC뉴스](https://www.cbci.co.kr/news/articleView.html?idxno=614010)

### Inferences
- Kakao Pay's selling-side PoC (data sellers receiving stablecoin payments from AI agents) is close to this business model. Because a large payment company is proceeding cautiously, "subject to domestic digital asset regulation", stablecoin payments in Korea are expected to stay mostly at the PoC stage until the phase-2 law passes.
- When the regulations are finalized, payment companies that hold an electronic financial business license and a VASP filing are likely to be first movers. A small startup has a realistic strategy option: receive USDC through overseas protocols such as x402, and avoid holding or converting funds itself.

### Gaps
- We found no official FSC position, guidelines or regulatory sandbox (혁신금융서비스) designations specific to AI agent payments.
- We could not confirm specific 2026 plans from Naver Pay, Toss and KB on agent payments.

## Q4. United States: GENIUS Act implementation, stablecoin acceptance, money transmission, and AI agent liability

### Takeaway
The GENIUS Act (signed July 2025) **takes effect 2027-01-18 at the latest** (or 120 days after final rules, if earlier). Rulemaking is still under way as of October 2026. The OCC proposed its rule in February–March 2026 and aims to finalize it by November 2026. Treasury published an interim final rule on 2026-09-30 that sets a $10 billion threshold for the state-regulation route, per a single press source. Circle (USDC) received an OCC charter in December 2025 and is on the federal track. The Act regulates **issuers** and does not directly restrict ordinary businesses from **accepting** stablecoins as payment. If the service does not custody or control funds, it is more likely to fall outside money transmitter status, but this depends on the facts.

### Cited Findings
- OCC proposed rule implementing the GENIUS Act, published in the Federal Register on 2026-03-02. — [Federal Register 2026-04089](https://www.federalregister.gov/documents/2026/03/02/2026-04089/implementing-the-guiding-and-establishing-national-innovation-for-us-stablecoins-act-for-the); [Sullivan & Cromwell](https://www.sullcrom.com/insights/memo/2026/March/OCC-Proposes-Regulations-Implement-GENIUS-Act); [Gibson Dunn](https://www.gibsondunn.com/occ-proposes-comprehensive-stablecoin-regulatory-framework-to-implement-the-genius-act/)
- AML/CFT and sanctions compliance proposal for permitted payment stablecoin issuers (Federal Register, 2026-06-24). — [Federal Register 2026-12692](https://www.federalregister.gov/documents/2026/06/24/2026-12692/permitted-payment-stablecoin-issuer-anti-money-launderingcountering-the-financing-of-terrorism-and)
- The OCC says it aims to finalize its rule by November 2026 so it can start processing applications in the new year. — [PYMNTS](https://www.pymnts.com/legal/2026/occ-races-the-clock-to-finish-genius-act-stablecoin-rules/)
- Treasury's interim final rule (2026-09-30, Federal Register 2026-19966), effective on publication, sets procedures for the Stablecoin Certification Review Committee. Issuers with $10 billion or less outstanding may choose state regulation; larger issuers must move to the federal framework within 360 days. The Act takes effect 2027-01-18, and the deadline for initial state certifications is 2028-01-18. Seven federal agencies reportedly missed the 2026-07-18 statutory rulemaking deadline. Circle received an OCC charter in December 2025. **Single press source (Forkast/Yahoo); verify in the Federal Register.** — [Yahoo Finance/Forkast 2026-10-01](https://finance.yahoo.com/markets/crypto/articles/treasury-first-genius-act-rule-073833593.html)
- Money transmission: licensing is mainly a state matter, alongside federal MSB registration with FinCEN. The trigger is **receiving funds or exercising meaningful control over fund flows**. Platforms that hold wallet keys, can pause or override disbursements, or pool user funds face more scrutiny. A pure, user-directed execution tool is more likely to be treated as a technology conduit. — [Fenwick 2026-04](https://www.fenwick.com/insights/publications/is-2026-the-year-of-agentic-payments)
- FinCEN's 2019 crypto guidance (FIN-2019-G001): MSB status depends on facts and circumstances, and the payment processor exemption is interpreted narrowly. A person who uses crypto to pay for goods or services on its own behalf is generally not a money transmitter. — [Sullivan & Cromwell memo](https://www.sullcrom.com/SullivanCromwell/_Assets/PDFs/Memos/SC-Publication-FinCEN-Issues-Updated-Convertible-Virtual-Currency-Guidance.pdf); [Manatt](https://manatt.com/Insights/Newsletters/Financial-Services-Law/FinCEN-Provides-Guidance-On-Cryptocurrency)
- AI agent payment liability: under the EFTA and Regulation E, an "unauthorized transfer" is one initiated by someone other than the consumer **without actual authority**. Whether giving an AI agent credentials counts as authorization, and who is liable when the agent goes beyond its instructions, are **legally unresolved**. Reg E generally does not cover crypto-native rails. — [Fenwick](https://www.fenwick.com/insights/publications/is-2026-the-year-of-agentic-payments)
- We found no CFPB rulemaking in 2026 specific to agentic commerce. Card networks lack a dispute reason code for agent errors, so merchants bear the cost by default. American Express's Agent Purchase Protection applies only to registered agents with authenticated purchase intent. Google's AP2 records user instructions and approvals with signed mandates. — [Forkast](https://forkast.news/the-agentic-commerce-liability-gap-who-pays-when-the-agent-buys-wrong/); [Backbase](https://www.backbase.com/blog/ai-agent-payment-liability); [ITIF/datainnovation](https://datainnovation.org/2026/03/agentic-commerce-is-coming-but-regulation-meant-for-humans-will-slow-it-down/)
- Federal AI policy: an executive order in December 2025, followed by a National Policy Framework for AI legislative recommendations in March 2026 (aimed at preventing a patchwork of state rules). These are not aimed specifically at agentic payments. — [Fenwick](https://www.fenwick.com/insights/publications/is-2026-the-year-of-agentic-payments)

### Inferences
- If a Korean company receives USDC fees from US agents directly into its **own wallet**, it is in the position of a payee, and the risk of US money transmitter status is relatively low **[UNCERTAIN]**. However, escrowing payments between agents, splitting or forwarding them, or managing wallets for clients could trigger FinCEN MSB registration and state money transmitter licenses, which would be costly.
- After the GENIUS Act takes effect, the ability of US digital asset service providers to offer stablecoins that are not permitted payment stablecoins is expected to be restricted (from the Act's general structure; **not confirmed in the sources gathered here**). USDC is on the federal track through Circle's OCC charter, so it is likely to be the safest choice for US-related transactions.
- OFAC sanctions screening (wallet address screening) applies to US persons. Even non-US companies may need it in practice, because of risks such as Circle freezing addresses.

### Gaps
- We could not confirm the provisions on digital asset service providers' handling of non-permitted stablecoins (Section 3 of the Act), or their implementing rules, from primary sources.
- We found no 2025–2026 primary FinCEN guidance on AI agent intermediaries or non-custodial brokers.
- We did not verify in this research the application of UETA (Uniform Electronic Transactions Act) electronic agent provisions, or 2026 case law on AI agent contracts.

## Q5. EU: MiCA treatment of USDC and the relevance of the AI Act

### Takeaway
USDC is an **e-money token (EMT) authorized under MiCA in France** and is one of the few large stablecoins that can be handled on regulated EU platforms (USDT is not). The MiCA **transitional period for crypto-asset service providers (CASPs) ended 2026-07-01** with no extension. Providing crypto services to EU customers without a license is now unlawful. For the AI Act, the high-risk obligations were **postponed through the Digital Omnibus provisional agreement of 2026-05-07** (to December 2027 / August 2028). The Article 50 transparency obligations largely stay on the original schedule.

### Cited Findings
- ESMA confirmed on 2026-04-17 that the MiCA transitional period ends 2026-07-01 with no extension. After that date, providing crypto-asset services to EU clients without a MiCA license breaches EU law. — [Coinpaprika](https://coinpaprika.com/news/mica-transitional-period-ends-1-july-2026/)
- USDC is described as an EMT authorized in France. Circle's USDC and EURC are described as the only top-ten stablecoins fully authorized under MiCA. Tether (USDT) did not seek EMT authorization and cannot be listed on regulated EU platforms. Sources disagree on the number of EMT issuers (19 vs. 23) and on the name of Circle's EU entity. — [StealthEX](https://stealthex.io/blog/mica-compliant-stablecoins/); [Scorechain](https://www.scorechain.com/blog/eu-stablecoin-regulation-mica); [Tangem](https://tangem.com/en/blog/post/stablecoin-mica-swap/)
- ESMA reportedly told national authorities that CASPs should stop servicing ART/EMT tokens that do not meet MiCA's conditions, with three months to comply. **Single source; verify against ESMA's own publication.** — [The Paypers](https://thepaypers.com/regulations/news/esma-gives-casps-three-months-to-drop-non-mica-compliant-stablecoins)
- AI Act: on 2026-05-07, the Council and Parliament reached a provisional agreement on targeted amendments through the Digital Omnibus. Obligations for stand-alone Annex III high-risk systems move to **2027-12-02**, and for AI embedded in Annex I regulated products to **2028-08-02**. The changes take legal effect only once published in the Official Journal. The Article 50 transparency obligations largely stay on the original schedule. — [Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/); [Hogan Lovells](https://www.hoganlovells.com/en/publications/eu-legislators-agree-to-delay-for-highrisk-ai-rules); one source gives the Annex I date as 2026-08-02 instead, likely a typo — [Winston Taylor](https://www.winstontaylor.com/insights/ai-act-rules-on-high-risk-ai-delayed-as-ai-digital-omnibus-agreed)

### Inferences
- If the service only **receives** USDC as payment for its own services, it is unlikely to be a MiCA CASP (custody, exchange, transfer services and similar are what require a license) **[UNCERTAIN]**. However, if it brokers or forwards payments between agents, it could count as a "transfer service" or "reception and transmission of orders".
- An AI-agent introduction service is unlikely to fall into an AI Act high-risk category. However, the Article 50 transparency obligations (disclosing interaction with AI, labeling generated content) may apply **[UNCERTAIN]**.
- EU consumer-protection rules (e.g., the Digital Services Act's online marketplace obligations) may apply depending on the platform's structure. This was not covered in this research.

### Gaps
- We could not confirm the final adoption and Official Journal publication date of the AI Act Digital Omnibus.
- We did not verify the ESMA notice on servicing non-compliant stablecoins against the original document.
- We found no MiCA guidance on whether a non-custodial payment-receiving service is a CASP.

## Q6. Liability and consumer protection when AI agents transact autonomously (mandates, authorization, disputes)

### Takeaway
In all three jurisdictions, existing payment law (US Reg E, Korean electronic finance and e-commerce law, EU) is designed around **human-authorized transactions**. Whether an AI agent's payment counts as "authorized", and who bears liability when the agent goes beyond its instructions (user, AI developer, platform or merchant), is **unresolved** as of 2026. Industry is filling the gap with technical and contractual tools: **signed mandates (AP2), x402, wallet policies (spending limits and permissions), and registered-agent protection programs**.

### Cited Findings
- Regulation E's test for unauthorized transfers depends on "actual authority", so it is unclear whether delegating to an agent counts as authorization. Consumers may lack standard dispute rights. AP2 signed mandates create an audit trail but have not been tested by courts or regulators. — [Fenwick](https://www.fenwick.com/insights/publications/is-2026-the-year-of-agentic-payments)
- Historically, a consumer's own authorization, even if given to a third party who misused it, has exempted banks from liability. — [Backbase](https://www.backbase.com/blog/ai-agent-payment-liability)
- In card disputes, merchants bear the cost of agent errors by default. American Express's Agent Purchase Protection applies only to registered agents and authenticated purchase intent. — [Forkast](https://forkast.news/the-agentic-commerce-liability-gap-who-pays-when-the-agent-buys-wrong/)
- In August 2025 the CFPB issued an advance notice (ANPR) on personal financial data rights, asking who can act as a consumer's "representative". — [검색 요약(Chargeflow/ITIF 등)](https://datainnovation.org/2026/03/agentic-commerce-is-coming-but-regulation-meant-for-humans-will-slow-it-down/)
- Kakao Pay's model controls agent payments through **wallet policies set by the user** (purchase authority and spending limits) plus real-time visibility in the app. — [뉴스핌](https://www.newspim.com/news/view/20260915000308)
- Korean industry identifies user authentication, delegation of authority and spending limits as key consumer-protection tasks. Consumers prefer keeping final approval themselves. — [CBC뉴스](https://www.cbci.co.kr/news/articleView.html?idxno=614010)

### Inferences
- **Business design implications:**
  1. Record the mandate given by each agent's owner (scope, limits, expiry) with a signature.
  2. Put clauses in the terms of service that allocate liability for agent errors and abuse.
  3. Accept payments only into the operator's own wallet, with no escrow.
  4. Keep refund and dispute procedures in fiat or off-chain processes.

  These reduce both regulatory and dispute risk.
- On-chain USDC payments are irreversible, so there are no chargebacks like with cards. That is an advantage for the receiving service, but it may also be judged inconsistent with consumer-protection rules such as the cooling-off and withdrawal rights in the Korean Electronic Commerce Act when consumers are involved **[UNCERTAIN]**.
- The Korean Civil Code's agency rules (apparent authority, unauthorized agency) are likely to be applied by analogy to AI agent actions. However, an AI is not a legal person, so it will most likely be analyzed as the user's tool (an expression of the user's own intent) **[UNCERTAIN]**. We found no Korean case law or government guidance on this.

### Gaps
- We found no official Korean government guidance on the validity of AI agent transactions or how to allocate liability (FSC, Fair Trade Commission, Ministry of Justice).
- We found no 2025–2026 primary rulemaking on agent transactions from the CFPB or the European Commission (e.g., the PSD3/PSR negotiations).
- We found no consumer-protection precedents or dispute cases involving stablecoin payments.
