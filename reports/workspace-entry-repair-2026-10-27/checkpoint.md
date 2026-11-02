# Workspace entry repair — completed 2026-10-27

User explicitly approved Frontend-only A/B deployment. Deployed workspace-entry-20261027-r3 to slot b PID13740; previous Frontend retained. No further deployment/restart required.

Approved r2 functionality was rebased onto latest payment-hardening-20261027-r2 after detecting a newer live base. No overlap among 9 changed base files and 9 Workspace files. 1303 other files and current front.py preserved. deployment-rebase.json and staged-release-approved-r2.json record provenance. Actual immutable release verified before/after deployment.

Final candidate tests: 181 passed/0 failed in rebased-candidate-tests.log. Candidate content308/zero. Previous root309/zero; Ruff S baseline2/current2/new0; Python/JS syntax pass. Anonymous route inventory90 (GET41 POST49), all401 in isolated tests with no fixture DB writes.

Live GET-only acceptance:25 passed/0 failed, live-after.json. Admin/Jobs/Execution complete status and proxy PID unchanged against services-before-deploy.json. Actual Chromium:9 passed/0 failed, no blocked requests or JS errors, live-browser-after.json. Deep-link return/fragment, fresh-visitor copy, support redirect, no guest form and mobile layout verified. No actual customer OAuth login, form submission or Provider execution. No Worker/DB-schema/Secret changes.

Changes: auth before CSRF/field validation; first visit vs observed expiry; safe local destination sealed into one-use OAuth; anonymous status200; read-only OAuth landing document support; private support gate; safe exception correlation IDs; no automatic mutation replay.

Reported prior three disconnections remain uncorrelated: historical ApplicationStoreError is insufficient evidence. Safe log review and precise limits remain in README.ko.md/local-log-review.json. Task complete; report outcome without more tests or restarts.
