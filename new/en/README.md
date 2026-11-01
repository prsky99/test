# Pearl Connection — English implementation

This folder contains 43 HTML documents. Nine main views reuse the operating frontend runtime and APIs: Home, Agent Status, Learn, Explore, Test, Workflows, Chat, List Your Agent and About. Four account views reuse the existing native Google/GitHub sign-in and workspace/session logic. Thirty component and state boards remain explicitly labeled design references.

## Open with the existing application

After restarting the existing application from the project terminal, open:

- `http://127.0.0.1:8400/new/en/index.html`
- `https://agentconcierge.biz/new/en/index.html` when the existing public proxy is connected.

After the application reloads the updated server code, the default HTML entry at `/` uses this published Pearl presentation. The named `/new/en/` routes remain available. JSON requests to `/` retain their existing contract. All execution, searches, registration, consent, visitor transport and notification verification use the existing same-origin APIs. No Docker or Node installation is needed.

Opening an HTML file through `file://` provides a visual shell; live APIs require the existing application origin. Do not add broad CORS access or proxy private APIs to make file previews act as hosted applications.

## Data and behavior

Home and Agent Status use `/api/pearl/status`, with real catalog, reachability, status-check, category and 24-hour execution counts. Catalog fields come from one grouped query; task outcomes use the existing execution evidence summary. Home refreshes in place on the operating frontend's normal schedule. Other views preserve their editing state and have no automatic page reload. Agent Status refresh is explicit.

The operating frontend's full search and Load More, report drawers, testbench, workflow input review/execution, web app downloads, Chat protocol selection, footer dialogs and privacy/notification actions are retained. Provider availability, session/CSRF handling, access restrictions and verified destination requirements remain in force. This implementation does not enable closed customer Workspace access or pretend that disabled providers are available. Authorized provider sign-in continues to use the existing OAuth callbacks; external provider completion was not tested.

The pearl necklace uses one SVG viewBox for the cord and 23 graduated pearls. Mirrored coordinates keep both sides aligned, and the same geometry is used by the design publication and this implementation.

The footer follows the dedicated desktop/mobile reference: Policies, Your choices and Support columns become an ordered eight-link list on mobile. Operating footer buttons retain their existing policy, consent, notification and contact actions. Learn has five topic panels and three protocol choices with visible selection and keyboard navigation. The former alternate guide entry is removed. Protocol badges share the reference colors and capsule shape. Tests select an available news example on an untouched initial visit, without executing it; user input is retained.

## Edit and build

The shared necklace is generated from `new/necklace.py`. Edit shared design templates in `new/build.py`, `new/reference_pages.py` and `new/catalog_pages.py`, the implementation compositions in `new/presentation.py` and `new/menu_presentation.py`, the transform in `new/build_en.py`, and its bridge/theme in `new/live-assets/`.

From the repository root:

```sh
.venv/bin/python new/build.py
.venv/bin/python new/build_en.py
```

The second build extracts the current embedded operating HTML without importing or executing the application, preserves its event hooks, and applies the Pearl presentation. The server routing and aggregate API are in `agent_market/concierge/pearl_view.py`.

Shared footer markup is in `new/shared_ui.py`, Learn content in `new/reference_learn.py`, and shared interactions/presentation in `new/shared-ui.js` and `new/shared-style.css`. They are bundled into existing served assets so no new asset route is needed.

## Verification

See `new/qa/en-browser-audit.json`, `en-browser-audit-supplement.json`, `en-implementation-regressions.xml`, `en-regressions.xml` and `en-final-verification.json`.

Browser captures use an isolated synthetic catalog; comparison images do not represent operating service counts. Tests do not execute real providers, send inquiries or notifications, sign in to an external account, modify the operating database, or certify accessibility. The original production embedded HTML and `extracted_html.txt` remain synchronized.

The later `new/qa/visual-review/` evidence includes running-service captures before and after correction, actual read-only topic and footer-dialog clicks, and separate isolated browser/API security regressions. Its deployment record confirms the default entry after the user's restart.

The focused five-menu implementation is in `new/menu_presentation.py`, `new/live-assets/pearl-menus.css` and `new/live-assets/pearl-menus.js`. It preserves the serif/sans-serif type hierarchy, ink and muted blue text, teal actions, protocol capsules and gold pearl accents. Optional catalog selection, request presets and registration import keep their original actions. A new registration authorization checkbox precedes the existing contractual consent. No submitted payload or backend authorization contract is expanded.

Workflow input review displays the published template's request. Editing the canvas does not change the published run. The result area is empty until an actual run returns, and the existing modal remains available. Chat keeps one recommendation, privacy filtering, protocol precedence, newest replies first and purpose-specific task updates.

`new/qa/menu-review/index.html` compares the approved images with previous and current running screens. `live-audit.json` records four viewport widths, mobile dark surfaces and read-only interactions. `security-function-regressions.xml` covers the isolated function/security regressions. The running-service audit never submits a Chat task, registration, provider execution, login or notification permission.

## Task-oriented working menus

`new/ux_presentation.py`, `new/live-assets/pearl-ux.css` and `new/live-assets/pearl-ux.js` now apply the working-menu layout after the original visual compositions. Edit these sources and run `new/build_en.py`; the generated HTML and bundled assets are served by the existing application without restarting it. Reload an already-open browser tab to load the new assets.

- Explore retains 45 initial results and Load More, uses the full working width, and offers compact cards or a list without re-querying or resetting filters. Details open in the existing drawer. Desktop cards use three columns at 1440 px, two at tablet widths and one on phones.
- Test presents examples above the request, places Run beside the selected example, and reveals results on execution. Catalog selection, advanced settings, history and help remain available on demand.
- Workflows keeps template selection, published inputs and Run together. Results update inline; full details open explicitly. The canvas editor is optional. Selecting the current template does not erase canvas edits.
- Chat uses one conversation column, task starters fill the composer without submitting, and a failed request restores an unsent draft when the user has not typed a replacement.
- List Your Agent starts with the endpoint and the existing inspection/autofill action. Name and category share a desktop row. Submission guidance is expandable; authorization and contractual consent remain required.

The interaction review also covers first visits and repeated tasks. Home passes the chosen protocol to Chat and can show already-delivered catalog figures with their recorded timestamp while a status refresh is pending; unavailable figures are not invented. Explicit Explore-to-Test selection takes precedence over the initial news example. Test samples expose editable fields derived from their actual input, with JSON under Advanced, and Reset restores the current example. Agent search reads the catalog while preserving the current request until a new agent is selected. Workflow choices retain their positions, agent steps use clickable pearls, and the template browser fills the available width without duplicating the selection strip. Chat results keep separate, fully expanded cards in newest-first order, and each card opens its own details.

Published catalog reads use a single bounded request instead of replaying an eight-second timeout. Weather, stock and crypto task shortcuts use relevant task keywords rather than broad protocol/finance terms. This is not a claim that every arbitrary catalog query is fast under operating load.

`new/qa/journey-review/` contains the subsequent interaction evidence: running-service read-only checks, earlier failures, targeted repeats, four-width page captures and isolated browser/API regressions. Chat POST requests in the running-screen capture are intercepted with controlled responses; no operating task or recommendation is created. External provider execution, external sign-in and production form submissions remain outside this verification scope.

`new/qa/ux-review/index.html` compares actual before/after screens. The adjacent `live-audit.json` records read-only running-service checks at 1440, 1024, 768 and 390 px, plus other main views and mobile dark captures. Write operations, provider failures, polling and draft retention are exercised with isolated data in the browser regression suite, rather than by submitting work to the operating service.
