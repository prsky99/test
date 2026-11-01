# Generic input and output transformations

2026-10-24 · deterministic mappings for private workflows and R-06 MCP fallback

## Design and research

The implementation uses explicit schema-to-schema transformations, then validates
the actual result. This follows the bounded rewrite direction of
[Synthesizing JSON Schema Transformers](https://arxiv.org/abs/2405.17681).
[AI-assisted JSON Schema Creation and Mapping](https://arxiv.org/abs/2508.05192)
describes combining suggested mappings with deterministic execution; this release
implements deterministic execution and administrator-authored rules, not an
autonomous model authorizer. [Gorilla](https://arxiv.org/abs/2305.15334) motivates
binding current tool documentation rather than assuming old arguments still fit.

[n8n's official parser documentation](https://docs.n8n.io/integrations/builtin/cluster-nodes/sub-nodes/n8n-nodes-langchain.outputparserstructured)
supports schema-based output handling. Its [production playbook](https://blog.n8n.io/production-ai-playbook-deterministic-steps-ai-steps/)
separates deterministic checks from AI generation. A
[Reddit discussion](https://www.reddit.com/r/n8n/comments/1i8jq8g/tool_agent_error_with_structured_output_parser/)
reports inconsistent parser results. That is anecdotal failure context, not a
benchmark or authority for bypassing schema validation. No third-party code or
instructions from social posts are executed.

## Pure transformation nodes

Node types are `input_transform` and `output_transform`. Both execute locally;
their `data.input` uses existing upstream-output references. `data.transform`
contains exactly `version`, `input_schema`, `output_schema`, and `expression`.
The version is `json-io-transform-v1`. Both root schemas describe JSON objects.

Supported expression operations are `get` (JSON Pointer), `const`, `object`,
`map`, `coalesce`, `choose` (typed equality), `string`, `integer`, `number`,
`boolean`, `trim`, `lower`, `upper`, `concat`, `take`, `utc`, and `parse_json`.
Array items are evaluated against their own object; missing required fields fail.
No arbitrary expressions, eval, filesystem, HTTP, model calls, regex execution,
clock reads, automatic format repair, or provider retry are available.

Example expression for renaming input fields and converting an explicit decimal:

```json
{"op":"object","fields":{
  "term":{"op":"trim","value":{"op":"get","path":"/query"}},
  "count":{"op":"integer","value":{"op":"get","path":"/requested_count"}}
}}
```

`coalesce` uses the first available non-null value and preserves false/zero.
Numeric conversion rejects booleans, non-finite numbers, fractional integer casts
and values outside the exact-integer safety range. `utc` requires an original
timezone and preserves the instant. `parse_json` rejects duplicate keys,
non-finite values and Markdown fences. Reserved prototype-related keys are refused.

Data and recipes have explicit size/depth/count budgets: 32,000 encoded bytes,
2,000 data nodes, 100 array items, 128 expression nodes, expression depth 12,
and 10,000 evaluation operations. Unsupported native schema references/patterns
remain refused by the existing offline validator. Local transform nodes make no
provider call and do not create execution/contract evidence.

The existing private canvas exposes Add Input Transform and Add Output Transform,
a recipe inspector, and ordinary input/upstream bindings. These nodes are not
automatically published as public templates. The separate staff/customer typed
workspace flow profiles retain their existing definitions and publication rules;
this change does not silently relax those formats.

## Verified profiles for differing native tools

A generic engine alone is not a fallback grant. An administrator must first
explicitly approve the current registered tool for an informational contract.
`workflow_io_profiles` stores an immutable signed profile only after one to three
real native proxy executions pass both mappings and the canonical validator.
Tests use public, non-sensitive input and require explicit purpose-specific
authorization. A preview performs zero provider calls and grants nothing.

The input recipe joins the exact canonical input schema to the current native
input schema. The output recipe joins the exact native output schema to the
canonical output schema. Native read-only/idempotent/non-destructive hints,
unpriced public admission, current full schema pins and native argument validation
remain required. Source URLs and timestamp fields must originate in provider
data, not literal fabricated records or refreshed local timestamps.

Configure `status_checks` explicitly for provider success/error semantics. Each
check has a JSON Pointer `path` and either scalar `allowed` values or an
`equals_input` pointer to the original canonical request. All configured checks
must pass. An unavailable response must not be mapped into an empty success.
Pass through truthful partial-result indicators; do not assume unknown results
are complete. Schema validity alone does not establish factual accuracy,
functional equivalence, source completeness or infrastructure independence.

Profile IDs (`io_` plus 32 hex characters) bind resource/version/tool, contract
approval timestamp, rule bodies, implementation digest, actual-test artifact
hashes, actor and a maximum 24-hour lifetime. Changing any binding, revocation,
schema, approval or implementation blocks reuse. Restore revokes all profiles.

An agent node can set `data.io_profile` for normal input/output conversion. In a
fallback pair, the alternative may set `alternate_io_profile`; its native tool
can have a different name and schema. The signed policy pins the profile digest.
Both ordinary and fallback business dispatch recheck the profile, and the output
is validated before reaching the next agent. Same-address/host/shared-dependency
guards are unchanged. Conversion failures do not authorize retries after an
uncertain external outcome; one alternative attempt per run remains the limit.

## Private operator controls

The renewed console's **Service Settings (T05) → Input/output transformation
review** provides current schemas, separate input/output previews, real-call
authorization, signed-profile creation and revocation. Fields are not persisted
in browser storage; logout/navigation closes the dialog. Local validation errors
can be corrected, while unknown write outcomes require inspection before retry.

Highest-administrator private APIs (all no-store):

- `GET /admin/api/workflow-io-profiles`
- `GET /admin/api/workflow-io-profiles/schemas?resource_id=...&tool=...&contract_id=...`
- `POST /admin/api/workflow-io-profiles/preview` with `recipe` and `input`
- `POST /admin/api/workflow-io-profiles/verify` with `profile`, `cases`,
  `authority=true`, `notice=verified-io-transform-v1`
- `DELETE /admin/api/workflow-io-profiles/{id}`

The profile object contains exactly `resource_id`, `tool`, `contract_id`,
`input_transform`, `output_transform`, and `status_checks`. No client may submit
successful evidence instead of actual calls. Machine tokens, other staff roles,
cross-origin writes and public frontend routes cannot use these controls.

After profile verification: save an explicit independent pair in shadow mode,
complete the bound primary workflow, promote to a bounded canary, then enable
the global switch. Enabling without a current eligible canary is rejected;
disabling remains available even when providers or profiles are invalid.
Per-run input-sharing consent remains separate and unchecked by default.

## Storage and deployment

The PostgreSQL catalog includes 230 tables and 3,704 statements for this batch.
`python -m scripts.migrate_workflow_io_profiles --check|--apply` checks/adds only
the new empty profile table; it never rewrites existing rows or enables fallback.
The migration was applied and actual PostgreSQL 18 Store schema attachment passed.
Deploy the same source batch to frontend, admin and execution. Jobs need no restart
for these changes. Server operations remain the user's responsibility.
