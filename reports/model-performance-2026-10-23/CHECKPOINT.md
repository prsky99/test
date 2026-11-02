# Model benchmark completed

User requested feature performance/quality and real C1/4/8/16 concurrency. Completed 364 actual remote model calls with synthetic/public inputs: 56 native functional, 145 initial direct load, 154 additional direct load, 2 isolated app calls, 6 format diagnostics, 1 HTTP-error recheck. HTTP 200=362, 422=2. Real scheduler reached16, no restart or production mutation. Scope does not include external agent execution or browser load tests.

Evidence: RESULT.ko.md, analysis-summary.json, functional.json, concurrency.json (original), concurrency-regraded.json (actual adapter normalization), additional/concurrency.json, application-admission.json, format-diagnostic.json, 422-diagnostic.json, metrics samples, frontend-read-performance.json, source-provenance.json, health-final.json. 7 model-related modules match active frontend release web-20261023-143347-416f.

Findings: C16 plain p95 1.808s, JSON 11.830s; workflow 38.218s and semantic0/16 (14 HTTP200, 2 HTTP422), guidance18.417s semantic0/16 and all beyond10s app budget. Contract planner C16 16/16 quality. Legacy intent/lead/RAG adapters are not current public Chat. Native single-request workflow1/16, guidance1/8 under limited rubric. Initial docs objectives less explicit; extra test explicitly prohibits news and still fails. HTTP422 not reproduced individually; no unsupported cause or safety inference.

AppFactory existing process semaphore2: 2/16 completed,14 WorkspaceConflict,actualmodelpeak2. Do not blindly increase to16 before quality/queue/deadline work. Report includes prioritized improvements; no runtime fix performed within this benchmark scope.

Verification:88 affected unit/model/workflow/shared-security tests passed,1 isolated real-model app test passed,Python compile passed. Final modelhealthy, scheduler0/0,home200,workspaceguest303. Analytical canvas created and opened/queued at ~/.cursor/projects/Users-kingstonelee-workspace-A2A_Discovery/canvases/model-performance-2026-10-23.canvas.tsx. Canvas exports/props checked against SDK; host compile status not available in current hidden window.

No old-model baseline, TTFT,cold start,long soak or general accuracy claim. All comparison/rate/sample caveats included. Task complete; future fixes require separate scope, no restart currently needed.
