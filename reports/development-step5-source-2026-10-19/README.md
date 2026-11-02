# Final-plan steps 5 and 6: selected source verification

The owned source set is frozen in `source-manifest.json` with SHA-256 hashes.
This scoped freeze is distinct from a global source or operating acceptance.
The operating server and databases were not changed. All external protocol
responses used isolated mock transports; Chromium ran offline through test apps.

## Implemented paths

- Private customer typed workflow review, max-six-node literal/projection and
  declared boolean/enum branch compilation, whole-graph test, immutable release,
  deployment, PKCE SDK execution, ZIP download and revocation use the existing
  execution and release modules. Runners cannot author or approve SDK policy.
- Explicitly consented model proposals now have a concrete
  `OllamaGraphProposer(endpoint, model, http=None)` HTTP adapter, installed through
  `PrivateIntegrations.model_proposer`. It is absent by default. Endpoint and model
  are immutable operator configuration. Only an attested public objective,
  approved resource/contract references and public schemas leave the server.
  Transport is bounded, strict JSON only, without redirects or automatic retries.
  Authority, adapter generation and candidate pins are rechecked before sending
  and after response. Proposals require exact graph review and a separate save;
  model output grants no execution or release authority.
- Reviewed bounded support JSON patches create a new draft. Source workflows,
  active runs and permissions cannot be changed through a patch.
- The separate private A2A 0.3 session profile supports same-context continuation,
  retained status, explicit cancellation and SSE cursor resume. Frames persist
  durably; stale or cancelled stream results cannot overwrite current state.
  Typed DAGs do not await arbitrary long A2A tasks. This boundary is explicit in
  the private studio and profile metadata. No provider replay guarantee is
  inferred merely from the existence of a cursor.
- Approved finite public source snapshots provide actual `docs.search.v1`
  retrieval and excerpts. This implementation does not self-approve quality,
  confer ranking priority or publish an untested corpus.
- Optional task feedback is consent-bound, scoped to a retained customer run and
  independently withdrawable, including after membership removal. Customer
  reports are distinguished from execution and independently verified quality.
- SDK lifecycle policy now pins current customer owner role and workspace,
  membership, identity and organization revisions. Missing signed/current owner
  state fails closed. Updates require the expected policy revision.

## Verification

- `model-sdk-final.xml`: 84 passing latest concrete-model, typed proposal/support,
  customer policy and affected factory tests.
- `customer-browser-final.xml`: 4 passing offline Chromium customer graph,
  concrete model consent/support new-draft and A2A continuation/resume journeys.
- Earlier affected suites and exact scopes are recorded in the manifest; their
  counts overlap and must not be added as unique tests.
- Final changed Python files compiled successfully. Remote admin JavaScript
  syntax was checked. Bandit is unavailable in the local environment, so no
  Bandit success is claimed.

Operator-approved actual model, A2A and corpus acceptance remains separate from
these source/mock tests. Public Workspace navigation remains closed. No money,
advertising, customer notifications or real provider operations were performed.
