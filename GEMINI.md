# Project Rules & Guidelines: Agent Concierge (A2A Discovery)

## 1. Strict 100% English Only for Frontend
- **Frontend Source & Assets**: All frontend source files (`extracted_html.txt`, `agent_market/concierge/front.py`, HTML templates, client-side JavaScript, CSS) must be strictly in **English only**.
- **Zero Korean in Source Code & Comments**: All code comments, docstrings, function headers, variable names, and inline annotations must be written 100% in English. No Korean characters (`\uac00-\ud7af`, `\u1100-\u11ff`, `\u3130-\u318f`) are permitted under any circumstances.
- **UI Content & Messages**: All user-facing UI labels, placeholders, tooltips, dialogs, alert popups, notifications, and metadata must strictly be in English.

## 2. Zero System, Developer, or Sensitive Information (Zero-Leakage Policy)
- **No System/Infra Details**: Do not expose internal IP addresses (e.g., `127.0.0.1`, `localhost`, `0.0.0.0`), internal ports (e.g., `:8080`, `:8200`, `:8400`), database technology names (e.g., `sqlite`, `postgres`), or internal local server paths in frontend source or public endpoints.
- **No Developer/Personal Data**: Never include developer personal identifiers, non-public contact details, internal debug logs, or development stack traces in client code.
- **Production Domain Standard**: All public links and machine invocation examples must strictly use the official production URL (`https://agentconcierge.biz`).

## 3. Automated Compliance Enforcement
- Before completing any frontend modifications, always execute an automated regex verification across all modified files:
  ```python
  import re
  hangul = re.findall(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", content)
  assert len(hangul) == 0, f"Violation: Found Korean characters: {set(hangul)}"
  ```

## 4. Modern Style Design & Strict Lucide Icons Only
- **Modern Design System**: The frontend must consistently adhere to a sleek, modern UI styling (dark/glassmorphism aesthetics, refined typography, smooth transitions, subtle border glows, clean badges, and responsive layouts).
- **Strict Lucide Icons Standard**: All UI icons across the entire frontend (navigation tabs, buttons, section banners, card headers, status indicators, quick chips, modal dialogs, and action bars) must strictly use official **Lucide SVG icons** (`viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"`).
- **Zero Raw Emojis or Unicode Symbols as UI Icons**: Raw emojis (e.g., ⚡, ⏱️, 🕒, ✦, ★, 📊, 🔍, ⚙️, 🚀, 🤖, 🌐, 🔒) or crude text characters (`✓`, `✕`, `●`) must not be used as standalone UI icons. Replace them with standard, clean, scalable inline Lucide SVG icons (e.g., `<svg class="lucide lucide-check" ...>`).
