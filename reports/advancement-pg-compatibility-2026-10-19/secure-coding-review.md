# Secure coding and isolated dynamic review

The seven changed/new application modules were scanned with Bandit. The raw result is High0/Medium28/Low12, with no scan errors. The raw JSON is preserved; Medium/Low findings were reviewed by location in `static-review.json`, rather than relabeled as zero.

The SQL findings use fixed source identifiers, bounded placeholder arrays and bound values. The temporary-path finding is a Redis test-namespace classifier without file IO. The subprocess import belongs to the explicitly owned offline archive kernel, with fixed argv, no shell, scrubbed environment and private Unix-only cluster checks. Existing frontend fallback handlers were not widened.

Independent reviews reproduced and resolved hostile latency conversion, wrong-key credential mutation, invalid virtual-account writes, dual statement/cleanup failure, large-catalog upper median and rolled-back FTS cache ABA. The separate public cache delta reproduced five failures and was rejected; current guards recheck evidence and escape embedded JSON.

Dynamic evidence uses actual disposable PostgreSQL and in-memory provider/identity transports, plus isolated FastAPI and routed Chromium fixtures. It does not certify real provider quality, real IdP setup, operating load, payment, production migration, backup credentials, DR or HA. Public Workspace access remains disabled; administrator use is desktop only. No operating server or database was changed.
