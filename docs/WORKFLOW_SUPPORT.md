# Scoped workflow support and reviewed JSON patches

`workspace-support-proposals-v1` supplies approved local guidance and
deterministic private-draft patch proposals. The initial implementation makes
zero model/provider calls. It does not execute terminal commands, inspect
customer servers, fetch source URLs, execute a workflow or publish a release.

The source-owned guidance covers private snapshots, bounded manual execution,
typed product evidence and change review. Only these fixed documents are
available; callers cannot supply a path, retrieval URL or alternate corpus.
Their content hash is included in a proposal. Guidance is not provider factual
evidence or an expert-quality score. Own-agent status creates no recommendation
or evaluation priority.

A writable owner/editor with a current individual session selects an active
private draft and its current immutable snapshot. The service accepts desired
name, description and, optionally, a named MCP node's complete literal input.
It generates only `replace` operations for those known paths. Arbitrary JSON
patches, graph/endpoint/authority changes, templates and known sensitive strings
are refused. Existing registered-tool/schema and private literal validators run
when preparing and again when applying. No input is forwarded to an agent.

The server-side signed `wsp_` proposal binds exact scoped objects, current draft
and snapshot state, source documents, workspace/member/role/session state and a
15-minute deadline. Preparation is independent of application. Applying requires
another initially unchecked explicit notice and consumes the reviewed proposal.
The current session and ACL are rechecked under a native writer reservation;
the draft CAS update, new signature, proposal consumption and audit record are
atomic. A recorded replay returns the same applied revision and never applies
another change. The immutable saved snapshot stays unchanged and non-executable.

Proposal history is metadata-only. Reading a proposal body requires current
workspace membership and active parent draft/snapshot. Revocation and archive
cannot expose old proposed inputs through the history endpoint. Global legacy
workflow/run/export tables are not used.

The centered native dialog displays server-generated paths and values as text,
keeps proposal state in memory, clears it on selection/session/modal changes
and does not retry POST requests automatically. Applying a patch does not grant
execution, external sharing, delivery, deployment, publication or payment.

This is the bounded read/propose/apply support unit. Broader diagnosis, actual
models, independently evaluated answer quality, customer identity integration,
support staffing and four-week reuse/business outcomes need their own evidence.
Known private/secret patterns are rejected; this is not a universal PII or
prompt-injection detector. The absence of model/command execution prevents
document text from becoming executable instructions in this profile.
