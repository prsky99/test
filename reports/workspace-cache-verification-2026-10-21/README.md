# Workspace cache verification

Date: 2026-10-21

Current workspace caching is a short-lived page-memory read cache, not persistent browser or CDN storage of private pages. Local and public HTTPS GET checks confirm the current helper is embedded, page fetch calls use workspaceUI.request, private responses use Cache-Control: no-store and Cloudflare returns DYNAMIC on the checked public paths. Anonymous session/credit requests correctly return 401 with no-store; authenticated customer records were not accessed in these operating probes.

The helper reuses same-origin typed-workflow list/detail JSON reads for 10 seconds and coalesces simultaneous identical reads. It stores at most 20 responses, each at most 262144 JavaScript text code units. Reads with a query, fragment or fresh:true bypass the cache. Login/session, credits, execution history/status, model generation and package downloads are outside the read-cache allowlist. No customer response is persisted in localStorage/sessionStorage or a service-worker Cache API. Theme preference storage is separate.

Writes, unsuccessful responses, transport errors, page exit, hidden tabs and explicit refresh clear read entries; revision tracking prevents an earlier pending response from repopulating the cache after a write. Full navigation/reload starts with empty page memory. This improves repeated reads within one page, not cold-page loading or model inference time.

Ten isolated Chromium cache regressions passed: concurrent request deduplication, sensitive-path exclusions (five cases), mutation/error/manual-refresh invalidation, stale in-flight response handling, expiry/page-exit clearing and bounded cache/original-transport retention. Evidence: cache-final.xml and cache-final.log. Operating evidence: operating-headers.json (eight GET checks, four local/four public HTTPS).

One older test incorrectly expected visible progress for a programmatically initiated background read. Its expectation now matches the existing user-interaction-only feedback contract; the stale-response assertion remains intact. No production code, customer data, credits, provider configuration or cache policy was changed. No server restart is required. The initial browser.xml is historical and superseded by cache-final.xml.
