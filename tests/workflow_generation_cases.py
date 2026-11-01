"""Public synthetic objectives with independently stated expected behavior."""
D='docs.search.v1';N='news.search.v1'


def ok(id,prompt,contracts,*,queries=(),mode='chain',limit=1,hours=None):
    return dict(id=id,prompt=prompt,expected='review_required',contracts=contracts,queries=list(queries),mode=mode,limit=limit,hours=hours)


def clarify(id,prompt):return dict(id=id,prompt=prompt,expected='needs_details')


def reject(id,prompt):return dict(id=id,prompt=prompt,expected='rejected')


CASES=[
 ok('docs_two','Find public Python documentation using exactly two steps',[D]*2,queries=['python']),
 ok('docs_five','Find JavaScript documentation using exactly five steps',[D]*5,queries=['javascript']),
 ok('docs_ten','Find Rust documentation using exactly ten steps',[D]*10,queries=['rust']),
 ok('news_two','Find artificial intelligence news using exactly two steps',[N]*2,queries=['artificial']),
 ok('news_then_docs','Find battery recycling news then supporting documentation using exactly two steps',[N,D],queries=['battery']),
 ok('docs_then_news','Find Python documentation then related news using exactly two steps',[D,N],queries=['python']),
 ok('three_alternating','Find Python news then documentation then news using three steps',[N,D,N],queries=['python']),
 ok('three_topics','Find documentation for 3 topics: Docker, Kubernetes and Terraform',[D]*3,queries=['docker','kubernetes','terraform'],mode='independent'),
 ok('two_topic_then','Find Python documentation, then Rust documentation',[D]*2,queries=['python','rust'],mode='independent'),
 ok('two_topic_and','Find documentation for Python and Rust',[D]*2,queries=['python','rust'],mode='independent'),
 ok('independent_mixed','Independently find Python news and Python documentation using two steps',[N,D],queries=['python','python'],mode='independent'),
 clarify('reverse_after','Find Python documentation after finding Python news using two steps'),
 ok('negated_news_count','Find Python documentation without news using 3 steps',[D]*3,queries=['python']),
 ok('negated_send','Find Python documentation using two steps. Do not send emails.',[D]*2,queries=['python']),
 ok('three_results','Find Python documentation using two steps. Return 3 results per step.',[D]*2,queries=['python'],limit=3),
 ok('top_five','Find Python documentation using two steps with top 5 results per step',[D]*2,queries=['python'],limit=5),
 ok('last_week','Find battery news from the last 7 days using two steps',[N]*2,queries=['battery'],hours=168),
 ok('last_twelve_hours','Find battery news from the last 12 hours using two steps',[N]*2,queries=['battery'],hours=12),
 clarify('one_step','Find Python documentation using one step'),
 clarify('eleven_steps','Find Python documentation using 11 steps'),
 clarify('eleven_word','Find Python documentation using eleven steps'),
 clarify('zero_steps','Find Python documentation using 0 steps'),
 clarify('conflicting_counts','Find Python documentation using exactly two steps and three tasks'),
 clarify('too_many_topics','Find documentation for 11 topics: Alpha, Bravo, Charlie, Delta, Echo, Foxtrot, Golf, Hotel, India, Juliet and Kilo'),
 clarify('topics_count_conflict','Find documentation for 3 topics: Docker, Kubernetes and Terraform using exactly two steps'),
 clarify('unknown_weather','Find a weather forecast using two steps'),
 clarify('unsupported_summary','Find battery news then summarize the results using two steps'),
 clarify('unsupported_send','Find battery news then send an email using two steps'),
 reject('private_url','Find documentation at https://private.example/internal using two steps'),
 reject('private_token','Find documentation using Bearer synthetic-private-token'),
 reject('empty',''),
 reject('oversized','Find documentation '+('x'*501)),
 ok('ko_three','\ud30c\uc774\uc36c \ubb38\uc11c\ub97c 3\ub2e8\uacc4\ub85c \uac80\uc0c9\ud574\uc918',[D]*3,queries=['python']),
 ok('ko_mixed','AI \ub274\uc2a4\ub97c \ucc3e\uc740 \ub2e4\uc74c \uad00\ub828 \ubb38\uc11c\ub97c \uac80\uc0c9\ud558\ub294 2\ub2e8\uacc4 \uc6cc\ud06c\ud50c\ub85c\uc6b0',[N,D],queries=['ai']),
 ok('ko_exclude_news','\ub274\uc2a4\ub294 \uc81c\uc678\ud558\uace0 Python \ubb38\uc11c\ub9cc 3\ub2e8\uacc4\ub85c \uac80\uc0c9\ud574\uc918',[D]*3,queries=['python']),
 clarify('ko_summary','AI \ub274\uc2a4\ub97c \uac80\uc0c9\ud55c \ud6c4 \uacb0\uacfc\ub97c \uc694\uc57d\ud574\uc918'),
 ok('cpp_topic','Find C++ documentation using two steps',[D]*2,queries=['c++']),
 ok('dotnet_topic','Find .NET documentation using two steps',[D]*2,queries=['.net']),
 ok('version_topic','Find Python 3.12 documentation using two steps',[D]*2,queries=['python','3.12']),
 ok('news_payment_topic','Find news about payment security using two steps',[N]*2,queries=['payment']),
 ok('docs_news_topic','Find documentation about news APIs using two steps',[D]*2,queries=['news']),
 clarify('unsupported_translation','Translate a Korean document into French using two steps'),
 clarify('conflicting_types','Find news and documentation using three steps'),
 clarify('too_many_results','Find Python documentation using two steps with 100 results per step'),
 ok('summary_as_topic','Find documentation about summarization algorithms using two steps',[D]*2,queries=['summari']),
 ok('translation_as_topic','Find documentation about translation algorithms using two steps',[D]*2,queries=['translation']),
 ok('negated_summary','Find Python documentation using two steps. Do not summarize.',[D]*2,queries=['python']),
 clarify('excessive_period','Find battery news from the last 30 days using two steps'),
 clarify('conflicting_limits','Find Python documentation using two steps. Return 2 results and top 3 results per step.'),
 ok('upper_case_count','Find Python documentation using exactly THREE steps',[D]*3,queries=['python']),
 ok('research_news','Find battery research news using two steps',[N]*2,queries=['battery']),
 ok('news_about_docs','Find news about documentation software using two steps',[N]*2,queries=['documentation']),
]


def assess(case,result,status):
    state=result.get('state')
    if case['expected']=='rejected':return {'rejected':status in (400,403,404,422)}
    if case['expected']=='needs_details':return {'clear_clarification':status==200 and state=='needs_details','no_model_call':result.get('model_calls')==0}
    nodes=result.get('definition',{}).get('nodes',[])
    checks={'review':status==200 and state=='review_required','contract_sequence':[n.get('contract_id') for n in nodes]==case['contracts'],
      'result_limit':bool(nodes) and all(n['input'].get('limit')==case['limit'] for n in nodes)}
    queries=case.get('queries',[])
    if case['mode']=='independent':
        checks['independent']=bool(nodes) and all(not n['bindings'] and not n['after'] for n in nodes)
        checks['subjects']=len(nodes)==len(queries) and all(q.lower() in n['input'].get('query','').lower() for q,n in zip(queries,nodes))
    else:
        checks['subjects']=bool(nodes) and all(q.lower() in nodes[0]['input'].get('query','').lower() for q in queries)
        # Same-kind steps chain on the returned title; a step of another kind searches the request topic (QA 17).
        checks['connections']=bool(nodes) and all(n['bindings'].get('query')=={'node_id':nodes[i-1]['id'],'path':['items',0,'title']}
            if n['contract_id']==nodes[i-1]['contract_id'] else
            (not n['bindings'] and nodes[i-1]['id'] in n['after'] and all(q.lower() in n['input'].get('query','').lower() for q in queries))
            for i,n in enumerate(nodes) if i)
    if case.get('hours') and nodes:
        from datetime import datetime,timezone
        values=[n['input'].get('from_utc') for n in nodes if n['contract_id']==N]
        checks['period']=bool(values) and all(v and abs((datetime.now(timezone.utc)-datetime.fromisoformat(v.replace('Z','+00:00'))).total_seconds()/3600-case['hours'])<.05 for v in values)
    return checks
