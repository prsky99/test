"""Conservative, deterministic constraints for supported public search goals.

These rules constrain advisory generation; they never authorize execution.
Ambiguous mixed-stage goals require clarification instead of invented stages.
"""
import re
from datetime import datetime, timezone

from .workspace_access import WorkspaceInvalid

DOCS = 'docs.search.v1'
NEWS = 'news.search.v1'
_KIND = re.compile(r'\b(?:documentation|documents?|docs|papers?|research|references?)\b|\ubb38\uc11c|\ub17c\ubb38|\b(?:news|headlines|newsletters?)\b|\ub274\uc2a4', re.I)
_NEWS = re.compile(r'\b(?:news|headlines|newsletters?)\b|\ub274\uc2a4', re.I)
_WORDS = {'two':2,'three':3,'four':4,'five':5,'six':6,'seven':7,'eight':8,'nine':9,'ten':10,'one':1,'zero':0,'eleven':11,'twelve':12,'thirteen':13,'fourteen':14,'fifteen':15,'sixteen':16,'seventeen':17,'eighteen':18,'nineteen':19,'twenty':20}
_COUNT = re.compile(r'\b(?:exactly\s+)?(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty)\s+(?:(?:read-only|connected|sequential|linked|independent|ordered)\s+){0,2}(?:steps?|tasks?)\b', re.I)


class GoalQueryMismatch(WorkspaceInvalid):
    """The model changed a named topic; no agent or save was dispatched."""


class GoalNeedsDetails(WorkspaceInvalid):
    """A fixed public explanation, never a provider or runtime diagnostic."""
    def __init__(self, requirement):
        super().__init__()
        self.requirement=requirement


def normalized_goal(objective):
    text=objective
    for alias,name in {'\ud30c\uc774\uc36c':'Python','\uc790\ubc14\uc2a4\ud06c\ub9bd\ud2b8':'JavaScript',
            '\ub274\uc2a4':'news','\ubb38\uc11c':'documentation','\ub17c\ubb38':'papers','\ub2e8\uacc4':'steps',
            '\uc694\uc57d':'summary','\ubc88\uc5ed':'translation'}.items():
        text=text.replace(alias,' '+name+' ')
    text=re.sub(r'\s+',' ',text)
    return text.strip()


def positive_text(objective):
    text=normalized_goal(objective)
    text=re.sub(r'\b(?:news|documentation)\b\s*[\uac00-\ud7a3]*\s*\uc81c\uc678\ud558\uace0', ' ',text,flags=re.I)
    # Keep later step-count and time constraints outside a negative phrase.
    from .concierge.query_intent import interpret
    return interpret(text).positive


def explicit_steps(objective):
    values={_WORDS.get(m[1].lower(),int(m[1]) if m[1].isdigit() else 0) for m in _COUNT.finditer(positive_text(objective))}
    if len(values)>1 or values and not 2<=next(iter(values))<=10:
        raise GoalNeedsDetails('Choose one consistent count between two and ten steps.')
    return next(iter(values)) if values else None


def _mentions(objective):
    text=positive_text(objective)
    text=re.sub(r'\ucc3e\uc740\s*\ub2e4\uc74c|\uadf8\ub2e4\uc74c|\uac80\uc0c9(?:\ud55c)?\s*\ud6c4',' then ',text)
    if re.search(r'\bafter\b(?!\s+that)',text,re.I):
        raise GoalNeedsDetails('Write the searches in execution order, separated by then.')
    stages=[]
    # "news about X and research on Y" names two tasks; split before a task word as well as at then.
    # "...and also find related papers" names a second task as plainly as "...and papers on Y".
    for clause in re.split(r'\b(?:then|followed by|next|after that)\b|\band\b(?=\s+(?:also\s+)?(?:please\s+)?(?:(?:find|search(?:\s+for)?|get|look\s+up)\s+)?'
                           r'(?:(?:the|some)\s+)?(?:(?:latest|recent|related|relevant|supporting)\s+)*(?:news|research|papers?|documentation|docs)\b)',text,flags=re.I):
        task=re.split(r'\b(?:about|on|regarding|concerning)\b',clause,maxsplit=1,flags=re.I)[0]
        matches=list(_KIND.finditer(task))
        # Research can describe a news task without requesting a document task.
        if any(_NEWS.fullmatch(m[0]) for m in matches):
            matches=[m for m in matches if m[0].lower()!='research']
        for match in matches:
            kind=NEWS if _NEWS.fullmatch(match[0]) else DOCS
            if not stages or stages[-1]!=kind:stages.append(kind)
    return stages


def requested_steps(context):
    from .workspace_goal_coverage import topics
    listed=topics(context['objective'])
    explicit=explicit_steps(context['objective'])
    if explicit is not None:
        if listed and len(listed)!=explicit:
            raise GoalNeedsDetails('Use the same number of steps and listed subjects.')
        return explicit
    stages=_mentions(context['objective'])
    return len(listed) or (len(stages) if len(stages)>1 else 2)


def contract_sequence(objective,count):
    text=positive_text(objective);stages=_mentions(objective)
    if not stages:return None
    if len(stages)==1:return stages*count
    if len(stages)!=count:raise GoalNeedsDetails('Specify a supported search type for every requested step.')
    # Korean joins two searches with geurigo, chatgo or hago ("find the news and also the related papers").
    if not re.search(r'\b(?:then|followed by|next|after that|and)\b|\ub2e4\uc74c|\uc774\uc5b4|\ud6c4|\uadf8\ub9ac\uace0|\ucc3e\uace0|\ud558\uace0',text,re.I):
        raise GoalNeedsDetails('State whether the different searches are independent or connected.')
    return stages


def independent(context):
    from .workspace_goal_coverage import topics
    qualified = any(re.search(r'\bindependent\b',match[0],re.I) for match in _COUNT.finditer(positive_text(context['objective'])))
    return bool(topics(context['objective']) or qualified or re.search(r'\b(?:independently|separately|in parallel)\b|\uac01\uac01',context['objective'],re.I))


def search_settings(objective):
    text=positive_text(objective)
    limits={int(m[1]) for m in re.finditer(r'\btop\s+(\d+)\b',text,re.I)}
    limits.update(int(m[1]) for m in re.finditer(r'\b(\d+)\s+results?\b',text,re.I))
    if len(limits)>1 or limits and not 1<=next(iter(limits))<=5:
        raise GoalNeedsDetails('Choose one consistent limit between one and five results per search step.')
    periods={int(m[1])*(24 if m[2].lower().startswith('day') else 1) for m in re.finditer(r'\b(?:last|past)\s+(\d+)\s+(days?|hours?)\b',text,re.I)}
    if len(periods)>1 or periods and not 1<=next(iter(periods))<=168:
        raise GoalNeedsDetails('Choose one news window between one and 168 hours (seven days).')
    return (next(iter(limits)) if limits else 1,next(iter(periods)) if periods else 24)


def goal_sequence(context):
    return contract_sequence(context['objective'],requested_steps(context))


def scoped_context(context):
    search_settings(context['objective'])
    sequence=goal_sequence(context)
    if sequence is None:return context
    candidates=[item for item in context['candidates'] if item['contract_id'] in sequence]
    if not candidates or set(sequence)-{item['contract_id'] for item in candidates}:raise WorkspaceInvalid()
    return context | {'candidates':candidates}


def validate_goal(context, nodes):
    sequence=goal_sequence(context)
    count=explicit_steps(context['objective'])
    if count is not None and len(nodes)!=count:raise WorkspaceInvalid()
    if sequence is not None and (any(type(node) is not dict or 'contract_id' not in node for node in nodes)
            or [node['contract_id'] for node in nodes]!=sequence):raise WorkspaceInvalid()
    from .workspace_goal_coverage import topics, step_subjects
    listed=topics(context['objective'])
    if independent(context):
        if any(node.get('bindings') or node.get('after') for node in nodes):raise WorkspaceInvalid()
        if listed:
            if len(listed)!=len(nodes):raise WorkspaceInvalid()
            for subject,node in zip(listed,nodes):validate_query({'objective':subject},node.get('input',{}).get('query',''))
    limit,hours=search_settings(context['objective'])
    explicit_limit=re.search(r'\b(?:top\s+\d+|\d+\s+results?)\b',positive_text(context['objective']),re.I)
    if explicit_limit and any(node.get('input',{}).get('limit')!=limit for node in nodes):raise WorkspaceInvalid()
    if re.search(r'\b(?:last|past)\s+\d+\s+(?:days?|hours?)\b',positive_text(context['objective']),re.I):
        for node in nodes:
            if node.get('contract_id')!=NEWS:continue
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(node['input']['from_utc'].replace('Z','+00:00'))).total_seconds()/3600
            except (KeyError,ValueError,TypeError):raise WorkspaceInvalid() from None
            if abs(age-hours)>.1:raise WorkspaceInvalid()
    for index, node in enumerate(nodes):
        if type(node) is not dict or type(node.get('input')) is not dict:
            continue
        query=node['input'].get('query')
        if type(query) is str:
            # Every literal search must retain its subject, not only step one.
            # Reviewed bindings are checked separately; a future title is not a
            # fact available to the proposal validator.
            own = step_subjects(context['objective'], len(nodes))
            if listed and independent(context):
                try:validate_query({'objective':listed[index]},query)
                except GoalQueryMismatch:
                    if not (own and own[index]):raise
                    validate_query({'objective':own[index]},query)
            elif own and own[index]:
                # The model proposes the first subject for every step; the service then writes
                # each step's own subject, so either one is accepted at this point.
                try:validate_query({'objective':own[index]},query)
                except GoalQueryMismatch:validate_query(context,query)
            else:
                validate_query(context,query)
    from .workflow_goal_evaluation import title_dependency_preserved
    if not title_dependency_preserved(positive_text(context['objective']), nodes):
        raise GoalNeedsDetails('Connect the next search to the returned title using a reviewed input binding.')


def compile_agents(context):
    sequence=goal_sequence(context)
    if sequence is None:raise WorkspaceInvalid()
    result=[];used={}
    for contract in sequence:
        candidates=[item for item in context['candidates'] if item['contract_id']==contract]
        if not candidates:raise WorkspaceInvalid()
        # Preserve catalog ordering and use distinct approved agents when possible.
        index=used.get(contract,0)
        result.append(dict(candidates[index % len(candidates)]));used[contract]=index+1
    return result


def search_topic(objective):
    """Keep the first requested subject separate from graph instructions."""
    text=re.sub(r'\ucc3e\uc740\s*\ub2e4\uc74c|\uadf8\ub2e4\uc74c|\uac80\uc0c9(?:\ud55c)?\s*\ud6c4',' then ',positive_text(objective))
    text=re.split(r'(?<=[.!?])\s+|\b(?:then|followed by)\b',text,maxsplit=1,flags=re.I)[0]
    text=re.split(r'\b(?:using\s+)?(?:exactly\s+)?(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:(?:read-only|connected|sequential|linked|independent|ordered)\s+){0,2}(?:steps?|tasks?)\b',text,maxsplit=1,flags=re.I)[0]
    text=re.sub(r'^(?:please\s+)?(?:find|search(?:\s+for)?|look\s+up|fetch|collect|get)\s+','',text,flags=re.I).strip(' ,;').rstrip('.')
    # "the latest news about X" searches for X; the request form is not part of the topic.
    topic=re.sub(r'^(?:the\s+)?(?:(?:latest|recent|newest|current|top)\s+)*(?:news(?:\s+stories)?|headlines|stories|articles|'
                 r'(?:research\s+)?papers|research|documentation|docs)\s+(?:about|on|regarding|for|of)\s+','',text,flags=re.I).strip()
    text=topic if len(topic)>=3 else text
    for alias,name in {'\ud30c\uc774\uc36c':'Python','\uc790\ubc14\uc2a4\ud06c\ub9bd\ud2b8':'JavaScript','\ub3c4\ucee4':'Docker','\ucfe0\ubc84\ub124\ud2f0\uc2a4':'Kubernetes'}.items():
        text=text.replace(alias,name)
    return text[:200] or objective[:200]


def clean_generated_query(context, query):
    """Remove graph-count instructions that are not part of the search topic."""
    topic=search_topic(context['objective']).lower()
    pattern=r'\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:(?:read-only|connected|sequential|linked|independent|ordered)\s+){0,2}steps?\b'
    query=re.sub(pattern,lambda match:match[0] if match[0].lower() in topic else '',query,flags=re.I)
    return ' '.join(query.split()).strip(' ,;')


def validate_query(context, query):
    # A clear named subject must survive generation; graph words are not topics.
    stop={'public','documentation','document','documents','docs','papers','research','reference','references','news','headlines','search','using','exactly','steps','two','three','four','five','six','seven','eight','nine','ten','the','and','for','related','supporting','current','material','only','every','step','must','read','query'}
    stop.update({'about','regarding','concerning','find','get','fetch','please','independently','separately','parallel'})
    topic=search_topic(context['objective'])
    subject=re.split(r'\b(?:about|on|regarding|concerning)\b',topic,maxsplit=1,flags=re.I)
    if len(subject)==2:
        topic=subject[1]
        stop-= {'news','documentation','docs','research'}
    def words(text):
        return {word[:-1] if word.endswith('s') and len(word)>3 else word for word in re.findall(r'[a-z][a-z0-9+#.-]{2,}',text.lower()) if word not in stop}
    anchors=words(topic)
    if anchors and not anchors & words(query):raise GoalQueryMismatch()
    versions=set(re.findall(r'\b\d+(?:\.\d+)+\b',topic))
    actual=set(re.findall(r'\b\d+(?:\.\d+)+\b',query))
    if actual!=versions:raise GoalQueryMismatch()
    from .workflow_goal_evaluation import topic_preserved
    if not topic_preserved(topic, query):raise GoalQueryMismatch()
