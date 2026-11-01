// Finds content a visitor cannot see or reach by scrolling (UI policy 11-01, round 20 audit).
// Returns {clipped, traps, covered, offscreen}; each item names the element and its sizes.
async () => {
  // Smooth scrolling would move the page after scrollIntoView returns; measure settled positions.
  document.documentElement.style.scrollBehavior = 'auto';
  document.body.style.scrollBehavior = 'auto';
  const label = (e) => {
    const id = e.id ? '#' + e.id : '';
    const cls = typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '';
    return e.tagName.toLowerCase() + id + cls;
  };
  const shown = (e) => {
    if (!e.getClientRects().length) return false;
    for (let n = e; n; n = n.parentElement) {
      const c = getComputedStyle(n);
      if (c.display === 'none' || c.visibility === 'hidden' || c.visibility === 'collapse' || Number(c.opacity) === 0) return false;
      if (n.hidden || n.closest('[inert]') || n.closest('dialog:not([open])') || n.closest('details:not([open]) > :not(summary)')) return false;
    }
    return true;
  };
  const meaningful = (e) => e.querySelector('a[href],button,input,select,textarea,[role=button]') || (e.innerText || '').trim().length > 0;
  const clipped = [], traps = [], covered = [], offscreen = [];
  const all = [...document.querySelectorAll('body *')].filter(shown);
  for (const e of all) {
    const c = getComputedStyle(e);
    if (['SCRIPT', 'STYLE', 'svg', 'SVG', 'PATH', 'IMG', 'VIDEO', 'CANVAS', 'TEXTAREA', 'SELECT', 'INPUT', 'OPTION'].includes(e.tagName)) continue;
    const overY = e.scrollHeight - e.clientHeight, overX = e.scrollWidth - e.clientWidth;
    const hides = (v) => v === 'hidden' || v === 'clip';
    // Text truncated on purpose with an ellipsis is a design choice, not lost content.
    const ellipsis = c.textOverflow === 'ellipsis' || Number(c.webkitLineClamp) > 0 || c.getPropertyValue('-webkit-line-clamp') !== 'none' && c.getPropertyValue('-webkit-line-clamp') !== '';
    // Screen-reader-only text (1px box with clip) is hidden on purpose.
    const srOnly = e.clientWidth <= 1 && e.clientHeight <= 1 || c.clip === 'rect(0px, 0px, 0px, 0px)' || c.clipPath === 'inset(50%)';
    if (!ellipsis && !srOnly && ((hides(c.overflowY) && overY > 4) || (hides(c.overflowX) && overX > 4)) && meaningful(e)) {
      // Only report when a child with content actually lies outside the box.
      const box = e.getBoundingClientRect();
      const lost = [...e.querySelectorAll('a[href],button,input,select,textarea,p,li,h1,h2,h3,h4,span,strong,td')]
        .filter(shown).filter((k) => {
          const r = k.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && (r.top >= box.bottom - 1 || r.bottom > box.bottom + 4 || r.left >= box.right - 1 || r.right > box.right + 4) && (k.innerText || k.value || '').trim();
        });
      if (lost.length) clipped.push({el: label(e), overY, overX, lost: lost.slice(0, 3).map((k) => label(k) + ' ' + (k.innerText || '').trim().slice(0, 40))});
    }
    const scrolls = (v) => v === 'auto' || v === 'scroll';
    if (e !== document.scrollingElement && e !== document.body && scrolls(c.overflowY) && overY > 4 && meaningful(e) && e.clientHeight < innerHeight * 0.9) {
      traps.push({el: label(e), visible: e.clientHeight, content: e.scrollHeight, overscroll: c.overscrollBehaviorY});
    }
  }
  const controls = [...document.querySelectorAll('a[href],button,input:not([type=hidden]),select,textarea,[role=button],summary')].filter(shown);
  const docW = document.documentElement.scrollWidth, docH = document.documentElement.scrollHeight;
  for (const e of controls) {
    const r = e.getBoundingClientRect(), absL = r.left + scrollX, absT = r.top + scrollY;
    if (r.width < 1 || r.height < 1) continue;
    if (absL + r.width <= 0 || absT + r.height <= 0 || absL >= docW || absT >= docH) {
      if (!e.classList.contains('sr-only') && !e.classList.contains('skip-link')) offscreen.push({el: label(e), left: Math.round(absL), top: Math.round(absT)});
    }
  }
  const sample = controls.filter((e) => !e.closest('.sr-only,.skip-link')).slice(0, 400);
  const frame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const blocker = (e) => {
    const r = e.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    const x = Math.min(innerWidth - 1, Math.max(0, r.left + r.width / 2)), y = Math.min(innerHeight - 1, Math.max(0, r.top + r.height / 2));
    const top = document.elementFromPoint(x, y);
    // A label or decoration inside the same control group still lets the click through.
    if (!top || top === e || e.contains(top) || top.contains(e) || (e.labels && [...e.labels].some((l) => l.contains(top)))) return null;
    return getComputedStyle(top).pointerEvents === 'none' ? null : top;
  };
  for (const e of sample) {
    e.scrollIntoView({block: 'center', inline: 'center'});
    await frame();
    if (!blocker(e)) continue;
    // Confirm after layout settles so a late data render is not reported as an overlap.
    await new Promise((resolve) => setTimeout(resolve, 150));
    e.scrollIntoView({block: 'center', inline: 'center'});
    await frame();
    const top = blocker(e);
    if (top) covered.push({el: label(e), by: label(top), text: (e.innerText || e.getAttribute('aria-label') || '').trim().slice(0, 40)});
  }
  scrollTo(0, 0);
  return {clipped, traps, covered, offscreen};
}
