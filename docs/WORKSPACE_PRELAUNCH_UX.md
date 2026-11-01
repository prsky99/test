# Workspace UI acceptance contract

The native customer experience shares the Pearl shell through `customer_workspace_pearl.py` and `new/live-assets/workspace-pearl.css`. It is distinct from administrator screens and from illustrative design-preview pages.

The studio has four stages: Design, Review & save, Test, and Download. Keyboard arrow/Home/End navigation follows the active tab. AI generation is advisory: only an explicit reviewed save consumes the applicable credit. A saved workflow, its editor contents, the prepared test and the release must agree. An objective/name/step change clears the previous review, execution authorization and release controls; tests remain blocked until the proposal is saved or the original is deliberately reloaded. Replacing unsaved contents or signing out requires a discard choice. Do not persist private drafts/objectives in browser storage.

On entry, the latest signed workflow is read when one exists. Choosing a saved option does not silently replace the editor. Organization context is carried by validated opaque references in same-origin links and never substitutes for current server authorization. Initial reads are bounded and independent lookups run concurrently. Optional feedback/A2A availability cannot fail core access initialization. A2A recovery cannot clear uncertain graph-run state. No ambiguous mutation is automatically repeated.

Export requires a successful tested saved version, current owner authority, an unexpired release, separate exact HTTPS-origin authorization and active credit enrollment. Existing active deployment downloads are restored through the scoped customer GET endpoint. Reading history does not call an agent, create a release, extend authorization or debit a credit. Download errors are rendered in the studio.

Overview makes AI workflow creation the primary organization action. Team controls, advanced single-task drafts, organization settings and account deletion are secondary disclosures. Account sign-out is available from the shared header. Recovery and app authorization preserve the same appearance, CSP and private metadata. Recovery completion remains gated by server proof validation and the review deadline; client state never grants authority.

Acceptance uses disposable identities/databases with real handlers, explicit enrollment, no implicit agent dispatch, role/origin/CSRF/IDOR checks, XSS-safe rendering, read-only history, ZIP downloads, all four stages, unsaved-state dialogs, both themes and narrow/keyboard layouts. See `reports/workspace-prelaunch-2026-10-20/README.md` for actual scope and evidence. Provider or infrastructure integration tests are reported separately; a synthetic UI pass does not imply a live provider pass.

Public navigation remains operator-controlled. An operator restart and live smoke check are required after Python view changes; agents must follow the repository's user-managed server rule. Opening Workspace is a separate explicit decision after acceptance.

The shared theme control uses the public Pearl pill shape and `pearl-preview:theme` session preference, with a validated legacy preference fallback. It supports native button keyboard input, visible focus and a 44-pixel pointer target. Dark-theme selected stages use contrasting foreground text.

AI readiness requires a configured suggestion service and current eligible approved candidates. Historical approval metadata alone is insufficient. Reading current history updates readiness without replacing unsaved inputs. A failed advisory request never consumes credits. Safe error copy distinguishes sign-in expiry, changed connection/access, invalid proposals and an ambiguous mutation.

Download requests use a bounded fetch and explicit manual retry. Failed read-only requests cannot clear a retained uncertain mutation. ZIP revision lookups use the safe application conflict boundary. The final opening decision must include a live verified-agent journey; an external timeout remains a provider limitation even when accounting and replay protection pass.

The 2026-10-20 defect follow-up adds the first-party Research Papers contract for
new reviewed workflows and fixes duplicate account runtime generation, embedded
export SDK metadata corruption and page-specific structured-data navigation.
See `reports/workspace-defect-remediation-2026-10-20/README.md` for the latest
source and live acceptance. Earlier external-provider unknown runs remain
historical evidence and are not silently repaired or resubmitted.
