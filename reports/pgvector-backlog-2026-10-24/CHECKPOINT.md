# Active pgvector backlog investigation and repair — 2026-10-24

User asks whether pgvector migration/indexing works; queue >50k. Then user says Ollama started. No subagents. No process restart authorization. Current operating database writes0/process replacements0.

Confirmed using readonly PG18.6/pgvector0.8.2:
- Source generation on Mac mini OpenAI, LOCAL_OLLAMA_ENABLED=0. Production RagEngine.embeddings_enabled tied to that flag; RagPipeline.step returns disabled before claims. Jobs heartbeat alive, not paused, pending attempts0; not DB performance failure.
- Initial queue56170, later56252; 24h/1h indexed0. Last success Oct23 13:45:10KST. ANN134110 includes46789 obsolete projection rows. Valid current vector+ANN87256; most queued56169 missing current raw vector due normal invalidation.
- Local Ollama was off, user started; now /api/tags includes original embeddinggemma-2:270m-mxfp8-text (768). Actual model isolated new/index update2requests passed; source model digest same4da17...; no production writes. Starting Ollama alone does not alter running flag.

Implemented:
- config.py independent optional embedding_enabled/url; defaults preserve old disabling if no explicit override. URL/boolean validation.
- scripts/agentcon_config.py read_embedding_settings separate opt-in profile; host startup+CLI loads gateway-data/embedding.env. Created owner0600 profile embeddingenabled1 URLlocalhost11434. Old local-model.env and Mac mini settings unchanged.
- gateway/server.py uses explicit embedding switch/url without changing generation.
- collector rag_status real result/time/count/error and service_host heartbeat vector_index.
- admin_console_operations fallback status field and collection.js indexMessage now reports disabled/error/unconfirmed/actual progress accurately.

Verification root: first combined129passed,1initdb environment failure (test_service_split native cluster); standalone service subset4pass overlaps129; separate native retry still initdb failure. Browser/admin20passed (4status cases + existingAPI) and collector38passed ->187 unique passed +1 unavailable setup. Config unit20passed. Actual Ollama+isolatedSQLite2flows passed1.069s/0.019s (not throughput claim). Publiccontent253/0. New testsruffpass.

Prepared reviewed immutable overlays from each active release, not whole dirty workspace; no operating state changed:
- jobs pgvector-embedding-20261024-r1 fivecorefiles, manifestvalid, stagedunit20pass.
- frontend pgvector-embedding-frontend-20261024-r1 fivecorefiles, stagedunit20pass.
- admin pgvector-embedding-admin-20261024-r1 fivecore+adminstatusAPI/JS, stagedunit20pass; firstbrowser hit capture outputrelativepath failure after actual UI assertion passed. Fixed test screenshot output anchored to source root. Admin stagedretest running /tmp/verify_embedding_web_packages.py filteredadmin; log prepared-admin-retest.log / prepared-admin-tests.log. Need confirm24pass before ask approval.

Next:
1. Confirm admin staged24pass, final staticchecks/sourcehash/manifests/generationprofileunchanged.
2. Ask via request_user_input_async for permission to replace jobs+frontend+admin with exact prepared IDs and verify production indexing, cite AGENTS no stop/restart/replace without explicit request. User only started Ollama; not permission to restart jobs. Complete reviewable preparation first. Execution worker unchanged.
3. While waiting finish RESULT.ko.md/validation manifest. If user approves apply only three reviewed commands, staged IDs; verify before any replacements active bases unchanged and overlays current. Then timed readonly snapshots show lastindexed/current vectors increasing, queue reducing; actual pipeline heartbeatstate correct, ready web and hashes. Do not delete queue/obsolete ANN manually; same-model preserved87k vectors, pipeline drains bounded work.
4. If user opts self apply provide exact3commands. Never claim fixed live until workers swapped and progress measured.

Files/artifacts reports/pgvector-backlog-2026-10-24: snapshots, current-coverage, provider probes, actual embedding isolated, RESULT.ko.md, prepared release manifests/results, testlogs, screenshots. Targeted debugging, Canvas skill exemption applies; no canvas needed. No more general audit expansion. Preserve previous finance/other dirty source. Need report actual PostgreSQL write test environment limit.

## Approval clarification
User answered the replacement permission question: “어드민을 재시작 해줘? 뭘 재시작 해야 하는지 모르겠음.” Treat as unclear scope, not authorization to replace jobs/frontend. No process changed. Explained jobs is essential for ingestion, frontend query embedding, admin status display. Sent a new concise async confirmation with options “필요한 세 서비스 모두 적용해줘” / “직접 실행할 명령어 알려줘”, citing exact AGENTS rule. Await explicit answer; do not infer approval from delay.
Admin staged retest24passed; frontend20passed; jobs20passed, manifests3reverified and all prepared file hashes still match source. Ruff5preexisting server.py issues,0new; current source and tests compile, JSparse,publiccontent253/0. Root187pass plus1nativeinitdbsetupfailure. All preparation complete.

## User-approved activation completed
Explicit user answer: 필요한 세 서비스 모두 적용해줘. Applied exact prepared jobs/frontend/admin IDs successfully. activation.json verifies generation file unchanged and execution worker unchanged. Three live readonly samples20s apart show pending56265→56220→56185 (net-80/40.1s), publications87290→87336→87377 (+87), maxindexed advancing, heartbeat embedding_enabledtrue/last_batch50/failures0. Both web roles ready and HTTP200; new admincollection JS hash matches; anonindex401. No manual queue deletion/fullreset; automatic worker now writes expected new vectors. See post-activation-progress.json. Main user request fulfilled: cause established, code repaired, activated with consent and actual backlog drain proven. Remaining backlog processes automatically; do not claim allcomplete or schedule unrequested monitoring. Finalreport updated; no more restarts needed.
