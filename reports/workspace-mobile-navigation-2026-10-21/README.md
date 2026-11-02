# Workspace mobile navigation fix

Date: 2026-10-21

The previous mobile layout placed navigation links in one horizontally scrolling row and hid the discovery link. Later destinations were off screen and there was no visible scrolling affordance. Header actions also competed with the brand for narrow horizontal space.

Mobile navigation now uses two wrapping columns with all six workspace destinations visible. The discovery link occupies a separate full-width row. Navigation targets remain at least 48px tall; labels wrap and icons retain their width. Below 520px the brand and account actions occupy separate rows. Desktop navigation, existing local icons, theme controls and authorization remain intact.

## Verification

- 11 unique final browser cases passed, zero unresolved failures or skips. Current mobile regression covers 320, 360, 390, 480, 600 and 760px in light/dark themes; desktop restoration is checked at 1440px.
- All seven navigation links fit within the viewport without horizontal scrolling. Header controls do not overlap. Keyboard focus and Account navigation work.
- Existing AI generation, workflow loading, theme persistence, dirty-edit sign-out review, revoked-session concealment and stale-session response isolation passed in isolated customer fixtures.
- Public content check: 238 files, zero violations. Scoped test lint passed. CSS changes introduce no JavaScript, network dependency, dynamic data interpolation or permission changes. Existing CSP and browser privacy regressions remain intact.
- Operating GET /customer/organizations returned 200 with the new mobile CSS and CSP. CSS is read while rendering the response: refreshing the page applies this fix without restarting the server. No real customer session, data or credits were used.

The first run reproduced hidden mobile navigation. An intermediate dark-theme assertion used programmatic focus immediately after a mouse click; the final test explicitly enters keyboard input mode before checking the focus ring. Final XML supersedes that earlier result; verification-summary.json deduplicates all effective cases. This is a scoped layout and security regression, not a full platform penetration test.

Evidence: mobile-final.xml, browser.xml, security-interactions.xml, operating-css.json, public-content.log, static.log and verification-summary.json. Screenshots: navigation-320-light.png and navigation-320-dark.png.
