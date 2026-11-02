# Conditional typed-DAG SDK 2 export

Current source verification passed **102 unique pytest cases**: 93 combined typed/single SDK/core/default-portal-hold regressions, plus nine additional cross-profile/public-hold/platform integration checks. Zero failures, errors or skips. Final Bandit reported zero findings; both new JavaScript assets passed syntax validation. The public content check inspected 77 files with zero violations.

The isolated fixture runs two typed MCP steps through the actual customer gateway/BFF/code exchange and ZIP assets, with whole-graph review, fresh unchecked consent, retained per-run capabilities and safe text output. Current authority tests cover release/deployment/member/session/controls/graph/approval/binding/restore changes before dispatch and during first/final responses, unknown outcomes, exact notice/immutable inputs, app scope, CSRF/bounded JSON, customer edit denial and history without output decryption.

The offline desktop tests use the actual exported app and the actual fixed admin asset from the dashboard route, scoped test APIs, native centered dialog, ZIP download and session reset. The fixed dashboard script nonce was checked; screenshots were visually inspected. The management interaction fixture isolates the component rather than claiming an operating dashboard session.

No operating provider, IdP, notification or payment service was called. Public Workspace access remains closed by default. PostgreSQL operating cutover and real hosted BFF/IdP/provider acceptance remain separate. Existing single-tool SDK 2 and public 1.x behavior remain under their own contracts.

See `verification.json`, `regression.xml`, `integration.xml`, `bandit.json`, the two PNGs and `docs/WORKSPACE_TYPED_SDK2.md`.

The actual current private PostgreSQL application rehearsal additionally passed 42/42 nested contracts, including six dedicated typed SDK 2 checks: generated ZIP, customer PKCE/cookie exchange, whole-graph no-call review/exact consent, two-node execution and replay with opaque attribution, retained history/status, and deployment revocation. These six native checks are separate from the 102 pytest cases. See `../pg/application-native.json`; its exact SHA and unchanged source binding are recorded in `verification.json`. This remains a removed synthetic Unix-socket cluster, with no operating cutover or provider calls.
