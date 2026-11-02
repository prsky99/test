# Workspace: human-centered redesign

Date: 2026-10-25. Scope: customer Workspace information architecture, AI/manual creation, protected templates, saved workflows, review/test/download, shared navigation, overview/account and credit presentation. This is an implemented change to the existing authenticated application, not a mockup.

## Why the old structure was difficult

The first screen mixed the task description, configuration, saved history, technical graph fields, execution authorization and app publishing. Users had to understand implementation concepts before choosing a task. Multiple unrelated actions competed for attention. Mobile navigation and long plans amplified the problem.

The new hierarchy starts with the user's goal. Advanced controls remain available when needed, while the existing authorization, credit ledger and execution state machines continue to enforce the action.

## Applied design

1. **Create with AI / Templates / My workflows** are separate screens. Returning users do not have an old workflow automatically opened over the first screen. Switching screens retains unfinished text.
2. **Create with AI** starts with one task description, three examples, a visible primary action and a short explanation of the currently supported public research/news/documentation tasks. AI input sharing remains an explicit unchecked agreement.
3. **Review → Try it → Use it** guides each workflow. Step cards show the agent and meaningful input. Long plans initially show three steps with an explicit expansion control. Technical identifiers, bindings and conditions are in advanced disclosures.
4. **Build step by step** includes a normal selector for written search text or an earlier step's result. It maintains the actual input binding and dependency; users do not need to edit JSON for this connection.
5. **Saving** has one confirmation showing the workflow, steps, exact credit charge and remaining balance. Selecting a template or generating a suggestion does not save, debit or execute an agent.
6. **Running** has separate fresh confirmation of the inputs and destinations. Ambiguous outcomes block automatic retries until current history is read. The latest/final successful result or relevant failure appears first, with other steps expandable.
7. **Download app** asks for an HTTPS app origin and explicitly explains the one-hour authorization and request limits before release/deployment. ZIP download is a separate visible action. Existing grant, role, run-success and origin checks remain in place.
8. **Templates** keep verified fallback visible. A saved template whose current verification has expired/been withdrawn retains readable inputs but cannot execute as an eligible template. Fallback permission is requested per execution.
9. **Navigation** prioritizes Overview, Workflows and Templates. Members, connections, credits and account settings are under Manage workspace. Mobile uses a real drawer, focus trapping, Escape/backdrop close, large targets and an inert main region while open. Light/dark themes and reduced-motion behavior remain supported.
10. **Overview and credits** prioritize the next useful action. Workspace selection, invitations, history, future paid features and plan settings are progressively disclosed. Required enrollment terms and the three independent unchecked agreements stay visible before enrollment. Optional members/draft reads load when their sections are opened.

All new product copy, comments and metadata are English. No additional customer identity collection, public access activation or advertising delivery was introduced.

## Research and how it was used

- [Microsoft: Guidelines for Human-AI Interaction, CHI 2019](https://www.microsoft.com/en-us/research/publication/guidelines-for-human-ai-interaction/): explain capabilities and limits, make correction possible and give useful feedback. Applied to supported-task copy, reviewable steps, loading and recoverable errors.
- [AI Chains: Transparent and Controllable Human-AI Interaction by Chaining Large Language Model Prompts](https://arxiv.org/abs/2110.01691): make intermediate work inspectable and editable. Applied to step inputs and result connections rather than a single opaque generate action.
- [PromptChainer](https://arxiv.org/abs/2203.06566): support inspection and debugging at multiple levels. Applied to a simple default path with optional exact settings.
- [Nielsen Norman Group: Progressive Disclosure](https://www.nngroup.com/articles/progressive-disclosure/): expose primary choices before advanced controls. Applied to navigation, history, publishing and account settings.
- [Reddit: a beginner describing automation overload](https://www.reddit.com/r/automation/comments/1p78u7u/completely_overwhelmed_where_do_i_even_start/): an anecdotal signal favoring a small goal and a useful template over setup terminology. SNS feedback was not treated as a representative usability study.

These sources informed an expert implementation review. No claim is made that independent designers with 30 years of experience participated or that a human usability study was performed.

## Defects found and corrected during implementation

- Initial automatic saved-workflow selection hid the task-entry path.
- Mobile header sizing caused overflow, and the brand mark overlapped the service name.
- A mutation observer repeatedly rewrote identical links and could starve rendering.
- Account content was incorrectly inside a container hidden by account navigation.
- A manual input selector was redrawn from its previous binding before its change event committed. Selecting written text could remain read-only. Event ordering and refresh were corrected; the regression checks the actual second-step request.
- Malformed advanced input could be blocked by native field validation without a useful parsing error. It now reaches the established, sanitized error handler.
- Manual/withdrawn-template screens could disappear during hash routing. Unsaved work now restores the editing screen after Cancel.
- The supported-goal parser interpreted “ten connected steps” as the default two. Bounded step qualifiers now retain the requested count, reject unsupported counts and preserve named-subject/version gates.

## Verification

**276 unique cases passed, 0 failed, 0 skipped**: 207 API/static/public-frontend cases, 53 existing browser journeys, 13 new human-centered browser journeys and 3 actual local-model journeys. Final results and test identities are recorded in `validation-summary.json` and the adjacent logs/XML. Screenshots use disposable identities and synthetic downstream agents.

- New task journeys: `human-final.log` / `human-final.xml`.
- Existing user journeys and dynamic security regressions: `browser-final.log` / `browser-final.xml`.
- API, signed review, credit, permission, private-page CSP, public frontend and PostgreSQL statement-catalog regressions: `api-static-authorized.log` / `api-static-final.xml`.
- Actual configured local-model generation: `model-ui-final.log`, three goals: ten connected documentation steps; news followed by documentation; three independent topics. Saving/execution uses synthetic customers and agent transports. This does not establish real external-agent availability or factual answer quality.
- Public content audit: `content-final.log`.
- JavaScript syntax and focused fatal/undefined Python checks: `lint-final.log`.
- Generated PostgreSQL catalog consistency: `catalog-final.log`. No schema migration or operational database writes were needed for this redesign.

Earlier failed logs are retained as evidence of discovery and correction. The initial unprivileged broad check had Chromium launch errors; `api-static-authorized.log` is the completed rerun with browser execution permitted. It passed all 207 cases.

Security checks include fresh consent, no implicit dispatch/debit, CSRF and cross-workspace denial, role restrictions, unsafe text rendering, session expiration/retained-data removal, uncertain execution, origin-restricted deployment and download recovery. Private API responses remain `no-store`; the new presentation does not persist customer results in browser storage. This is isolated browser/API testing, not a production penetration test.

## Changed implementation

- `agent_market/customer_studio_design.py`
- `new/live-assets/workspace-studio.js` and `workspace-studio.css`
- `new/live-assets/workspace-human.js` and `workspace-human.css`
- `agent_market/customer_typed_authoring_view.py`
- `agent_market/customer_workspace_pearl.py`
- `agent_market/customer_organization_service.py`
- `agent_market/workspace_support_view.py`
- `agent_market/workflow_goal_policy.py`
- `scripts/check_front_content.py`
- `agent_market/application_store_sql.json` (generated catalog)
- Affected browser journeys/helpers and goal-policy tests were updated to use the visible new UI while preserving credit, permission, privacy and execution assertions.

## Deployment and practical limits

The development server was not stopped, replaced or restarted. The user must run `agentcon restart frontend`, then refresh the customer tab to load the changes. Admin, jobs and execution worker replacement is not required by these presentation changes. Workspace publication remains at its existing setting.

No real customer's credits, workflows or login grants were modified. Actual production-session rendering should be checked after deployment. Measured usability with representative first-time humans, screen readers and a wider device/browser matrix remains a separate acceptance activity; automated checks cannot establish perfect usability or guarantee external-agent uptime.

## Follow-up deployment verification

The user deployed `frontend-rag-quality-20261025-r1`. Read-only checks confirm that the active B slot reports that release and is ready; the homepage and sign-in return 200, and the unauthenticated workspace redirects to sign-in (303). **The new Workspace design is not in this release.** The guided module and four new JS/CSS assets are absent. Six existing code files differ only in the redesign areas; all other packaged Python/JavaScript/CSS files match the current working source. The previously validated working files remain intact. Thus the deployed RAG code and the Workspace changes can be packaged together from the current working source. Deploying an existing release uses its immutable snapshot, rather than incorporating later working-directory edits. User command to package and deploy current source: `./agentcon restart frontend`. No service was changed during this verification.

### Restart confirmed

The active frontend is now `web-20261025-075656-953a`, slot B, ready. All 12 recorded implementation/catalog files exactly match the validated source and package manifest. The homepage/sign-in return 200; an unauthenticated Workspace request redirects to sign-in (303), and customer responses remain no-store. The served sign-in document now includes the redesigned shared navigation/styles. The new package additionally contains separate MCP contract changes in front.py; these were not modified during this check. This confirms package and runtime rollout; it does not claim an authenticated real-customer browser journey was repeated.
