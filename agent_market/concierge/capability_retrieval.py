"""Immutable tool facts, rebuilt from each current resource's public metadata.

This cache contains no candidates, verification decisions, workspace data or
query. All admission and execution authority remains in the existing caller.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import re
import threading


@dataclass(frozen=True)
class ToolFacts:
    name: str
    text: str
    input_fields: tuple[str, ...]


@dataclass(frozen=True)
class CapabilityFacts:
    revision: str
    text: str
    tools: tuple[ToolFacts, ...]


class ProjectionCache:
    def __init__(self, maximum=128, maximum_bytes=2*1024*1024):
        self.maximum = maximum
        self.maximum_bytes = maximum_bytes
        self.bytes = 0
        self.sizes = {}
        self.lock = threading.Lock()
        self.values = OrderedDict()

    def project(self, resource):
        # Bound before parsing; oversized/malformed declarations supply no facts.
        fields = {}
        for key, maximum in [('name', 160), ('description', 2000), ('usage_full_tools', 65536),
                             ('usage_tools', 65536), ('usage_guide', 65536)]:
            value = resource.get(key)
            if not isinstance(value, str):
                try: value = json.dumps(value, ensure_ascii=True, allow_nan=False)
                except (ValueError, TypeError, RecursionError): value = ''
            fields[key] = value if len(value) <= maximum else ''
        revision = hashlib.sha256(json.dumps(fields, sort_keys=True).encode('utf-8', 'replace')).hexdigest()
        with self.lock:
            found = self.values.pop(revision, None)
            if found is not None:
                self.values[revision] = found
                return found, True
        tools = []
        for key in ('usage_full_tools', 'usage_tools', 'usage_guide'):
            try: values = json.loads(fields[key] or 'null')
            except (ValueError, TypeError, RecursionError): continue
            if isinstance(values, dict): values = values.get('tools', [])
            if not isinstance(values, list): continue
            for value in values[:32]:
                if not isinstance(value, dict): continue
                name = value.get('name') or value.get('id')
                if not isinstance(name, str) or not name or len(name) > 120: continue
                description = value.get('description')
                description = description[:700] if isinstance(description, str) else ''
                schema = value.get('inputSchema') or {}
                properties = schema.get('properties') if isinstance(schema, dict) else None
                inputs = tuple(sorted(k for k in properties if isinstance(k, str) and len(k) <= 80)[:32]) if isinstance(properties, dict) else ()
                item = ToolFacts(name, (name.replace('_', ' ') + ' ' + description).casefold(), inputs)
                if item not in tools: tools.append(item)
                if len(tools) >= 32: break
            if tools: break
        result = CapabilityFacts(revision, (fields['name'] + ' ' + fields['description']).casefold(), tuple(tools))
        size = len(result.text.encode('utf-8','replace')) + sum(len((t.name+t.text+''.join(t.input_fields)).encode('utf-8','replace')) for t in result.tools)
        if size > self.maximum_bytes:
            return result, False
        with self.lock:
            self.bytes -= self.sizes.get(revision,0)
            self.values[revision] = result
            self.sizes[revision] = size
            self.bytes += size
            while len(self.values) > self.maximum or self.bytes > self.maximum_bytes:
                old,_ = self.values.popitem(last=False)
                self.bytes -= self.sizes.pop(old)
        return result, False


def word_present(word, text):
    return bool(re.search(r'(?<![a-z0-9])' + re.escape(word) + r'(?![a-z0-9])', text))
