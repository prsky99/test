"""Preserve server-rendered daily home metadata during public navigation."""


def daily_metadata_runtime(runtime):
    marker = 'const DAILY_HOME_METADATA = '
    if marker in runtime:
        return runtime
    runtime = runtime.replace('function updatePageMeta(tabId) {', '''const DAILY_HOME_METADATA = (() => {
  try {
    const node = document.getElementById("dailyHomeMetadata");
    return node ? JSON.parse(node.textContent) : null;
  } catch (error) { return null; }
})();

function updatePageMeta(tabId) {''', 1)
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
    return runtime
