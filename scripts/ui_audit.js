// In-page UI quality audit (AD Coin public screens, PM criteria 2026-11-11).
// Returns counts and the first offenders for: horizontal scroll, overlaps, small targets (<44px),
// unlabeled fields, WCAG AA contrast, spacing values outside the shared design files, alignment
// (rows and columns within 1px) and broken images. Only visible elements are measured.
(() => {
  // Content of a closed <details> is not drawn, but Chrome still reports layout boxes for it (11-11:
  // the test and register screens counted ~150 "overlaps" from closed panels). Only the summary shows.
  const inClosedDetails = el => {
    for (let d = el.closest('details:not([open])'); d; d = d.parentElement && d.parentElement.closest('details:not([open])')) {
      const summary = el.closest('summary');
      if (el !== d && !(summary && summary.parentElement === d)) return true;
    }
    return false;
  };
  const visible = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility !== 'hidden' && +s.opacity > 0 && r.width > 1 && r.height > 1
      && !el.closest('[hidden], [aria-hidden="true"], .sr-only') && !inClosedDetails(el);
  };
  const name = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const all = [...document.querySelectorAll('body *')].filter(visible);
  const out = {};

  // 1. horizontal scroll
  out.horizontal_scroll = document.documentElement.scrollWidth > window.innerWidth + 1 ? 1 : 0;

  // 2. spacing tokens: every px value used for margin, padding and gap in the shared stylesheets
  const allowed = new Set([0]);
  for (const sheet of document.styleSheets) {
    let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
    const walk = list => { for (const rule of list) {
      if (rule.cssRules) walk(rule.cssRules);
      if (!rule.style) continue;
      for (const prop of rule.style) if (/^(margin|padding|gap|row-gap|column-gap)/.test(prop)) {
        for (const m of String(rule.style.getPropertyValue(prop)).matchAll(/(-?[0-9.]+)px/g)) allowed.add(Math.abs(+m[1]));
      }
    } };
    walk(rules);
  }
  const spacing = [];
  for (const el of all) {
    const s = getComputedStyle(el);
    for (const prop of ['margin-top', 'margin-bottom', 'margin-left', 'margin-right', 'padding-top', 'padding-bottom',
                        'padding-left', 'padding-right', 'row-gap', 'column-gap']) {
      const v = s.getPropertyValue(prop);
      if (!v.endsWith('px')) continue;
      const n = Math.round(Math.abs(parseFloat(v)) * 100) / 100;
      const autoMargin = /margin-(left|right)/.test(prop) && n > 48;   // auto margins resolve to leftover space
      if (n && !allowed.has(n) && !autoMargin && !(prop.startsWith('margin-') && s.display === 'inline'))
        spacing.push(name(el) + ' ' + prop + ' ' + v);
    }
  }
  out.spacing_off_token = spacing.length; out.spacing_examples = spacing.slice(0, 8);

  // 3. targets and labels
  const interactive = all.filter(el => el.matches('button, a[href], input:not([type=hidden]), select, textarea, summary'));
  const inText = el => el.matches('a') && el.closest('p, li, dd, td, label, .caption') && !el.matches('.btn');  // label: a link inside a consent sentence (11-11)
  const target = el => (el.matches('input[type=checkbox], input[type=radio]') && el.closest('label')) || el;  // the label is the hit area
  const small = interactive.filter(el => !inText(el)).filter(el => { const r = target(el).getBoundingClientRect(); return r.width < 44 - 0.5 || r.height < 44 - 0.5; });
  // Shared header and form parts sized by the design system files (the same on the main frontend).
  const shared = el => el.matches('a.brand, button.theme-toggle') || !!(el.matches('input[type=checkbox], input[type=radio]') && el.closest('label.check'));
  out.design_system_small = small.filter(shared).length;
  out.design_system_examples = [...new Set(small.filter(shared).map(name))];
  const own = small.filter(el => !shared(el));
  out.small_targets = own.length; out.small_examples = own.slice(0, 8).map(el => { const r = target(el).getBoundingClientRect(); return name(el) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height); });
  out.small_targets_all = small.length; out.small_all_examples = small.slice(0, 8).map(el => { const r = el.getBoundingClientRect(); return name(el) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height); });
  const fields = all.filter(el => el.matches('input:not([type=hidden]), select, textarea'));
  const unlabeled = fields.filter(el => !(el.labels && el.labels.length) && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby'));
  out.unlabeled_fields = unlabeled.length; out.unlabeled_examples = unlabeled.slice(0, 5).map(name);

  // 4. contrast (WCAG AA): text nodes against the first opaque background behind them
  const rgba = c => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const background = el => { let layers = []; for (let n = el; n; n = n.parentElement) { const c = rgba(getComputedStyle(n).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; } }
    let base = [255, 255, 255]; const root = rgba(getComputedStyle(document.body).backgroundColor); if (root && root[3] >= 1) base = root.slice(0, 3);
    for (const c of layers.reverse()) base = base.map((v, i) => v * (1 - c[3]) + c[i] * c[3]); return base; };
  const low = []; let unmeasured = 0;
  const gradient = el => { for (let n = el; n; n = n.parentElement) { const s = getComputedStyle(n);
      if (s.backgroundImage !== 'none') return true; const c = rgba(s.backgroundColor); if (c && c[3] >= 1) return false; } return false; };
  for (const el of all) {
    if (![...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) continue;
    if (el.matches(':disabled') || el.closest(':disabled')) continue;   // WCAG 1.4.3 exempts inactive controls
    const s = getComputedStyle(el), fg = rgba(s.color); if (!fg) continue;
    if (gradient(el)) { unmeasured++; continue; }   // text on a gradient is measured by the screenshot review
    const bg = background(el), f = fg[3] < 1 ? fg.slice(0, 3).map((v, i) => v * fg[3] + bg[i] * (1 - fg[3])) : fg.slice(0, 3);
    const L1 = lum(f), L2 = lum(bg), ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    const size = parseFloat(s.fontSize), large = size >= 24 || (size >= 18.66 && +s.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5) - 0.01) low.push(name(el) + ' ' + ratio.toFixed(2));
  }
  out.contrast_unmeasured = unmeasured; out.contrast_failures = low.length; out.contrast_examples = low.slice(0, 8);

  // 5. overlaps between distinct visible boxes that do not contain each other
  const boxes = all.filter(el => el.matches('button, a, input, select, textarea, label, h1, h2, h3, p, img, .badge, .card'));
  const overlaps = [], overlays = [];
  const layer = el => { for (let e = el; e && e !== document.body; e = e.parentElement) { const p = getComputedStyle(e).position; if (p === 'fixed' || p === 'sticky') return true; } return false; };
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j]; if (a.contains(b) || b.contains(a)) continue;
    // An inline element that wraps has one box per line; its bounding box would span both lines (11-11).
    const boxesOf = el => getComputedStyle(el).display === 'inline' ? [...el.getClientRects()] : [el.getBoundingClientRect()];
    const hit = boxesOf(a).some(r => boxesOf(b).some(q => Math.min(r.right, q.right) - Math.max(r.left, q.left) > 1
      && Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) > 1));
    if (hit) (layer(a) || layer(b) ? overlays : overlaps).push(name(a) + ' / ' + name(b));
  }
  out.overlaps = overlaps.length; out.overlap_examples = overlaps.slice(0, 8);
  // A fixed or sticky layer (cookie strip, sticky panel) floats over scrolling content by design; it is
  // counted apart so in-flow layout overlaps stay visible (11-11).
  out.overlay_overlaps = overlays.length; out.overlay_examples = overlays.slice(0, 8);

  // 6. alignment: flex/grid rows share a top, bottom or centre; stacked blocks share a left edge
  const misaligned = [];
  for (const parent of all) {
    const s = getComputedStyle(parent), kids = [...parent.children].filter(visible);
    if (kids.length < 2) continue;
    // Table rows lay cells side by side and the table aligns its own columns; the stacked-block left-edge
    // check would compare th and td in one row (11-11: 106 false reports on the status table).
    if (/^table/.test(s.display)) continue;
    const rects = kids.map(k => k.getBoundingClientRect());
    if (/flex|grid/.test(s.display)) {
      // Rows aligned on the text baseline are aligned by design; an item that spans several grid rows
      // (a side column of actions) is not in one row with its neighbour (11-11).
      if (/baseline/.test(s.alignItems)) continue;
      const spans = k => { const c = getComputedStyle(k), a = parseInt(c.gridRowStart), b = parseInt(c.gridRowEnd);
        return /span\s*([2-9]|\d\d)/.test(c.gridRowEnd) || (b - a > 1); };
      for (let i = 1; i < kids.length; i++) {
        if (/grid/.test(s.display) && (spans(kids[i - 1]) || spans(kids[i]))) continue;
        const a = rects[i - 1], b = rects[i];
        const sameRow = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > Math.min(a.height, b.height) / 2;
        if (sameRow && Math.abs(a.top - b.top) > 1 && Math.abs(a.bottom - b.bottom) > 1 && Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) > 1)
          misaligned.push('row ' + name(kids[i - 1]) + ' | ' + name(kids[i]));
      }
    } else {
      const blocks = kids.filter(k => /block|flex|grid|table/.test(getComputedStyle(k).display) && getComputedStyle(k).position === 'static' && getComputedStyle(k).float === 'none');
      const lefts = blocks.map(k => k.getBoundingClientRect().left + parseFloat(getComputedStyle(k).marginLeft) * 0);
      // A centred or right-aligned stack shares its centre or right edge instead (11-11: centred workflow steps).
      const br = blocks.map(k => k.getBoundingClientRect()), centre = r => (r.left + r.right) / 2;
      for (let i = 1; i < blocks.length; i++) if (Math.abs(lefts[i] - lefts[0]) > 1 && Math.abs(centre(br[i]) - centre(br[0])) > 1
        && Math.abs(br[i].right - br[0].right) > 1) misaligned.push('column ' + name(blocks[0]) + ' | ' + name(blocks[i]));
    }
  }
  out.misaligned = misaligned.length; out.misaligned_examples = misaligned.slice(0, 8);

  // 7. broken images
  out.broken_images = [...document.images].filter(i => visible(i) && i.complete && i.naturalWidth === 0).length;
  return out;
})()
