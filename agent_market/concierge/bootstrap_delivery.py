"""Bound initial HTML delivery without publishing stale connection assertions."""
import json
import gzip
import threading
import re
from functools import lru_cache

# At most two catalog snapshots can be built for HTML across this process.
# Requests share a front-local in-flight job; no unbounded executor queue exists.
_slots = threading.BoundedSemaphore(2)
EMPTY = {key: None for key in ('overview', 'explore', 'insights', 'workflow_default',
                              'workflow_templates', 'testbench_presets', 'testbench_examples')}
MAX_INLINE_GZIP = 700


@lru_cache(maxsize=1)
def compact_shell(source):
    """Compact only the static shell; preserve license and source edit anchors."""
    result = re.sub(r'<!--[\s\S]*?-->',
                    lambda match: match[0] if 'License' in match[0] else '', source)
    return re.sub(r'<style(?:\s[^>]*)?>[\s\S]*?</style>',
                  lambda match: re.sub(r'/\*[\s\S]*?\*/', '', match[0]), result)


class HtmlBootstrap:
    def __init__(self, front):
        self.front = front
        self.lock = threading.Lock()
        self.job = None

    def read(self, seconds=.15):
        """Use a fresh projection or hydrate through the existing page APIs."""
        with self.lock:
            job = self.job
            if job is None or job['done'].is_set():
                if not _slots.acquire(blocking=False):
                    return json.dumps(EMPTY, separators=(',', ':'))
                job = {'done': threading.Event(), 'value': None}
                self.job = job
                def build():
                    try:
                        # Never reuse a completed job: current failure, expiry and
                        # authority checks still run on every fresh page request.
                        job['value'] = self.front.bootstrap_snapshot_json()
                    except Exception:
                        # No diagnostics or private data enter the HTML fallback.
                        job['value'] = None
                    finally:
                        job['done'].set()
                        _slots.release()
                try:
                    threading.Thread(target=build, name='html-catalog-snapshot', daemon=True).start()
                except Exception:
                    self.job = None
                    _slots.release()
                    return json.dumps(EMPTY, separators=(',', ':'))
        if job['done'].wait(max(0., min(float(seconds), .25))) and job['value'] is not None:
            # The home shell needs only its overview and first discovery page.
            # Other menus load through their existing bounded APIs on entry;
            # don't duplicate all template and guide payloads in every page.
            value = json.loads(job['value'])
            result = dict(EMPTY, overview=value.get('overview'), explore=value.get('explore'))
            def encode():
                return json.dumps(result, separators=(',', ':')).replace('<', '\\u003c')
            # Bound the inline transfer too. Large catalogs hydrate summaries
            # through existing APIs rather than inflate every initial document.
            if len(gzip.compress(encode().encode('utf-8'))) > MAX_INLINE_GZIP:
                result['overview'] = None
                explore = result.get('explore')
                if isinstance(explore, dict) and isinstance(explore.get('items'), list):
                    for count in (3, 1):
                        keys = ('id', 'agent_ref', 'name', 'description', 'kind', 'url', 'category',
                                'eval_grade', 'health_status', 'connection_readiness', 'verified_working')
                        result['explore'] = dict(explore, items=[{k:card[k] for k in keys if k in card}
                            for card in explore['items'][:count] if isinstance(card, dict)])
                        if len(gzip.compress(encode().encode('utf-8'))) <= MAX_INLINE_GZIP:
                            break
            encoded = encode()
            if len(encoded.encode('utf-8')) <= 32768 and len(gzip.compress(encoded.encode('utf-8'))) <= MAX_INLINE_GZIP:
                return encoded
        return json.dumps(EMPTY, separators=(',', ':'))


def nonce_scripts(value,nonce):
    """Nonce actual HTML script tags without changing script-source templates."""
    from html.parser import HTMLParser
    offsets=[];position=0
    for line in value.splitlines(keepends=True):offsets.append(position);position+=len(line)
    edits=[]
    class Scripts(HTMLParser):
        def handle_starttag(self,tag,attrs):
            if tag!='script':return
            row,column=self.getpos();start=offsets[row-1]+column;raw=self.get_starttag_text()
            clean=re.sub(r'\snonce=(?:"[^"]*"|\'[^\']*\'|[^\s>]+)','',raw,flags=re.I)
            edits.append((start,start+len(raw),'<script nonce="'+nonce+'"'+clean[7:]))
    Scripts(convert_charrefs=False).feed(value)
    for start,end,replacement in reversed(edits):value=value[:start]+replacement+value[end:]
    return value
