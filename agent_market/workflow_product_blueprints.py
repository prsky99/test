"""Research-product candidates; never approval, publication or fixture results."""
from copy import deepcopy
from .capability_contracts import CONTRACTS


def get(path):return {'op':'get','path':path}
def obj(**fields):return {'op':'object','fields':fields}


def definitions(primary_id, alternate_id, primary_io, alternate_io):
    def search(nid,name,rid,profile,query,x):
        return {'id':nid,'name':name,'type':'agent','kind':'mcp','resource_id':rid,'position':{'x':x,'y':180},
                'data':{'tool':'search_research_papers' if rid==primary_id else 'search_arxiv','io_profile':profile,
                        'input':{'query':query,'language':'en','limit':2}}}
    def output(expression):
        schemas={'items':deepcopy(CONTRACTS['docs.search.v1']['output_schema']['properties']['items']),
                 'first':deepcopy(CONTRACTS['docs.search.v1']['output_schema']['properties']['items']),
                 'second':deepcopy(CONTRACTS['docs.search.v1']['output_schema']['properties']['items']),
                 'references':{'type':'array','maxItems':5,'items':{'type':'object','properties':{k:{'type':'string'} for k in ('title','url','accessed_at','source_version')},'required':['title','url','accessed_at','source_version'],'additionalProperties':False}},
                 'partial':{'type':'boolean'},'first_partial':{'type':'boolean'},'second_partial':{'type':'boolean'}}
        fields=expression['fields']
        output_schema={'type':'object','properties':{k:schemas[k] for k in fields},'required':list(fields),'additionalProperties':False}
        return {'id':'response','type':'output_transform','kind':'transform','name':'Application response','position':{'x':850,'y':180},
            'data':{'input':{'primary':"{{$node['search'].output.structuredContent}}"},
                    'transform':{'version':'json-io-transform-v1','input_schema':{'type':'object'},'output_schema':output_schema,'expression':expression}}}
    def pair(nid,rid,profile):return {'node_id':nid,'resource_id':rid,'contract_id':'docs.search.v1','alternate_io_profile':profile}
    single=search('search','Research lookup',primary_id,primary_io,'retrieval augmented generation',320)
    products=[]
    result=output(obj(items=get('/primary/items'),partial=get('/primary/partial')))
    products.append({'slug':'research-search-api','name':'Research Search API',
        'description':'Search public articles and preprints with source links and recorded retrieval times. Review original records before relying on them.',
        'use_case':'A research search backend for a website or mobile application.',
        'inputs':[{'name':'query','node_id':'search','argument':'query','type':'string','min_length':2,'max_length':160},
                  {'name':'limit','node_id':'search','argument':'limit','type':'integer','minimum':1,'maximum':5}],
        'nodes':[deepcopy(single),result],'pairs':[pair('search',alternate_id,alternate_io)],
        'edges':[{'source':'search','target':'response'}]})
    left=deepcopy(single);left['name']='First topic research'
    right=search('compare','Second topic research',alternate_id,alternate_io,'quantum error correction',590)
    result=output(obj(first=get('/primary/items'),second=get('/secondary/items'),
                      first_partial=get('/primary/partial'),second_partial=get('/secondary/partial')))
    result['data']['input']['secondary']="{{$node['compare'].output.structuredContent}}"
    products.append({'slug':'research-comparison-board','name':'Research Comparison Board',
        'description':'Compare source records for two research topics in separate evidence panels. Includes articles and preprints; no unsupported scientific conclusions are generated.',
        'use_case':'A two-topic evidence board in a research application.',
        'inputs':[{'name':'first_query','node_id':'search','argument':'query','type':'string','min_length':2,'max_length':160},
                  {'name':'second_query','node_id':'compare','argument':'query','type':'string','min_length':2,'max_length':160}],
        'nodes':[left,right,result],
        'pairs':[pair('search',alternate_id,alternate_io),pair('compare',primary_id,primary_io)],
        'edges':[{'source':'search','target':'response'},{'source':'compare','target':'response'}]})
    references={'op':'map','value':get('/primary/items'),'item':obj(title=get('/title'),url=get('/url'),
                    accessed_at=get('/retrieved_at'),source_version=get('/version'))}
    result=output(obj(references=references,partial=get('/primary/partial')))
    products.append({'slug':'source-bibliography-api','name':'Source Bibliography API',
        'description':'Build a machine-readable source bibliography from public research records, preserving titles, links and retrieval times without inventing authors or conclusions.',
        'use_case':'A source-list endpoint for reports, knowledge pages and reading applications.',
        'inputs':[{'name':'query','node_id':'search','argument':'query','type':'string','min_length':2,'max_length':160}],
        'nodes':[deepcopy(single),result],'pairs':[pair('search',alternate_id,alternate_io)],
        'edges':[{'source':'search','target':'response'}]})
    for product in products:
        product['workflow']={'name':product['name'],'description':product['description'],'category':'dev_tools',
            'trigger_type':'manual','is_active':1,'is_template':0,'author':'Agent Concierge',
            'tags':'workflow-product-candidate,'+product['slug'],'nodes':product.pop('nodes'),'edges':product.pop('edges')}
    return products


def recipes(resource,tool,contract,native):
    common=CONTRACTS[contract]
    input_map=obj(query=get('/query'),limit=get('/limit'))
    owned=tool=='search_research_papers'
    fields={'title':{'op':'english','value':get('/title')},'url':get('/url'),
            'excerpt':({'op':'concat','values':[{'op':'const','value':'Public bibliographic record. DOI: '},get('/doi')],'separator':''} if owned
                       else {'op':'english','value':{'op':'coalesce','values':[get('/abstract'),get('/title')]}}),
            'version':({'op':'choose','value':get('/publication_date'),'equals':'','then':{'op':'const','value':'Undated record'},'otherwise':get('/publication_date')} if owned
                       else {'op':'choose','value':get('/year'),'equals':None,'then':{'op':'const','value':'Undated record'},'otherwise':{'op':'string','value':get('/year')}}),
            'retrieved_at':{'op':'get_root','path':'/retrieved_at' if owned else '/as_of'}}
    output_map=obj(items={'op':'map','value':get('/data/items' if owned else '/results'),'item':obj(**fields)},
                   partial=get('/data/partial') if owned else {'op':'const','value':False})
    def recipe(source,target,expression):return {'version':'json-io-transform-v1','input_schema':source,'output_schema':target,'expression':expression}
    return {'resource_id':resource,'tool':tool,'contract_id':contract,
        'input_transform':recipe(common['input_schema'],native['inputSchema'],input_map),
        'output_transform':recipe(native['outputSchema'],common['output_schema'],output_map),
        'status_checks':([{'path':'/data/query','equals_input':'/query'}] if owned else
                         [{'path':'/status','allowed':['ok','no_results']},{'path':'/query','equals_input':'/query'},
                          {'path':'/source/name','allowed':['arXiv']}])}
