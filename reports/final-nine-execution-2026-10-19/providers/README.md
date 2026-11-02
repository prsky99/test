# Subscription provider investigation — 2026-10-19

The user authorized investigating and, where supported, testing Gemini and
Claude subscription sign-in alongside the existing local ChatGPT evaluation.
Only public research text and the already approved Paper Finder/docs contract
reference were used. No customer graph, private input, source tree or tool access
was given to either model. No extra credits, API-key fallback or subscription
purchase was enabled.

## Gemini

Official documentation supports personal Google account sign-in in Gemini CLI,
including Google AI Pro/Ultra accounts, and permits headless operation with a
previously cached login. This establishes a supported native CLI route; it does
not establish a customer-facing Gemini OAuth integration for Agent Concierge.
Direct use of CLI OAuth credentials through other software is expressly
restricted in its service notice. Google/GitHub customer identity credentials
are unrelated and were not reused.

The installed official CLI0.37.1 completed Google authentication and stored its
own credentials in the isolated ignored profile, mode0600, but could not finish
service initialization. A separate official npm package0.64.0 was installed
without lifecycle scripts in the ignored test directory. Its version was
checked, and one public planning attempt returned `UNSUPPORTED_CLIENT` in4.983s.
There was no completed graph. This is not evidence of exhausted subscription
quota. No further requests or internal-endpoint/token workarounds were tried.
The existing global CLI was not replaced.

See [safe result](gemini-personal-result.json).

Sources: [official authentication](https://geminicli.com/docs/get-started/authentication/),
[headless output](https://geminicli.com/docs/cli/headless/),
[terms and privacy](https://geminicli.com/docs/resources/tos-privacy/).

## Claude

Current official help describes subscription use through the Agent SDK and
native CLI. The SDK overview and legal page separately restrict offering a
developer's own Claude login or intermediating customer subscription credentials.
The legal page permits an end user to sign into the unmodified CLI, subject to
its stated conditions. We therefore tested only the native personal route;
these sources do not justify building a raw-token hosted adapter.

Official CLI2.1.89 completed sign-in using its native flow and a separate ignored
configuration directory. Its status reported `loggedIn=true`, `authMethod=claude.ai`
and `apiProvider=firstParty`; credentials were not printed or copied into the
application. The first public generation reached the local validation harness,
which failed because the system interpreter lacked the pytest dependency of an
imported test helper. That attempt is not counted as accepted evidence.

The corrected probe used the project interpreter and production compiler
directly. One subsequent request using the official `sonnet` alias returned a
valid compact two-step research plan in8.135s. Built-in tools, MCP, hooks, Chrome,
skills, session persistence and API-key/provider overrides were disabled. Both
steps referenced the approved resource34807/`docs.search.v1`. This proves native
subscription sign-in and planning, not customer-workflow save, actual agent
execution, general factual quality or hosted customer integration.

See [safe result](claude-personal-result.json). Account/profile/session IDs and
tokens are excluded. The CLI manages its own credential storage; the hosted
application does not ingest it. The status response's email was null, so exact
email ownership is not inferred from it; see [bounded account status](claude-account-status.json).

Sources: [subscription help](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan),
[SDK overview](https://code.claude.com/docs/en/agent-sdk/overview),
[credential and native-hosting conditions](https://code.claude.com/docs/en/legal-and-compliance).

## ChatGPT and product state

The prior user-requested inference hold is preserved. No ChatGPT inference was
sent here. Its hosted sign-in remains conditional on the registered/approved
website profile; see [official website guide](https://developers.openai.com/siwc/website).
Neither a successful native Claude test nor a Gemini login changes that boundary.
Public Workspace navigation remains hidden. The existing local Ollama provider
and user-operated project server configuration were not changed.
