# SDK 1.2: reviewed deployment and per-run authority

2026-10-18 · bounded informational deployment profile · source implementation and isolated operating tests are tracked separately.

The new SDK is an explicit administrator export choice. Public SDK 1.0 and administrator SDK 1.1 retain their packages and APIs. SDK 1.2 adds a server-reviewed deployment grant and two fresh, purpose-specific authorizations for each manual run. Its public publish key and Origin allowlist remain deployment controls, not proof of a person's identity.

## Initial supported scope

The first profile supports an already published, approved literal informational compiler template using `news.search.v1` and/or `docs.search.v1`. It runs the server's canonical pinned definition with its reviewed fixed public inputs. A public projection is a display/export boundary, not execution authority. Dynamic input fields, arbitrary graphs, credentials, fallback, extended budgets, result delivery, schedules and events are excluded from this profile.

This does not publish a private connected draft or a controlled pair. Existing connected-publication, export and runtime refusals remain in force. A future public news-title-forwarding release needs its own versioned publication/input-sharing profile, canonical definition, safe projection and explicit public-run authorization. The private pair purpose cannot supply those permissions. Publication and automation consent are not collected while those actions remain unavailable.

News inputs keep their explicitly reviewed absolute `from_utc`. A new run does not silently shift that window or pretend that an old query is a fresh 24-hour digest. The exact query, language, result limit and any news start time appear in the run preview; current contract, connection, approval and evidence checks can refuse an expired or changed deployment.

## Review and export

The highest administrator selects SDK 1.2, reviews the exact supported definition, approved recipients, fixed inputs, allowed origins, limits and expiration, and explicitly authorizes that deployment. An owner-bound signed preparation response is not a grant. Changes to selections, origins, limits or expiry invalidate the preview and unchecked approval. Closing, session changes and late responses cannot download a stale authorization.

A registered app and its independent signed deployment grant bind the published projection and internal canonical definition, approved bindings, fixed inputs, origins, limits, owner and expiry. The grant has a revocation revision. It does not authorize another workflow, a changed definition, public title forwarding, automation or result delivery. Its private payload is stored on the server and is not embedded in the downloaded bundle.

The bundle contains only public configuration and local frontend assets. It calls the Agent Concierge gateway, keeps run capabilities in memory/request headers, and includes restrictive CSP. No provider credential, raw private graph, grant payload, original upstream endpoint, visitor identity or automatic tracking is exported.

## Prepare and run

The app first requests a short-lived signed run ticket. This does not invoke a provider or model, admit a run or grant the client permission to change inputs. Current catalog checks can refresh internal registry metadata. The preview shows the complete approved public argument objects and safe recipient aliases. It does not display private proof or a raw server response.

Sharing authorization and one live execution authorization are separate, initially unchecked and bound to that exact ticket. The SDK submits one Execute request only after both are supplied. A ticket binds the app, current grant revision, exact definition/input scope, Origin, notices, expiration and a nonce. A copy of a publish key, an old administrator checkbox, a private test purpose or a legacy notification flag supplies no such authorization.

The server resolves the canonical definition and signs the new deployment-run purpose into the normal execution principal. Admission, tool dispatch and recovery recheck the current deployment/grant, owner role, exact binding, controls, expiry and run scope. The standard 25-second absolute execution deadline, durable queue, fence, prepared/dispatched certainty and unknown-outcome rules remain authoritative.

Accepted-run status and cancellation use the signed active deployment metadata, origin and existing run capability. They do not require the provider to remain eligible, the publication-test checkpoint to remain available or invocation controls to stay enabled. A failed or uncertain provider response therefore remains visible without granting another invocation. Revocation and capability expiry still limit access.

The accepted nonce uses the existing durable run idempotency boundary. Repeating the same accepted, still-authorized request can return the original run and its scoped capability; it cannot create a second run. Changed, revoked or expired scope is refused. The SDK never automatically repeats Prepare/Execute/Cancel POSTs after a network failure. Status polling uses bounded GET retries, and a monitoring timeout does not assert server cancellation or safe replay of an uncertain provider request.

## Revocation and restore

Revocation is a highest-administrator action using the current grant revision. It retains the grant tombstone, invalidates subsequent execution and requests cancellation of unfinished runs. Dispatch checks remain necessary because a worker can already own a queued run when revocation occurs. An in-flight external request can finish; no exactly-once external-effect guarantee is introduced.

The legacy SDK 1.1 start path cannot execute an app identified as SDK 1.2, including a revoked or expired grant. Legacy mutation paths cannot bypass the new revision/role checks. Old SDK 1.1 deployments retain their existing behavior.

Registration stages the app as inactive. Only after the grant is signed and stored does the final database mutation activate it. This remains fail-closed if a legitimate registry refresh commits a nested metadata transaction before grant validation fails: any orphan stays inactive and cannot fall through to the legacy start path. Grant tombstones continue to identify SDK 1.2 after revocation.

Backup restore deactivates grants, increments their revision and retains the inventory needed for explicit new review. Paused execution controls and reissue requirements prevent old signed tickets or restored app records from automatically becoming current authority. Grant/nonce tombstones are not automatically deleted to regain an execution path. The PostgreSQL rehearsal includes the new execution-state table; it is not a complete Store/catalog/auth/ledger migration.

## Evaluation and privacy limits

Successful invocation records ordinary managed execution/contract evidence. It does not create an expert grade, automatic winner, factual/source-quality certificate, unseen holdout or publication approval. Actual independent review, reviewed source materials, access enforcement and chronological pre-run allocation remain separate operating work.

SDK 1.2 controls apply to its registered-deployment routes. Existing public template APIs remain independently available for supported literal templates; a publish key is not a global paywall or an authentication mechanism. Public connected drafts and private controlled pairs remain unavailable through those legacy routes.

Frontend copy, source comments and generated package metadata are English. Existing Chat, public workflow downloads, footer task updates, destination verification and separate marketing permission are unaffected. Per-run execution consent does not imply marketing consent.

## Versioned API and bounds

The profile is `literal-informational-deployment-v1`; SDK metadata is `1.2.0`. The separate notices are `workflow-app-v12-deployment-grant-v1`, `workflow-app-v12-share-v1` and `workflow-app-v12-run-v1`. They are not interchangeable with publication, connected-flow, fallback, result-delivery or automation notices.

All administrator routes below require the current highest-administrator session plus the existing dashboard/origin/CSRF protections, use bounded request bodies and return `no-store` responses:

- `GET /admin/api/workflows/{workflow_id}/export-app-v12/options` reports current availability, public configuration, defaults and deployments.
- `POST .../prepare` takes exactly `allowed_origins`, `minute_limit`, `day_limit` and `ttl_seconds`; its signed review includes the fixed recipients and inputs.
- `POST .../package` or `POST .../html` takes the signed proposal plus explicit `grant_authority` and `grant_notice`.
- `GET .../deployments` exposes non-secret grant status/revision/expiry.
- `POST .../deployments/{app_id}/revoke` takes the current integer `revision`.

At least one exact HTTP(S) origin is required, with no wildcard or file/null-origin fallback. Start limits retain the existing 1–30 per minute and 1–5000 per UTC day bounds, with the existing per-IP limit. Requested grants last 300–86400 seconds but are shortened to the original retained successful test's validity; an unusably short proposal is refused. Per-run tickets last at most 300 seconds and never outlive the grant. The fixed news start time is disclosed and validated without moving it.

Public package requests use `X-Publish-Key` at `/api/workflow-apps-v12/{app_id}`. `POST /prepare` accepts only an empty object. `POST /runs` requires the exact signed proposal and separate sharing/live declarations. `GET /runs/{run_id}` and `POST /runs/{run_id}/cancel` additionally require the scoped `X-Workflow-Key`. Errors do not echo submitted proof, private graph, key, path or stack trace. Prepare has a separate bounded quota operation and does not consume the only start slot of a one-start deployment.

Signed administrator proposals contain canonical definition hashes rather than a round-tripped Store object. Integral timestamps are normalized before signing; verification itself stays strict. This avoids JavaScript's `0.0` to `0` serialization changing the HMAC while keeping the graph server-side. The SDK treats an execution HTTP 400 as uncertain after submission, because an error after durable admission is not proof that no run was accepted.

The user operates the development server. New Python behavior requires the user's restart and authenticated acceptance. Source/UI markers, isolated fixture success and previous-version observations are not a substitute for current operating acceptance. Development tests use isolated databases/providers/browsers and temporary ports; production grants, publication, provider tasks, notifications and automatic maintenance are not created merely to populate a screen.

Current source verification and operating limits: [v1.18 report](../reports/advancement-sdk12-consent-2026-10-18/README.md).

The later [public news-to-documentation connection](WORKFLOW_PUBLIC_CONNECTIONS.md)
uses its own canonical test, publication grant and manual-run routes. This literal
SDK profile still refuses connected graphs. Publication permission does not extend
an existing SDK deployment or authorize its automation.

[Connected SDK 1.3](WORKFLOW_CONNECTED_SDK13.md) is a separate export and deployment
profile for an already published canonical news-to-documentation connection.
It does not extend this literal SDK 1.2 grant, its tickets or its routes.
