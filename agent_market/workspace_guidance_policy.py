"""Ground common workspace policy questions in reviewed public documentation."""
import re

from .workflow_support import DOCS

_DOCS={doc['id']:doc for doc in DOCS}
_MUTATION=re.compile(r'\b(?:rename|name it|call it|set (?:the )?(?:name|description)|change (?:the )?name|update (?:the )?description)\b',re.I)


def reviewed_guidance(objective):
    """Return quoted public policy for clear help intents, without model claims."""
    text=' '.join(objective.lower().split())
    if _MUTATION.search(text):return None
    documents=None
    if re.search(r'\b(?:uncertain|unknown|ambiguous)\b',text) and re.search(r'\b(?:run|execution|submission|submit|outcome)\b',text):
        documents=['typed-workflow-review','private-manual-run']
    elif re.search(r'\b(?:destination|task updates?|browser (?:permission|notifications?)|webhook|inbox)\b',text):
        documents=['verified-task-updates']
    elif re.search(r'\b(?:review|apply|proposed)\b',text) and re.search(r'\b(?:change|patch)\b',text):
        documents=['safe-change-review','typed-workflow-review']
    elif re.search(r'\b(?:save|saving|saved|snapshot)\b',text) and re.search(r'\b(?:workflow|snapshot|execute|execution)\b',text):
        documents=['private-snapshots','typed-workflow-review']
    elif re.search(r'\b(?:explain|how|steps)\b',text) and re.search(r'\bworkflow\b',text) and re.search(r'\b(?:news|documentation|research|search)\b',text):
        documents=['public-search-workflow','typed-workflow-review']
    if documents is None:return None
    return {'answer':' '.join(_DOCS[key]['text'] for key in documents),'documents':documents,'changes':{}}


def selected_documents(objective, limit=4):
    words=set(re.findall(r'[a-z]{3,}',objective.lower()))-{'the','and','for','with','what','how','explain','please','public','private'}
    def score(doc):
        title=set(re.findall(r'[a-z]{3,}',doc['title'].lower()))
        content=set(re.findall(r'[a-z]{3,}',doc['text'].lower()))
        return 3*len(words & title)+len(words & content)
    eligible=[(i,d) for i,d in enumerate(DOCS) if d['id']!='app-deployment-lifecycle' or words & {'deployment','deploy','export','exported','origin','expiry','authorization','app'}]
    scored=sorted(eligible,key=lambda pair:(-score(pair[1]),pair[0]))
    selected=[doc for _,doc in scored[:limit]]
    # Every optional draft proposal requires the same explicit review policy.
    if not any(doc['id']=='safe-change-review' for doc in selected):
        selected[-1]=_DOCS['safe-change-review']
    return [dict(doc) for doc in selected]


def response_schema(documents):
    return {'type':'object','properties':{
        'answer':{'type':'string','minLength':1,'maxLength':1200},
        'documents':{'type':'array','items':{'type':'string','enum':[d['id'] for d in documents]},'minItems':1,'maxItems':len(documents),'uniqueItems':True},
        'changes':{'type':'object','properties':{'name':{'type':'string','minLength':1,'maxLength':120},'description':{'type':'string','maxLength':1000}},'additionalProperties':False}},
        'required':['answer','documents','changes'],'additionalProperties':False}
