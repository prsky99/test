"""Preserve server-rendered daily home metadata during public navigation.

11-14 (PM plan 1): the Pearl pages no longer carry the daily payload as inline JSON (3.4 KB on every page, the same
as the home page's own ld+json and description). The runtime reads it, in order, from an inline
<script id="dailyHomeMetadata"> (the legacy page still has one), from the home page's own head (its ld+json and
description are that payload), or, on another page, from /daily-home-metadata.json when the visitor first opens
Home. Only <head> metadata depends on it; nothing visible waits for it.
"""

MARKER = 'const DAILY_HOME_METADATA_URL = '
OLD_BLOCK = '''const DAILY_HOME_METADATA = (() => {
  try {
    const node = document.getElementById("dailyHomeMetadata");
    return node ? JSON.parse(node.textContent) : null;
  } catch (error) { return null; }
})();
'''
NEW_BLOCK = '''const DAILY_HOME_METADATA_URL = "/daily-home-metadata.json";
let DAILY_HOME_METADATA = (() => {
  try {
    const node = document.getElementById("dailyHomeMetadata");
    if (node) return JSON.parse(node.textContent);
    if (location.pathname === "/" || location.pathname.endsWith("/index.html")) {
      const ld = document.head.querySelector('script[type="application/ld+json"]');
      const desc = document.head.querySelector('meta[name="description"]');
      if (ld && desc) return {description: desc.getAttribute("content"), graph: JSON.parse(ld.textContent)};
    }
  } catch (error) {}
  return null;
})();
let dailyHomeMetadataRequest = null;
function loadDailyHomeMetadata() {
  if (DAILY_HOME_METADATA || dailyHomeMetadataRequest) return;
  dailyHomeMetadataRequest = fetch(DAILY_HOME_METADATA_URL, {credentials: "omit"})
    .then((r) => r.ok ? r.json() : null)
    .then((data) => {
      if (data && data.description && data.graph) {
        DAILY_HOME_METADATA = data;
        if (typeof currentTab === "undefined" || currentTab === "overview") updatePageMeta("overview");
      }
    })
    .catch(() => {});
}
'''


def daily_metadata_runtime(runtime):
    if MARKER in runtime:
        return runtime
    if OLD_BLOCK in runtime:  # an operating.js built before 11-14
        runtime = runtime.replace(OLD_BLOCK, NEW_BLOCK, 1)
    else:
        runtime = runtime.replace('function updatePageMeta(tabId) {', NEW_BLOCK + '\nfunction updatePageMeta(tabId) {', 1)
        runtime = runtime.replace('  document.title = m.title;', '''  if (tabId === "overview" && DAILY_HOME_METADATA) m.desc = DAILY_HOME_METADATA.description;
  document.title = m.title;''', 1)
        runtime = runtime.replace('const data = JSON.parse(script.textContent);', '''const data = JSON.parse(DAILY_HOME_METADATA ? JSON.stringify(DAILY_HOME_METADATA.graph) : script.textContent);
        if (tabId !== "overview" && Array.isArray(data["@graph"])) {
          data["@graph"] = data["@graph"].filter((node) => node["@type"] !== "Dataset");
          data["@graph"].forEach((node) => {
            if (["WebPage", "AboutPage"].includes(node["@type"])) {
              delete node.dateModified;
              delete node.hasPart;
            }
          });
        }''', 1)
    # Ask for the payload the first time Home is shown on a page that does not carry it.
    runtime = runtime.replace('  if (tabId === "overview" && DAILY_HOME_METADATA) m.desc = DAILY_HOME_METADATA.description;',
                              '  if (tabId === "overview" && !DAILY_HOME_METADATA) loadDailyHomeMetadata();\n'
                              '  if (tabId === "overview" && DAILY_HOME_METADATA) m.desc = DAILY_HOME_METADATA.description;', 1)
    return runtime
