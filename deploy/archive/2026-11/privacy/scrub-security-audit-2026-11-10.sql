-- Reduce stored addresses and user agents in security and admin audit records (2026-11-10, user approved).
-- Same rules as agent_market/privacy.py: IPv4 -> /24, IPv6 -> /48, anything else -> 'unknown' (security_events.ip is NOT NULL)
-- or NULL (admin_audit_logs.ip), User-Agent -> client family. Run in one transaction (psql -1).
UPDATE security_events SET ip = regexp_replace(ip, '^(\d+)\.(\d+)\.(\d+)\.\d+$', '\1.\2.\3.0/24')
 WHERE ip ~ '^\d+\.\d+\.\d+\.\d+$';
UPDATE security_events SET ip = network(set_masklen(ip::inet, 48))::text
 WHERE ip ~ ':' AND ip ~ '^[0-9A-Fa-f:.]+$' AND ip !~ '/';
UPDATE security_events SET ip = 'unknown' WHERE ip !~ '/(24|48)$';
UPDATE admin_audit_logs SET ip = regexp_replace(ip, '^(\d+)\.(\d+)\.(\d+)\.\d+$', '\1.\2.\3.0/24')
 WHERE ip ~ '^\d+\.\d+\.\d+\.\d+$';
UPDATE admin_audit_logs SET ip = NULL WHERE ip IS NOT NULL AND ip !~ '/(24|48)$';
UPDATE security_events SET user_agent = CASE
   WHEN user_agent IS NULL OR user_agent = '' THEN NULL
   WHEN user_agent ~* 'googlebot' THEN 'Googlebot'
   WHEN user_agent ~* 'bingbot' THEN 'bingbot'
   WHEN user_agent ~* 'claudebot' THEN 'ClaudeBot'
   WHEN user_agent ~* 'gptbot' THEN 'GPTBot'
   WHEN user_agent ~* 'perplexitybot' THEN 'PerplexityBot'
   WHEN user_agent ~* '(site owner|ops-check|agentconcierge|qa-agent)' THEN 'internal'
   WHEN user_agent ~* '(headless|puppeteer|playwright)' THEN 'headless'
   WHEN user_agent ~* '^mozilla/5\.0 .*edg/' THEN 'Edge'
   WHEN user_agent ~* '^mozilla/5\.0 .*firefox/' THEN 'Firefox'
   WHEN user_agent ~* '^mozilla/5\.0 .*chrome/' THEN 'Chrome'
   WHEN user_agent ~* '^mozilla/5\.0 .*safari/' THEN 'Safari'
   WHEN user_agent ~* '^(curl|wget|python|httpx|aiohttp|node|axios|undici|go-http|okhttp|java|deno|bun|ruby|php|libwww|postman|insomnia)'
     THEN lower(split_part(substring(user_agent from '^[A-Za-z][A-Za-z0-9_.-]{0,30}'), '/', 1))
   WHEN user_agent IN ('Chrome','Edge','Firefox','Safari','browser','headless','internal','verifier','other') THEN user_agent
   ELSE 'other' END;
