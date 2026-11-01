"""Owned document retrieval over explicitly approved public source snapshots.

No network fetch, model answer or self-awarded quality evidence is performed.
The same docs.search.v1 contract and independent evaluation apply as for any
catalog agent. Approval of a corpus is a trusted deployment input, not user data.
"""
from dataclasses import dataclass
from collections import Counter
from datetime import datetime, timezone
import hashlib
import math
import re

from .capability_contracts import validate
from .concierge.recommendation_security import usable_endpoint
from .first_party_guides import PlatformGuideAgent, router_for as guides_router


@dataclass(frozen=True)
class ApprovedDocument:
    title: str
    url: str
    version: str
    text: str

    def __post_init__(self):
        from urllib.parse import urlsplit
        if (any(type(v) is not str for v in (self.title,self.url,self.version,self.text))
                or not 1 <= len(self.title) <= 200 or not 1 <= len(self.version) <= 200
                or not 1 <= len(self.text.encode('utf-8')) <= 100000 or len(self.url) > 2000
                or urlsplit(self.url).scheme != 'https' or not usable_endpoint(self.url)
                or re.search(r'<[^>]*>|\bBearer\s|\b(?:api[_-]?key|token|password)\s*[:=]', self.text, re.I)
                or any(ord(c)<32 and c not in '\n\t' for c in self.text)):
            raise ValueError('Provide a bounded approved public source snapshot.')


class ApprovedCorpusAgent(PlatformGuideAgent):
    tool_name = 'search_approved_documents'
    server_name = 'Agent Concierge Document Search'

    def __init__(self, documents):
        if (type(documents) is not tuple or not 1 <= len(documents) <= 500
                or any(type(doc) is not ApprovedDocument for doc in documents)
                or len({doc.url for doc in documents}) != len(documents)
                or sum(len(doc.text.encode('utf-8')) for doc in documents) > 5000000):
            raise ValueError('Choose one finite approved corpus.')
        self.documents = documents
        self.corpus_hash = hashlib.sha256(repr(documents).encode()).hexdigest()
        self.frequencies = [Counter(self._words(doc.title+' '+doc.text)) for doc in documents]
        self.document_frequency = Counter(term for counts in self.frequencies for term in counts)

    @staticmethod
    def _words(text):
        return re.findall(r'[a-z0-9]{2,}',text.lower())

    def search(self, arguments):
        validate('docs.search.v1',arguments)
        query = arguments['query']
        if (any(ord(c)<32 for c in query) or re.search(r'https?://|<[^>]*>|\bBearer\s|\b(?:api[_-]?key|token)\s*[:=]',query,re.I)):
            raise ValueError('Use public document search terms.')
        terms = set(self._words(query))
        if len(terms)>32:
            raise ValueError('Use at most thirty-two distinct search terms.')
        ranked=[]
        for doc,counts in zip(self.documents,self.frequencies):
            # Finite BM25-style term frequency weighting; no popularity boost or
            # first-party priority enters platform recommendation ranking.
            score=0.0
            for term in terms:
                frequency=counts[term]
                if frequency:
                    containing=self.document_frequency[term]
                    score += math.log(1+(len(self.documents)-containing+.5)/(containing+.5))*frequency/(frequency+1.2)
            if score:
                ranked.append((-score,doc.url,doc))
        ranked.sort(key=lambda item:item[:2])
        now=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        result={'items':[],'partial':False}
        for _,_,doc in ranked[:arguments['limit']]:
            matches=[match.start() for term in terms for match in re.finditer(r'\b'+re.escape(term)+r'\b',doc.text,re.I)]
            start=max(0,min(matches,default=0)-120)
            excerpt=doc.text[start:start+1200]
            result['items'].append({'title':doc.title,'url':doc.url,'excerpt':excerpt,'version':doc.version,'retrieved_at':now})
        validate('docs.search.v1',arguments,result)
        return result


def router_for(documents=(), *, enabled=False):
    if type(enabled) is not bool:
        raise ValueError('Choose an explicit owned corpus setting.')
    if not enabled:
        return guides_router()
    router=guides_router(enabled=True,agent=ApprovedCorpusAgent(documents),path_prefix='/api/document-search')
    # The corpus's cited URLs are its approved source locations. Do not expose
    # unrelated public-guide documents under a document-search source URL.
    router.routes[:]=[route for route in router.routes if 'POST' in route.methods]
    return router
