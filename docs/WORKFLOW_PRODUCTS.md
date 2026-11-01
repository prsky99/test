# Verified workflow products

The first catalog contains three public-research products: **Research Search API**,
**Research Comparison Board**, and **Source Bibliography API**. They retrieve live
Crossref or arXiv records through the managed gateway. They do not generate fixed
business results, invented authors, scientific conclusions, or guaranteed uptime.

## Qualification and publication

1. Survey full native schemas and retain existing approval history. A conflicting
   current-version approval is rejected rather than silently replaced.
2. Test each explicitly approved native tool with real public English queries.
   Sign generic input/output mappings, preserving original source links/times.
3. Save private product drafts with bounded public keyword/result-limit inputs,
   typed local response transforms, and an independent pair for every agent stage.
4. Complete a normal shadow run. Enable bounded canary admission and perform one
   signed, private preflight-outage run per distinct primary provider. Actual
   alternative business dispatch, successful signed checkpoints and matching graph,
   tool versions, profiles, policy and authority are required. A client-supplied
   success flag or normal-only run cannot qualify.
5. Accept retained proofs, promote to protected active routing, then publish only
   passed products. Existing hub templates are preserved. Current accepted products
   are reused on repeated operator commands instead of creating duplicates.

Active routing selects every eligible **explicitly opted-in** product request,
with at most one alternative for the entire run, at most 1,000 admissions per
policy, and at most 24 hours. The operator uses a 23-hour window bounded by native
profile/evidence expiration. Canary defaults remain 10%, 100 runs and 24 hours.
Fresh review is required before expiry; this release does not silently renew
approval. Expired/changed/revoked products disappear from public projection and
new protected execution is denied. A protected run never silently becomes a
baseline run because consent, capacity or verification is unavailable.

The comparison board uses opposite primaries for its two stages. Either single
provider outage can be handled with one switch. Both providers unavailable,
uncertain post-dispatch timeouts, cancelled requests, and invalid authorization
are failures requiring inspection, not an invitation to repeat external work.
Different article/preprint coverage is disclosed. Different endpoints/operators
and source checks are negative dependency guards, not proof of complete physical
network/CDN independence.

## App interface

The existing `/api/workflows/templates`, `/api/workflows/run`, run status/cancel,
and template web-app download routes remain in use. Products add a declared
`input` object; caller graphs, provider identifiers, recipes, fault injection and
additional keys are rejected. Per-run input is signed into the snapshot, without
changing the saved graph or its fallback fingerprint. A run capability is required
to inspect/cancel a run and remains in memory/header transport.

The actual Pearl publication and legacy shell both show product input controls.
Each execution needs fresh alternative-sharing consent. Exported product ZIPs
contain an English static UI, CSP, accessible status/loading feedback, safe text
and HTTPS source links, a manifest, and deployment guidance. They call only
`https://agentconcierge.biz` and embed no provider URLs, admin credentials or
secrets. They do not automatically retry POST requests. Existing ordinary template
and administrator SDK export formats are unchanged; product packages use their
separate reviewed format. Public gateway rate limits still apply.

## Owner operation and rollout

Source deployment and operating qualification are distinct. The owner command
refuses mutations until frontend, admin, jobs and execution roles run matching immutable
product sources and pass readiness checks. It does not restart/deploy services or
start an HTTP server. Private filesystem ownership/settings authorize the local
owner identity, audited as `local-owner-command`/actor `0`; it does not impersonate
a named employee. Failed products remain private and their policies are disabled.
If no product is published and fallback was originally off, it is turned off again.

The reviewed empty `workflow_product_templates` PostgreSQL table must be installed
before attaching a new runtime. The additive migration never replaces existing
rows. Restores revoke product acceptance and require new qualification.

After the user deploys one immutable release to the four roles, run:

```sh
.venv/bin/python -m scripts.qualify_workflow_products
.venv/bin/python -m scripts.qualify_workflow_products --apply --authorize-public-provider-tests --publish-passed
```

The first command checks only readiness. The second makes real public read-only
calls, approves current reviewed contracts, creates/tests private workflows,
activates bounded fallback and publishes only passed products. Results and audit
records distinguish isolated trials from operating publication.

## Validation boundaries

See `reports/workflow-product-templates-2026-10-24/README.md`. Live tests use real
providers with controlled private preflight faults; external providers are not
shut down. Normal provider caches may return previously retrieved real records;
original retrieval times remain visible. General engine TCP shutdown/security
regressions additionally exercise actual isolated server interruption. Passing
these tests is not a zero-failure SLA or certification of every provider/query.

## Crossref quota handling

The public Crossref list API has a separate, lower quota than single-record reads.
The adapter serializes list calls and conservatively spaces them by at least 1.1
seconds after responses in each process, honors stricter bounded rate headers and
429 cooldowns, and refuses a new source request when the existing execution budget
cannot accommodate the wait. It never repeats a network request automatically.
Cross-process/provider throttling remains possible and follows ordinary explicit
fallback/failure policy. Source timestamps and cache ages remain truthful.

Primary references: [Crossref access and request limits](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/),
[Crossref list-request limit announcement](https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/).
