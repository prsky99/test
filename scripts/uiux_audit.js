// UI/UX·접근성 자동 측정. 기준은 docs/qa/uiux-evaluation-criteria.md
//
//   npm i playwright@1.56 axe-core@4.10   (한 번)
//   node scripts/uiux_audit.js https://agentconcierge.biz out.json
//
// 환경 변수: AUDIT_PAGES(쉼표로 구분한 경로, 기본 10개), CHROMIUM(실행 파일 경로), HTTPS_PROXY(프록시), SPKI(쉼표로 구분한 인증서 SPKI 목록)
//           AUDIT_MODES(desktop,mobile,w320,dark 중 일부)
// 측정 항목: axe-core(WCAG 2.2 AA + best-practice), LCP·CLS·INP(근사)·TTFB, 24px 미만 타깃,
//           Tab 25회 동안의 포커스 표시·가림, 가로 넘침, 랜드마크·skip link·라이브 영역.
// 화면 조건: 데스크톱 1366, 모바일 390, 320px 리플로, 다크 모드. 페이지 사이 1.5초 쉼.
const fs = require("fs");
const { chromium } = require("playwright");
const AXE = fs.readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");

const BASE = (process.argv[2] || "https://agentconcierge.biz").replace(/\/$/, "");
const OUT = process.argv[3] || "uiux_audit.json";
const PAGES = process.env.AUDIT_PAGES ? process.env.AUDIT_PAGES.split(",") : ["/", "/new/en/explore.html", "/new/en/chat.html", "/new/en/test.html", "/new/en/workflows.html",
  "/new/en/learn.html", "/new/en/agent-status.html", "/new/en/list-agent.html", "/new/en/about.html", "/customer/sign-in"];
const MODES = (process.env.AUDIT_MODES ? m => m.filter(x => process.env.AUDIT_MODES.split(",").includes(x[0])) : m => m)([["desktop", { width: 1366, height: 900 }], ["mobile", { width: 390, height: 844 }],
  ["w320", { width: 320, height: 640 }], ["dark", { width: 1366, height: 900 }, true]]);
const VITALS = `window.__v={lcp:0,cls:0,inp:0};
new PerformanceObserver(l=>{for(const e of l.getEntries())__v.lcp=e.startTime}).observe({type:'largest-contentful-paint',buffered:true});
new PerformanceObserver(l=>{for(const e of l.getEntries())if(!e.hadRecentInput)__v.cls+=e.value}).observe({type:'layout-shift',buffered:true});
new PerformanceObserver(l=>{for(const e of l.getEntries())__v.inp=Math.max(__v.inp,e.duration)}).observe({type:'event',buffered:true,durationThreshold:16});`;

function launchOptions() {
  const o = {};
  if (process.env.CHROMIUM) o.executablePath = process.env.CHROMIUM;
  if (process.env.HTTPS_PROXY) o.proxy = { server: process.env.HTTPS_PROXY };
  if (process.env.SPKI) o.args = ["--ignore-certificate-errors-spki-list=" + process.env.SPKI];
  return o;
}

async function measurePage(p, url) {
  const t0 = Date.now();
  const r = await p.goto(url, { waitUntil: "load", timeout: 90000 });
  await p.waitForTimeout(1500);
  const nav = await p.evaluate(() => {
    const n = performance.getEntriesByType("navigation")[0];
    const rs = performance.getEntriesByType("resource");
    return { ttfb: Math.round(n.responseStart), dcl: Math.round(n.domContentLoadedEventEnd), requests: rs.length + 1,
      transferKB: Math.round((rs.reduce((s, x) => s + (x.transferSize || 0), 0) + n.transferSize) / 1024) };
  });
  const btn = p.locator("main button:visible").first();
  // INP 근사용 클릭. 로그인 버튼처럼 다른 사이트로 넘어가는 버튼은 누르지 않는다
  const leaves = await btn.evaluate(e => /sign in|log in|continue with|google|github/i.test(e.innerText)).catch(() => true);
  if ((await btn.count()) && !leaves) await btn.click({ timeout: 3000 }).catch(() => {});
  await p.waitForTimeout(800);
  if (new URL(p.url()).origin !== new URL(url).origin) await p.goto(url, { waitUntil: "load", timeout: 90000 });
  const vitals = await p.evaluate(() => window.__v || {});
  await p.evaluate(AXE); // CSP가 있어도 동작하도록 주입 대신 평가
  const axe = await p.evaluate(async () => {
    const res = await axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"] } });
    return res.violations.map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, example: (v.nodes[0]?.target || []).join(" ").slice(0, 80) }));
  });
  const ui = await p.evaluate(() => {
    const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
    const ctrls = [...document.querySelectorAll("a,button,input,select,textarea,[role=button]")].filter(vis);
    const small = ctrls.filter(e => { const r = e.getBoundingClientRect(); return (r.width < 24 || r.height < 24) && !(e.tagName === "A" && getComputedStyle(e).display === "inline"); });
    return { controls: ctrls.length, smallTargets: small.length, smallExamples: small.slice(0, 3).map(e => (e.innerText || e.getAttribute("aria-label") || e.tagName).trim().slice(0, 20)),
      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth, lang: document.documentElement.lang,
      visibleH1: [...document.querySelectorAll("h1")].filter(vis).length, landmarks: ["main", "nav", "header", "footer"].filter(t => document.querySelector(t)).length,
      visibleLiveRegions: [...document.querySelectorAll("[aria-live],[role=status],[role=log],[role=alert]")].filter(vis).length };
  });
  await p.evaluate(() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); });
  const focus = [];
  for (let i = 0; i < 25; i++) {
    await p.keyboard.press("Tab");
    focus.push(await p.evaluate(() => {
      const e = document.activeElement; if (!e || e === document.body) return null;
      const s = getComputedStyle(e); const r = e.getBoundingClientRect();
      const ring = (s.outlineStyle !== "none" && parseFloat(s.outlineWidth) > 0) || (s.boxShadow && s.boxShadow !== "none");
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const top = y >= 0 && y <= innerHeight ? document.elementFromPoint(x, y) : null;
      return { ring, covered: !!(top && !e.contains(top) && !top.contains(e)), name: (e.innerText || e.getAttribute("aria-label") || e.tagName).trim().slice(0, 20) };
    }));
  }
  const f = focus.filter(Boolean);
  const keyboard = { tabbed: f.length, noVisibleRing: f.filter(x => !x.ring).length, covered: f.filter(x => x.covered).length,
    noRingExamples: f.filter(x => !x.ring).slice(0, 3).map(x => x.name) };
  return { status: r ? r.status() : null, loadMs: Date.now() - t0, ...nav, lcp: Math.round(vitals.lcp || 0), cls: +(vitals.cls || 0).toFixed(3), inp: Math.round(vitals.inp || 0), axe, ui, keyboard };
}

function summarize(res) {
  const ok = Object.values(res).filter(v => !v.error && v.status === 200);
  const pct = (arr, q) => { const s = [...arr].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(s.length * q))] : null; };
  const axeNodes = {};
  ok.forEach(v => v.axe.forEach(a => { axeNodes[a.id] = (axeNodes[a.id] || 0) + a.nodes; }));
  return {
    pages: ok.length,
    lcpP75: pct(ok.map(v => v.lcp).filter(Boolean), 0.75), clsMax: Math.max(...ok.map(v => v.cls)), inpMax: Math.max(...ok.map(v => v.inp)),
    ttfbMedian: pct(ok.map(v => v.ttfb), 0.5),
    axeSeriousOrCritical: ok.reduce((s, v) => s + v.axe.filter(a => ["serious", "critical"].includes(a.impact)).reduce((t, a) => t + a.nodes, 0), 0),
    axeByRule: axeNodes,
    smallTargets: ok.reduce((s, v) => s + v.ui.smallTargets, 0), overflowPages: ok.filter(v => v.ui.overflowX > 0).length,
    focusWithoutRing: ok.reduce((s, v) => s + v.keyboard.noVisibleRing, 0) + "/" + ok.reduce((s, v) => s + v.keyboard.tabbed, 0),
  };
}

(async () => {
  const results = {};
  for (const [mode, viewport, dark] of MODES) {
    const browser = await chromium.launch(launchOptions());
    const ctx = await browser.newContext({ viewport, colorScheme: dark ? "dark" : "light" });
    await ctx.addInitScript(VITALS);
    const p = await ctx.newPage();
    for (const path of PAGES) {
      try { results[`${mode} ${path}`] = await measurePage(p, BASE + path); }
      catch (e) { results[`${mode} ${path}`] = { error: e.message.slice(0, 150) }; }
      fs.writeFileSync(OUT, JSON.stringify({ results }, null, 1));
      await p.waitForTimeout(1500);
    }
    await browser.close();
  }
  const summary = summarize(results);
  fs.writeFileSync(OUT, JSON.stringify({ summary, results }, null, 1));
  console.log(JSON.stringify(summary, null, 1));
})();
