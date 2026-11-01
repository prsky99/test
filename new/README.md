# Pearl Connection — HTML publication

The approved pearl necklace concept, its reference images, and an isolated HTML/CSS/JavaScript publication live together in this folder.

## Open the publication

- [Home](html/index.html)
- [Agent Status](html/agent-status.html)
- [All layouts](html/gallery.html)
- [Compare browser captures and reference images](html/compare.html)
- [Workspace](html/workspace.html)
- [Google / GitHub account creation](html/sign-up.html)
- [Sign in](html/sign-in.html)
- [Account and sign out](html/account.html)
- [Downloaded web app interface](html/webapp.html)
- [Visual review and corrections](qa/visual-review.md)

Open `html/index.html` directly in a browser. No Node installation or build step is required. For an isolated HTTP preview, run this command from the repository root:

```sh
.venv/bin/python new/qa/preview.py --port 8767
```

Then visit [the local preview](http://127.0.0.1:8767/html/index.html). Stop this preview with Ctrl+C when finished. This read-only helper serves only the new HTML and design folders. It is separate from the existing application server.

## Files

- `design/concept/`: the approved original Pearl Connection direction.
- `design/pages/`: eight main and public page reference images.
- `design/system/`: sixteen footer, layer and common UI reference boards.
- `design/workspace-auth/`: nine workspace and authentication reference boards.
- `design/manifest.json`: 34 reference image paths and SHA-256 fingerprints.
- `html/`: 43 HTML documents, including the gallery, comparison and standalone web app preview.
- `html/assets/styles.css`: shared tokens, typography, layouts, components, themes and responsive rules.
- `html/assets/necklace.css`: generated decorative pearl placement.
- `html/assets/app.js`: local navigation, forms, tabs, search, dialogs and button feedback.
- `html/assets/pearl.png`: a transparent decorative pearl generated with the built-in image tool.
- `html/assets/previews/`: real desktop and mobile browser captures used by the comparison page.
- `html/assets/webapp-preview.zip`: the downloadable local workflow interface preview.
- `publication-manifest.json`: page inventory and reference mapping.
- `asset-prompts.md`: the decorative asset generation prompt and method.
- `qa/`: checks, browser results, screenshots and review notes.

Original references were copied without alteration. The three unselected design directions are excluded. Typography uses local system fonts, icon paths are embedded locally, and no CDN or external script is required.

## Catalog status design revision

The [revised Home](html/index.html) and [Agent Status](html/agent-status.html) implement the two approved images in [design/revisions/2026-10-19-catalog-status](design/revisions/2026-10-19-catalog-status/README.md). Home leads with four catalog metrics and links to protocol discovery, recent changes and recorded checks. Agent Status adds protocol totals, connection observations, execution outcomes, selected categories and definitions.

Both pages read the same captured public aggregate snapshot through `catalog_pages.py`. The visible timestamp is 19 Oct 2026, 10:07 UTC. The counts are real captured aggregates; the HTML is a static design preview, not a live dashboard. No random count changes, background page reloads or automatic refresh timers are used. The manual Refresh data button reviews the snapshot with button feedback and explains that live updates are not connected. Production integration must update Home metrics in place and preserve input on other pages.

Protocol and category links apply safe, allowlisted filters to the eight-agent example collection in Explore. New-arrival links identify the preview boundary rather than inventing arrival dates. A category can have no matching example even when the real snapshot has listings.

The 34 original image fingerprints remain unchanged. Two revision images are verified separately. `publication-manifest.json` explicitly maps the superseded original Home reference to its approved revision. The gallery and desktop/mobile comparison use the current revisions.

## Interactions and scope

The publication provides responsive navigation, light and dark themes, accessible native dialogs with Escape and focus return, tab keyboard navigation, illustrative search and additional results, input review, form validation, import review and a downloadable interface with button loading.

Catalog aggregate counts are a timestamped snapshot; agent cards, individual records and execution results are examples. Provider buttons, invitations, inquiries, notification preferences and workflow actions do not call a production API or change real accounts. This is the publishing stage of the design. Production integration, real Google/GitHub authentication, notification verification and real agent execution require their existing server-side boundaries.

Policy prose is taken from the repository's existing public legal documents. The eight footer destinations remain available. Example boards may show multiple separate states; this does not mean those layers open simultaneously.

## Editing and rebuilding

Edit HTML templates and copy in `new/build.py` and the two catalog page templates in `new/catalog_pages.py`, and edit the CSS and JavaScript in `new/html/assets/`. Rebuild generated documents with:

```sh
.venv/bin/python new/build.py
```

`webapp.html` and its dedicated `assets/webapp.js` are standalone source files. Rebuilding does not modify the existing production frontend, database or server configuration. Direct edits to generated HTML are overwritten by a rebuild.

Run the checks with the existing project environment:

```sh
.venv/bin/python new/qa/check_publication.py
.venv/bin/python new/qa/browser_audit.py
.venv/bin/python new/qa/catalog_viewports.py
.venv/bin/python new/qa/check_preview.py
.venv/bin/python scripts/check_front_content.py
.venv/bin/python new/qa/finalize.py
```

The browser audit requires the project's existing Playwright/Chromium installation. It uses a temporary loopback port, isolated browser context and no production database. The finalizer copies the final captures to the comparison assets and refreshes the downloadable web app and publication archives.

## Verification limits

The QA notes report actual checks. Pixel-perfect equivalence to generative raster text is not asserted. Browser font metrics, responsive reflow, complete policy text and independent state examples can differ from a reference board's fixed dimensions. The current workflow does not certify accessibility or validate production providers and agent endpoints.

## English implementation

The separate [English implementation](en/README.md) is available under `new/en/`. Its main views reuse the operating frontend runtime and same-origin APIs. After the existing application is restarted, open `/new/en/index.html` from that application origin. File previews do not connect to live APIs. The original `/` frontend remains available.

The necklace now uses a single responsive SVG coordinate system, a continuous cord and 23 mirrored, graduated pearls instead of independent CSS positions and rotations. Both `html/` and `en/` use the corrected geometry.
