"""Build the isolated Pearl Connection HTML publication without dependencies."""
from pathlib import Path
from html import escape as e
import json
import re
import sys
import catalog_pages
import necklace as pearl_necklace
import reference_pages
import shared_ui

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'html'
PAGES = []
ICONS = {
 'activity':'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
 'refresh':'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-2l2 3M4 16l2 3a7 7 0 0 0 12-2"/>',
 'database':'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
 'search':'<circle cx="10.5" cy="10.5" r="7.5"/><path d="m16 16 5 5"/>',
 'arrow':'<path d="M4 12h16m-6-6 6 6-6 6"/>',
 'back':'<path d="M20 12H4m6-6-6 6 6 6"/>',
 'file':'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8m-8 4h6"/>',
 'network':'<circle cx="12" cy="5" r="3"/><circle cx="5" cy="19" r="3"/><circle cx="19" cy="19" r="3"/><path d="m10.5 8-4 8m7-8 4 8M8 19h8"/>',
 'play':'<path d="m7 3 14 9-14 9Z"/>',
 'download':'<path d="M12 3v12m-5-5 5 5 5-5M3 15v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5"/>',
 'shield':'<path d="M12 3 3 7v6c0 5 9 9 9 9s9-4 9-9V7Z"/>',
 'book':'<path d="M12 5v17M2 3c5-1 8 0 10 2 2-2 5-3 10-2v16c-5-1-8 0-10 3-2-3-5-4-10-3Z"/>',
 'link':'<path d="m10 13 4-4m-5 8-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m0-1 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0"/>',
 'chat':'<path d="M21 11a8 8 0 0 1-8 8H7l-5 3V5a3 3 0 0 1 3-3h8a8 8 0 0 1 8 9Z"/>',
 'sun':'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
 'moon':'<path d="M21 13A9 9 0 0 1 11 3 9 9 0 1 0 21 13Z"/>',
 'menu':'<path d="M3 6h18M3 12h18M3 18h18"/>',
 'close':'<path d="m6 6 12 12M6 18 18 6"/>',
 'check':'<path d="m5 12 4 4L20 5"/>',
 'info':'<circle cx="12" cy="12" r="10"/><path d="M12 11v6m0-11v1"/>',
 'user':'<circle cx="12" cy="7" r="4"/><path d="M4 22v-2a8 8 0 0 1 16 0v2"/>',
 'users':'<path d="M16 22v-2a6 6 0 0 0-12 0v2m16-1v-2a6 6 0 0 0-4-5"/><circle cx="10" cy="6" r="4"/><path d="M17 2a4 4 0 0 1 0 8"/>',
 'home':'<path d="m3 10 9-8 9 8v12h-7v-8h-4v8H3Z"/>',
 'settings':'<path d="m9 3 1-2h4l1 2 3 2 3 1v4l-2 2 2 2v4l-3 1-3 2-1 2h-4l-1-2-3-2-3-1v-4l2-2-2-2V6l3-1Z"/><circle cx="12" cy="12" r="3"/>',
 'bell':'<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 10h18c0-3-3-3-3-10M10 22h4"/>',
 'logout':'<path d="M9 3H4v18h5m5-15 6 6-6 6M8 12h12"/>',
 'plus':'<path d="M12 4v16M4 12h16"/>',
 'mail':'<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m2 5 10 8L22 5"/>',
 'sparkles':'<path d="m12 2 3 7 7 3-7 3-3 7-3-7-7-3 7-3Z"/>',
 'chevron':'<path d="m8 4 8 8-8 8"/>',
 'lock':'<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4"/>',
 'github':'<path fill="currentColor" stroke="none" d="M12 1a11 11 0 0 0-3.5 21.4c.6.1.8-.3.8-.5v-2.1c-3.4.7-4.1-1.4-4.1-1.4-.5-1.3-1.2-1.6-1.2-1.6-1.1-.8.1-.8.1-.8 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.7 1.3 3.4 1 .1-.8.4-1.3.8-1.6-2.8-.3-5.7-1.4-5.7-6.1 0-1.4.5-2.5 1.3-3.3-.1-.3-.6-1.6.2-3.3 0 0 1-.3 3.4 1.3a12 12 0 0 1 6.2 0C18 3.6 19 3.9 19 3.9c.8 1.7.3 3 .2 3.3.8.8 1.3 1.9 1.3 3.3 0 4.7-2.9 5.8-5.7 6.1.5.4.8 1.1.8 2.2v3.1c0 .3.2.6.8.5A11 11 0 0 0 12 1Z"/>'
}

def icon(name):
 return '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'+ICONS.get(name,ICONS['file'])+'</svg>'
def pearl(size=''):
 return '<span class="pearl '+size+'" aria-hidden="true"></span>'
def brand():
 return '<a class="brand" href="index.html"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span>Agent Concierge</a>'
def badge(text='Example preview',cls=''):
 return '<span class="badge '+cls+'">'+e(text)+'</span>'
def btn(text,href=None,ico=None,cls='',attrs=''):
 body=(icon(ico) if ico else '')+e(text)
 return f'<a class="btn {cls}" href="{e(href,quote=True)}" {attrs}>{body}</a>' if href else f'<button type="button" class="btn {cls}" {attrs}>{body}</button>'
def field(label,value='',typ='text',placeholder='',name=None,required=False):
 name=name or re.sub('[^a-z0-9]+','-',label.lower()).strip('-')
 req=' required' if required else ''
 tag=f'<textarea id="{name}" name="{name}" placeholder="{e(placeholder)}"{req}>{e(value)}</textarea>' if typ=='textarea' else f'<input id="{name}" name="{name}" type="{typ}" value="{e(value,quote=True)}" placeholder="{e(placeholder,quote=True)}"{req}>'
 return f'<div class="field"><label for="{name}">{e(label)}</label>{tag}</div>'
def select(label,options,name):
 return f'<div class="field"><label for="{name}">{e(label)}</label><select id="{name}" name="{name}">'+''.join(f'<option>{e(v)}</option>' for v in options)+'</select></div>'
def check(text,name,attrs=''):
 return f'<label class="check"><input type="checkbox" id="{name}" name="{name}" {attrs}><span>{e(text)}</span></label>'
def protocol(name='protocol',default='A2A',any_=True):
 return '<fieldset class="segmented" aria-label="Connection protocol">'+''.join(f'<label><input type="radio" name="{name}" value="{p}"'+(' checked' if p==default else '')+f'><span>{p}</span></label>' for p in (['A2A','MCP','x402','Any'] if any_ else ['A2A','MCP','x402']))+'</fieldset>'
def note(text,ico='info',cls=''):
 return f'<div class="note {cls}">{icon(ico)}<p>{text}</p></div>'
def fake_lines():
 return '<div class="fake-lines" aria-hidden="true"><i></i><i></i><i></i></div>'
def heading(eyebrow,title,lead):
 return f'<div class="page-heading"><p class="eyebrow">{e(eyebrow)}</p><h1>{title}</h1><p class="lead">{lead}</p></div>'
def strands(steps,numbered=False,large=False):
 return '<div class="strand '+('numbered' if numbered else '')+'">'+''.join(f'<div>{pearl("large" if large else "")}<h3>{t}</h3><p>{d}</p></div>' for t,d in steps)+'</div>'
def info_card(title,copy,ico='file',link=None):
 return f'<article class="card"><span class="icon-disc">{icon(ico)}</span><h3 style-marker="heading">{title}</h3><p>{copy}</p>'+ (btn('Explore',link,ico='arrow') if link else '')+'</article>'

NAV=[('Agent Status','agent-status'),('Learn','learn'),('Explore','explore'),('Test','test'),('Workflows','workflows'),('Chat','chat'),('List Your Agent','list-agent'),('About','about')]
POLICIES=[('Terms of Service','terms'),('Privacy Policy','privacy'),('Cookie Preferences','cookies'),('Do Not Sell or Share My Personal Info','privacy-choices'),('Accessibility Statement','accessibility'),('AI System Disclosures','disclosures'),('Notification Preferences','notifications'),('Contact','contact')]
def theme():
 return icon('sun')+'<button class="theme-toggle" type="button" data-action="theme" aria-label="Toggle dark theme" aria-pressed="false"></button>'+icon('moon')
def header(active='',workspace=False,auth=False):
 if workspace:
  return '<header class="ws-top"><div class="container header-inner">'+brand()+'<a class="small mobile-hidden" href="explore.html">Back to discovery</a><div class="header-actions">'+theme()+'</div>'+btn('Account','account.html','user','small')+'</div></header>'
 nav='' if auth else '<nav id="public-nav" class="public-nav" aria-label="Main navigation">'+''.join(f'<a href="{key}.html"'+(' aria-current="page"' if key==active else '')+'>'+name+'</a>' for name,key in NAV)+'</nav>'
 return '<header class="site-header'+(' auth-header' if auth else '')+'"><div class="container header-inner">'+brand()+nav+('<a class="small" href="explore.html">Back to discovery</a>' if auth else '')+'<div class="header-actions">'+theme()+('' if auth else '<button type="button" class="icon-btn menu-button" data-action="menu" aria-controls="public-nav" aria-expanded="false" aria-label="Open navigation">'+icon('menu')+'</button>')+'</div></div></header>'
def footer():
 return shared_ui.footer(brand,icon)
def sidebar(active='Overview'):
 links=[('Overview','workspace','home'),('Workflows','workspace-studio','network'),('Members & invitations','workspace-members','users'),('Account','account','user')]
 return '<aside class="ws-sidebar" aria-label="Workspace navigation"><p class="caption">Example workspace</p><div class="row">'+badge('Owner')+'</div><hr class="divider">'+''.join(f'<a class="side-item'+(' active' if title==active else '')+f'" href="{href}.html"'+(' aria-current="page"' if title==active else '')+'>'+icon(ico)+title+'</a>' for title,href,ico in links)+'</aside>'
def page(filename,title,content,reference=None,group='Pages',workspace=False,auth=False,active='',wsactive='Overview',dark=False):
 if filename in ('learn.html','list-agent.html','chat.html'):
  art='<div class="heading-pearls'+(' single' if filename=='chat.html' else '')+'" aria-hidden="true">'+pearl('large')+(pearl('large')+pearl('large') if filename!='chat.html' else '')+'</div>'
  if filename=='learn.html':
   art='<div class="heading-protocols" aria-hidden="true">'+''.join('<span>'+pearl('large')+'<b>'+p+'</b></span>' for p in ['A2A','MCP','x402'])+'</div>'
  if filename=='list-agent.html':
   art='<div class="heading-listing-art" aria-hidden="true"><div>'+pearl('large')+pearl('large')+pearl('large')+'</div><p>Individual agents.<br>A more powerful connection.</p></div>'
  content=content.replace('<div class="page-heading">','<div class="page-heading decorated">'+art,1)
 if workspace:content='<div class="container ws-layout">'+sidebar(wsactive)+'<main class="ws-main" id="main">'+content+'</main></div>'
 else:
  menu=filename in ('explore.html','test.html','workflows.html','chat.html','list-agent.html')
  if menu:content=content.replace('class="page-heading','class="page-heading pearl-menu-heading',1)
  content='<main class="container'+(' pearl-menu-page' if menu else '')+'" id="main">'+content+'</main>'
 ref=reference or 'concept/04-pearl-connection.png'
 ribbon='<div class="preview-ribbon"><span>Design preview · Illustrative content</span><div class="row"><a href="gallery.html">All layouts</a><a href="compare.html?page='+filename+'">Compare design</a><button class="reference-link" data-action="reference" type="button">Reference image</button></div></div>'
 html='<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\'; style-src \'self\'; img-src \'self\' data:; font-src \'self\'; connect-src \'none\'; object-src \'none\'; base-uri \'none\'; form-action \'none\'"><meta name="referrer" content="no-referrer"><meta name="description" content="'+e(title)+' — Pearl Connection design preview for Agent Concierge."><title>'+e(title)+' | Agent Concierge</title><link rel="icon" href="assets/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="assets/styles.css"><script src="assets/app.js" defer></script></head><body data-page="'+filename+'" data-reference="../design/'+e(ref)+'"'+(' data-theme="dark"' if dark else '')+'><a class="sr-only skip-link" href="#main">Skip to content</a>'+ribbon+header(active,workspace,auth)+content+footer()+modal_shell()+'<div class="toast" id="toast" role="status" aria-live="polite" hidden></div></body></html>'
 html=html.replace(' style-marker="heading"','')
 if filename in ('index.html','agent-status.html'):html=html.replace('Design preview · Illustrative content','Design preview · Snapshot &amp; examples',1)
 (OUT/filename).write_text(html)
 PAGES.append(dict(file=filename,title=title,reference='../design/'+ref,group=group))
def modal_shell():
 templates={'agent':agent_details(),'report':report_content(),'run':run_review(),'cookies':cookie_settings('-modal'),'create':create_workspace_form(),'invitation':invitation_review(),'import':import_form()}
 result='<dialog class="modal" id="preview-dialog" aria-labelledby="dialog-title"><div class="modal-inner"><div class="modal-heading"><h2 id="dialog-title">Review</h2><button class="icon-btn" type="button" data-action="close-dialog" aria-label="Close dialog">'+icon('close')+'</button></div><div id="dialog-body"></div></div></dialog>'
 result+=''.join('<template id="template-'+key+'">'+body+'</template>' for key,body in templates.items())
 result+=''.join('<template id="policy-'+key+'"><article class="policy-copy">'+value['html']+'</article></template>' for key,value in DOCS.items())
 return result

def necklace():
 (OUT/'assets/necklace.css').write_text('/* Necklace geometry is contained in one responsive SVG. */\n')
 (OUT/'assets/necklace-geometry.json').write_text(json.dumps(pearl_necklace.geometry(),indent=2))
 return pearl_necklace.markup(icon,badge)


def faq():
 return '<div class="faq">'+''.join('<details><summary>'+q+'</summary><p>'+a+'</p></details>' for q,a in [('What can I try?','Explore example agents and workflows for technology news, research and documentation. Each preview explains its scope and illustrative result.'),('How are agents checked?','Inspect recorded reports and execution checks. Recorded evidence does not guarantee current availability.'),('Can I choose a protocol?','Choose A2A, MCP or x402 explicitly. New requests default to A2A; Any searches across all three.')])+'</div>'
def home():
 catalog_pages.publish_home(sys.modules[__name__])

def agent_status():
 catalog_pages.publish_status(sys.modules[__name__])


AGENTS=[('Technology news agent','A2A','Finds and summarizes technology news from public sources.',['News','Research','Summarization']),('Research sources','MCP','Finds research sources on a topic and organizes them.',['Research','Analysis','References']),('Documentation search','x402','Searches technical documentation for your question.',['Documentation','Technical']),('Public knowledge agent','A2A','Finds factual information from public sources.',['News','Reference']),('Weather overview','A2A','Organizes a public weather overview for a selected location.',['Weather','Research']),('Document reader','MCP','Summarizes selected public documents.',['Documentation','Summarization']),('Research notes','A2A','Turns source material into structured notes.',['Research','Documentation']),('News comparison','x402','Compares a selection of news sources.',['News','Analysis'])]
def agent_card(a,index):
 title,p,copy,tags=a
 return f'<article class="card agent-card" data-agent-index="{index}" data-agent-protocol="{p}" data-execution="{str(index%2==0).lower()}" data-agent-tags="{e(" ".join(tags))}"><div class="between"><div class="row">'+pearl()+'<h3>'+title+'</h3></div>'+badge(p,'protocol')+'</div><p>'+copy+'</p><div class="tags">'+''.join('<span>'+t+'</span>' for t in tags)+'</div><div class="actions">'+btn('Read report',ico='file',cls='small',attrs='data-action="report"')+btn('View details',ico='arrow',cls='small',attrs='data-action="agent-details"')+'</div></article>'
def agent_details():
 return badge()+'<h3>Technology news agent</h3><h4>What it does</h4><p>Finds and summarizes public technology news with citations and key takeaways.</p><hr class="divider"><h4>Recorded checks</h4><p>Review example outputs, sources and limitations for each recorded run.</p><hr class="divider"><h4>Connection details</h4><dl><dt>Protocol</dt><dd data-selected-protocol>A2A</dd><dt>Category</dt><dd>News &amp; Research</dd><dt>Input</dt><dd>A topic or area of interest</dd><dt>Output</dt><dd>Structured brief with sources</dd></dl>'+btn('Inspect connection',ico='network',cls='primary block',attrs='data-action="connection"')+'<p class="caption center">Availability can change.</p>'
def explore():
 content=heading('Connected intelligence','Find your next capable agent.','Search by task, inspect the evidence, and choose your next step.')
 content+='<form class="card" id="search-form" data-form="search"><div class="filter-grid">'+field('Search for an agent or task',placeholder='technology news',name='query')+'<div><span class="field-label">Protocol</span>'+protocol('search-protocol','Any')+'</div>'+select('Category',['All categories','News & Research','Documentation','Weather','Docs, Knowledge Bases & RAG','Web Search & Scraping','Data Utilities & Format Conversion','Database & Analytics'],'category')+'<button class="btn primary" id="search-button">'+icon('search')+'Search</button></div><div class="filters-bottom"><div><span class="field-label">Filter by evidence</span><div class="row">'+check('Recorded reports','reports','checked')+check('Execution checked','execution')+'</div></div><div><span class="field-label">Common tasks</span><div class="row">'+''.join(btn(t,cls='small',attrs=f'data-action="quick-search" data-query="{t}"') for t in ['News','Research','Documentation','Weather'])+'</div></div></div></form>'
 content+='<p id="catalog-context" class="note" hidden></p><div class="results-layout"><section><div class="between"><h2>Illustrative search results</h2><span id="search-count" class="caption" role="status">4 example agents shown</span></div><div class="grid two" id="agent-results">'+''.join(agent_card(a,i) for i,a in enumerate(AGENTS[:4]))+'</div><div id="search-empty" class="card empty" hidden><h3>No matching example agents</h3><p>Try a broader task or choose Any protocol.</p>'+btn('Clear filters',attrs='data-action="clear-search"')+'</div><div class="actions center">'+btn('Load More Agents',ico='plus',cls='primary',attrs='id="load-more" data-action="load-more"')+'</div></section><aside class="card details-panel" id="agent-side">'+agent_details()+'</aside></div><section class="section"><h2>Understand the evidence.</h2><div class="grid two">'+info_card('Recorded reports',"View example reports from past runs to understand the agent's output and sources.",'file')+info_card('Execution evidence',"Check recorded connections and input handling. Past checks do not promise current availability.",'settings')+'</div></section><template id="extra-agents">'+''.join(agent_card(a,i+4) for i,a in enumerate(AGENTS[4:]))+'</template>'
 page('explore.html','Find your next capable agent',content,'pages/02-explore.png',active='explore')

EXAMPLES=[('Technology news','Find and summarize recent technology news.','file'),('Web research','Research a topic and organize key information.','search'),('Mobile documentation','Find and summarize official documentation.','book'),('Racket research','Compare specifications and published reviews.','book')]
def examples():
 return '<div class="side-nav">'+''.join('<button type="button" class="side-item'+(' active' if n==0 else '')+f'" data-action="example" data-example="{e(t)}">'+icon(i)+'<span><strong>'+t+'</strong><p>'+d+'</p></span></button>' for n,(t,d,i) in enumerate(EXAMPLES))+'</div>'
def result_items():
 return ''.join('<article class="result-item"><div class="result-art">'+(pearl() if n==1 else icon(i))+'</div><div><h4>'+t+'</h4><p>'+d+'</p><button type="button" class="link-button small" data-action="example-source">View source →</button></div></article>' for n,(t,d,i) in enumerate([('AI infrastructure','Illustrative overview of infrastructure and efficiency developments.','network'),('Agent interoperability','Illustrative discussion of agent connections across systems.','network'),('Developer tools','Illustrative overview of documentation and developer workflows.','file')]))
def test_page():
 content=heading('Test an agent','See an agent in action.','Choose an example, review the input, and inspect the result.')+strands([('1. Choose','Pick an example agent and task.'),('2. Review','Check the input and target.'),('3. Run','Run the selected request.'),('4. Inspect','Review the result and evidence.')])
 content+='<div class="test-layout"><section class="card test-input"><div><h3>Examples</h3><p class="small">Try an example with a clear task.</p>'+examples()+'</div><form data-form="test"><p class="eyebrow">Selected example</p><h2 data-example-title>Technology news</h2><p>Find and summarize recent technology news from public sources, with links to the original articles.</p>'+select('Agent protocol',['A2A (Agent-to-Agent)','MCP','x402'],'test-protocol')+field('Your request','Find recent technology news with source links.','textarea',name='test-request')+select('Target and scope',['Public web (open sources)'],'test-scope')+'<p class="caption">Review the selected input and target before running.</p><div class="actions"><button class="btn primary" id="run-test">'+icon('play')+'Run test</button>'+btn('Reset input',cls='small',attrs='data-action="reset-test"')+'</div></form></section><section class="card" id="test-result">'+badge('Illustrative result')+'<h2>Your news overview</h2><p>A concise example summary, organized by topic.</p>'+result_items()+'<div class="tabs"><button class="tab" data-tab="summary" aria-selected="true">Summary</button><button class="tab" data-tab="sources" aria-selected="false">Sources</button><button class="tab" data-tab="connection" aria-selected="false">Connection</button></div><div data-tab-panel="summary"><h4>What was checked</h4><p>Selected public information, source relevance, and an example summary with source references.</p></div><div data-tab-panel="sources" hidden><p>Source links in this layout are illustrative. No external agent has been executed.</p></div><div data-tab-panel="connection" hidden><p>A2A · Review the agent and input before connecting.</p></div></section></div><section class="section"><p class="eyebrow">Understand the results</p><h2>Know what a test tells you.</h2><p class="lead">A test shows an agent’s scope, connections and kind of output.</p><div class="grid three">'+info_card('Connection checks','Review the tools and data sources before running.','link')+info_card('Execution evidence','Inspect the steps and information used for a result.','file')+info_card('Current availability','Recorded results are illustrative and may vary with availability.','info')+'</div></section>'
 page('test.html','See an agent in action',content,'pages/03-test.png',active='test')

def workflow_graph():
 return '<div class="card workflow-graph"><div class="between">'+badge('Concept preview')+'<span class="caption">Three agents, one useful outcome</span></div>'+strands([('Find news','Search for recent technology news across selected sources.'),('Review sources','Check relevance and credibility, and select useful items.'),('Prepare brief','Summarize key points and include source references.')],large=True)+'</div>'
def brief():
 return badge('Illustrative result')+'<h3>Technology news brief</h3><div class="card"><h4>Summary</h4><p>An illustrative brief showing how selected findings can be organized.</p><hr class="divider"><h4>Key items</h4><ul><li>Research and development across AI tools.</li><li>Interoperability between agents and services.</li><li>Clear documentation and source references.</li></ul><hr class="divider"><h4>Sources</h4>'+btn('Review example sources',ico='arrow',attrs='data-action="example-source"')+'</div>'
def workflows():
 content=heading('Workflows','Connect strengths. Create outcomes.','Review the steps and inputs before each run.')+'<div class="workflow-layout"><aside class="card side-nav"><h3>Workflow templates</h3><p class="small">Start with an example that connects the right agents.</p>'+''.join('<button type="button" class="side-item'+(' active' if n==0 else '')+f'" data-action="workflow-template" data-name="{t}">'+icon(i)+'<span><strong>'+t+'</strong><p>'+d+'</p></span></button>' for n,(t,d,i) in enumerate([('Technology news','Find, review and summarize recent technology news.','file'),('Mobile development','Research and compare development options.','file'),('Racket comparison','Compare options across selected sources.','book')]))+'</aside><section><h2 id="workflow-name">Technology news</h2><p>Find recent technology news, review sources and prepare a concise brief.</p><div class="actions">'+btn('Run workflow',ico='play',cls='primary',attrs='data-action="workflow-review"')+btn('Download web app',ico='download',attrs='data-action="download"')+'</div>'+workflow_graph()+'</section></div><section class="card section"><h3>'+icon('file')+' Review inputs</h3><form data-form="workflow" class="split"><div>'+field('Your request','Find recent technology news.','textarea',name='workflow-input')+'</div><div>'+select('Protocol',['A2A','MCP','x402'],'workflow-protocol')+'<p class="caption">Check selected sources. Review and edit the brief before external sharing.</p>'+btn('Review this run',ico='play',attrs='data-action="workflow-review"')+'</div></form></section><div class="grid two section"><article class="card" id="workflow-output">'+brief()+'</article><article class="card"><h3>Run details</h3><p>Preview of this workflow.</p><ol class="step-list"><li><div><h4>Find news</h4><p>Search across selected sources.</p></div></li><li><div><h4>Review sources</h4><p>Check relevance and credibility.</p></div></li><li><div><h4>Prepare brief</h4><p>Summarize key points and references.</p></div></li></ol></article></div><div class="card between"><div><h3>Use the web app</h3><p>Download a local interface and review each run.</p></div>'+btn('Download web app',ico='download',attrs='data-action="download"')+'</div>'
 page('workflows.html','Connect strengths. Create outcomes.',content,'pages/04-workflows.png',active='workflows')

def recommendation():
 return '<article class="recommendation">'+badge('Example recommendation')+'<h3 data-rec-name>Research assistant</h3>'+badge('A2A','protocol')+'<p>Helps you find and summarize relevant public information, with clear citations and links.</p><div class="actions">'+btn('Review recorded checks',ico='file',cls='small',attrs='data-action="report"')+btn('View details',ico='arrow',cls='primary',attrs='data-action="agent-details"')+'</div></article>'
def chat():
 content=heading('Conversational assistance','Start with the right agent.','Describe the task. Compare up to three relevant recommendations.')+'<div class="row"><span class="field-label">Connection protocol</span>'+protocol('chat-protocol')+'</div><div class="chat-layout section"><section class="card"><div class="between"><span class="caption">Example conversation</span>'+badge('Illustrative result')+'</div><div id="chat-messages"><div class="chat-message"><span class="icon-disc aqua">'+icon('sparkles')+'</span><div class="message-body"><p>I found a relevant agent for your task.<br>Here is one recommendation based on your request.</p>'+recommendation()+btn('Show an alternative',ico='network',attrs='data-action="alternative"')+'</div></div><div class="chat-request">Find an agent for technology research.</div></div><details class="faq"><summary>Earlier messages</summary><p>Start a new request or ask for an alternative.</p></details><form class="chat-composer" data-form="chat"><label class="sr-only" for="chat-input">What do you want to accomplish?</label><input id="chat-input" name="question" placeholder="What do you want to accomplish?" required><button class="btn primary" id="chat-send">Send '+icon('arrow')+'</button></form></section><aside class="card details-panel"><div class="between"><h3>Agent details</h3>'+btn('Open',ico='arrow',cls='small',attrs='data-action="agent-details"')+'</div>'+agent_details()+'</aside></div><div class="card between"><div class="row"><span class="icon-disc">'+icon('bell')+'</span><div><h3>Request task updates</h3><p>Optional · Destination verification required.</p></div></div>'+btn('Review options',href='task-updates.html',ico='arrow')+'</div>'
 content=content.replace('Technology news agent','Research assistant').replace('Finds and summarizes public technology news with citations and key takeaways.','Helps you find, evaluate and summarize relevant public research sources with clear citations.')
 page('chat.html','Start with the right agent',content,'pages/05-chat.png',active='chat')

def learn():
 page('learn.html','Understand the connections',reference_pages.learn(heading,icon,pearl),'pages/06-learn.png',active='learn')

def listing_form():
 return '<form data-form="listing">'+field('Agent name',placeholder='Your agent name',required=True)+'<span class="field-label">Protocol</span>'+protocol('listing-protocol',any_=False)+field('Public endpoint',typ='url',placeholder='https://your-agent.example/a2a',required=True)+select('Category',['Research','News','Documentation','Weather'],'list-category')+field('Description',typ='textarea',placeholder='Describe what your agent can do.',required=True)+field('Public documentation (optional)',typ='url',placeholder='https://your-agent.example/docs')+check('I am authorized to submit this public endpoint.','list-authority','required')+check('I agree to the Terms of Service and acknowledge the Privacy Policy.','list-terms','required')+'<div class="actions"><button class="btn primary">'+icon('arrow')+'Submit for review</button>'+btn('Import agent information',attrs='data-action="import"')+'</div><p class="caption">Design preview. No submission is sent.</p></form>'
def listing():
 content=heading('Share your capabilities','Give your agent a place<br>in the connection.','Submit a public endpoint for review and discovery.')+strands([('1. Submit endpoint','Provide public connection details.'),('2. Connectivity review','Review capability and compatibility.'),('3. Catalog listing','Listing depends on review.')])+'<div class="split section"><section class="card"><h2>Agent details</h2><p>Provide information so your agent can be reviewed and discovered.</p>'+listing_form()+'</section><aside class="card"><h2>Before you submit</h2><p>A few things to check to help the review process go smoothly.</p><div class="evidence-list">'+''.join('<div class="evidence-item"><span class="icon-disc">'+icon(i)+'</span><div><h3>'+t+'</h3><p>'+d+'</p></div></div>' for t,d,i in [('Public endpoint','Provide a publicly accessible endpoint that can be reviewed.','link'),('Accurate protocol','Select A2A, MCP or x402 accurately.','file'),('Clear capabilities','Describe the main tasks and intended uses.','settings'),('Connection details','Provide public documentation when available.','book')])+'</div><hr class="divider"><h3>What happens next?</h3><p>Review checks connectivity, compatibility and the information provided. Listing is subject to the outcome.</p></aside></div><section class="grid two section"><article class="card"><h3>Will my agent appear immediately?</h3><p>No. Submissions are reviewed before being considered for the catalog.</p></article><article class="card"><h3>Can I review the connection details?</h3><p>Public connection details and documentation help make the scope clear.</p></article></section>'
 page('list-agent.html','Give your agent a place in the connection',content,'pages/07-list-your-agent.png',active='list-agent')
def about():
 page('about.html','Individual strengths. Shared possibilities.',reference_pages.about(icon,pearl,btn),'pages/08-about.png',active='about')

def workspace_overview():
 content='<div class="page-heading"><div class="between"><div><p class="eyebrow">Example workspace</p><h1>Your workspace</h1><p class="lead">Bring the right agents together, one reviewed step at a time.</p></div>'+btn('Create workflow','workspace-studio.html','plus','primary')+'</div></div><section class="card"><h2>Private workflows</h2><p>Design, review and run workflows with the right agents.</p><div class="grid two">'
 for title,state,copy,action in [('Technology news brief','Draft','Find and summarize selected technology news.','Open draft'),('Research summary','Ready to review','Research a topic and create a concise summary.','Review inputs')]:
  content+='<article class="card"><div class="between">'+badge()+badge(state,'protocol')+'</div><div class="actions">'+pearl()+'</div><h3>'+title+'</h3><p>'+copy+'</p><hr class="divider"><p class="caption">'+icon('network')+' Read-only tasks · Review before testing</p>'+btn(action,'workspace-studio.html' if state=='Draft' else 'workspace-review.html','arrow','primary block')+'</article>'
 content+='</div></section><section class="card section"><h2>From idea to impact</h2><p>A clear path from design to a useful result.</p>'+strands([('Design','Choose the right agents and define the task.'),('Review','Inspect the inputs before every test.'),('Test','Run a reviewed test with exact inputs.'),('Release','Release after a successful test.')])+note('A draft stays private. Review the inputs before every test. Release follows a successful test.','info','warn')+'</section><section class="card section"><div class="between"><h2>Recent task history</h2>'+btn('View history','workspace-review.html','arrow','small')+'</div>'+badge()+'<div class="history-row"><span>'+icon('file')+' Technology news brief</span>'+badge('Test succeeded','success')+'</div><div class="history-row"><span>'+icon('file')+' Research summary</span>'+badge('Not run')+'</div></section>'
 page('workspace.html','Your workspace',content,'workspace-auth/01-workspace-overview.png','Workspace',workspace=True)

def state(number,title,content):
 return '<section class="board-state"><div class="state-heading"><span class="state-number">'+str(number).zfill(2)+' ·</span><h2>'+title+'</h2></div>'+content+'</section>'
def create_workspace_form():
 return '<form data-form="create-workspace">'+field('Workspace name',placeholder='Name your workspace',required=True)+'<p class="caption">You will be its owner.</p><div class="actions">'+btn('Cancel',attrs='data-action="close-dialog"')+'<button class="btn primary">Create workspace</button></div></form>'
def invitation_review():
 return badge()+'<h3>Example workspace</h3><p>Invited role: Editor</p><p>Edit workflows and run reviewed tests.</p>'+note('Only accept access from a team you recognize.','shield','warn')+'<p class="caption">Your invitation reference is available in Account. It does not grant access by itself.</p><div class="actions">'+btn('Decline',attrs='data-action="decline-invite"')+btn('Accept invitation',cls='primary',attrs='data-action="accept-invite"')+'</div>'
def workspace_start():
 content=heading('Workspace · Concept preview','A place for your next connection.','Start your workspace or review an invitation from a team you recognize.')
 content+=state(1,'First visit','<div class="card"><h2>Your account is ready.</h2><p class="lead">Create a workspace or accept an invitation to begin.</p><div class="actions">'+btn('Create workspace',ico='plus',cls='primary',attrs='data-action="create-workspace"')+btn('Review invitations',ico='mail',attrs='data-action="invite-review"')+'</div><hr class="divider">'+note('Signing in does not grant access to someone else’s workspace.')+'</div>')
 content+=state(2,'Create workspace','<div class="card sample-dialog"><h2>Create workspace</h2>'+create_workspace_form()+'</div>')
 content+=state(3,'Review invitation','<div class="card sample-dialog"><h2>Review invitation</h2>'+invitation_review()+'</div>')
 page('workspace-start.html','Create or join a workspace',content,'workspace-auth/02-workspace-start-and-invitations.png','Workspace',workspace=True)
def studio():
 content='<div class="page-heading"><p class="caption">Workspace / Workflows / Technology news brief</p><div class="between"><div><h1>Private workflow studio</h1>'+badge('Private draft')+' '+badge()+'</div><div class="actions">'+btn('Save reviewed draft',ico='file',cls='primary',attrs='data-action="save-draft"')+btn('Review inputs','workspace-review.html','play')+'</div></div><p>Create and refine a workflow by connecting the right agents into a useful result.</p></div><div class="studio-layout"><section><div class="card">'+field('Workflow name','Technology news brief',name='draft-name')+'</div><section class="card section"><div class="between"><span class="caption">Read-only workflow · 3 steps</span><div class="row">'+btn('Add step',ico='plus',cls='small',attrs='data-action="add-step"')+btn('Connect prior result',ico='link',cls='small',attrs='data-action="connect-step"')+'</div></div><div class="studio-canvas"><div class="strand">'
 for title,copy,ico in [('News search','Find recent, relevant articles about the topic.','search'),('Summarize','Create clear, factual summaries from articles.','file'),('Brief','Combine into one useful brief.','file')]:
  content+='<div><button type="button" class="pearl" data-action="select-step" data-step="'+title+'" aria-label="Select '+title+'">'+icon(ico)+'</button><h3>'+title+'</h3><p>'+copy+'</p></div>'
 content+='</div></div></section>'+note('Review every agent, exact input and prior result connection before a test. Changes create a new private draft.','shield')+'</section><aside class="card"><h4>Selected step</h4><div class="row">'+pearl()+'<h3 id="selected-step">News search</h3></div><hr class="divider">'+select('Agent',['Web search agent','Summary agent','Brief agent'],'studio-agent')+select('Read-only tool',['Web search','Summarize','Prepare brief'],'studio-tool')+field('Topic','Technology news',name='studio-topic')+select('Previous results',['None','News search','Summarize'],'studio-previous')+btn('Review this change',cls='primary block',attrs='data-action="review-change"')+'</aside></div><details class="card section"><summary>Suggest a workflow</summary><p>Suggestions require review and cannot run tasks.</p>'+field('Public task objective',placeholder='Describe a public task objective',name='studio-objective')+btn('Suggest for review',attrs='data-action="suggest"')+'</details>'
 page('workspace-studio.html','Private workflow studio',content,'workspace-auth/03-private-workflow-studio.png','Workspace',workspace=True,wsactive='Workflows')
def review_steps(active=1):
 return '<div class="review-steps">'+''.join('<div>'+pearl()+'<p>'+('<strong>'+t+'</strong>' if n==active else t)+'</p></div>' for n,t in enumerate(['Draft','Review','Test','Release']))+'</div>'
def run_review():
 return '<h3>Technology news brief</h3>'+badge('Private draft')+review_steps()+'<div class="table-wrap"><table class="data-table"><thead><tr><th>Step</th><th>Information shared</th><th>Connected result</th></tr></thead><tbody><tr><td>News search</td><td>Topic: Technology news</td><td>None</td></tr><tr><td>Summarize</td><td>Selected articles</td><td>News search</td></tr><tr><td>Brief</td><td>Summary</td><td>Summarize</td></tr></tbody></table></div><div class="actions">'+note('One read-only workflow test. Review these inputs and connected results.')+'</div>'+check('I authorize these exact inputs and connected results to be shared with the selected agents for one test.','run-authorization','data-enable="run-reviewed"')+btn('Run reviewed workflow once',ico='play',cls='primary',attrs='id="run-reviewed" disabled data-action="run-reviewed"')
def release_card():
 return '<h3>Release and web app</h3><p>Create a temporary release after a successful test, then authorize an exact app origin.</p>'+check('Release this successful version for one hour.','release-consent','data-enable="create-release"')+btn('Create release',cls='primary block',attrs='id="create-release" disabled data-action="create-release"')+'<hr class="divider">'+field('Exact web app origin',typ='url',placeholder='https://your-app.example',name='app-origin')+check('Authorize this origin for one hour.','origin-consent','data-enable="authorize-origin"')+'<p class="caption">Up to 5 tasks per minute and 20 per day.</p>'+btn('Authorize web app',cls='block',attrs='id="authorize-origin" disabled data-action="authorize-origin"')+btn('Download reviewed web app',ico='download',cls='block',attrs='id="download-reviewed" disabled data-action="download"')+'<hr class="divider">'+note('Every web app run requires a fresh input review.')
def workspace_review():
 content=heading('Private workflow','Review before testing.','Inspect each input and connection before authorizing one test.')+badge()
 content+=state(1,'Review before testing','<div class="card">'+run_review()+'</div>')
 content+=state(2,'Successful test and release','<div class="grid two"><article class="card">'+badge('Test succeeded','success')+'<h2>Technology news brief</h2><p>Illustrative result · Review before release.</p>'+brief()+'</article><section class="card">'+release_card()+'</section></div>')
 page('workspace-review.html','Review, test and release',content,'workspace-auth/04-workspace-review-test-release.png','Workspace',workspace=True,wsactive='Workflows')
def roles():
 return '<div>'+''.join('<div class="setting-row"><div class="row">'+icon(i)+'<strong>'+t+'</strong></div><span class="caption">'+d+'</span></div>' for t,d,i in [('Owner','Manage workspace and access','settings'),('Editor','Edit and run reviewed tasks','file'),('Runner','Run reviewed tasks','play'),('Viewer','Read only','book')])+'</div>'
def invite_form():
 return '<form data-form="invite"><h2>Invite a member</h2><p>Ask the recipient to sign in and share their invitation reference.</p>'+field('Recipient invitation reference',placeholder='Enter invitation reference',required=True)+select('Role',['Viewer','Runner','Editor','Owner'],'member-role')+roles()+'<button class="btn primary block">Send invitation</button><p class="caption">Sending an invitation does not grant access.</p></form>'
def members():
 content=heading('Concept preview','People, with clear permissions.','Access is granted after an invitation is accepted.')+'<div class="split"><div class="stack"><section class="card"><h2>Members</h2><p>People who have access to this workspace.</p>'+''.join('<div class="history-row"><div class="row">'+pearl('small')+'<span>'+title+'</span></div>'+badge(role)+'</div>' for title,role in [('Workspace owner','Owner'),('Example editor','Editor'),('Example viewer','Viewer')])+'</section><section class="card"><h2>Role permissions</h2>'+roles()+'</section><section class="card"><h2>Pending invitations</h2><p>Invitations must be accepted before access is granted.</p><div class="history-row"><span>Example invitation · Editor</span>'+badge('Awaiting acceptance','warning')+btn('Revoke invitation',cls='small danger',attrs='data-action="revoke-invite"')+'</div></section><section class="card"><h2>Workspace settings</h2>'+btn('Rename workspace',attrs='data-action="rename-workspace"')+btn('Leave workspace',cls='danger',attrs='data-action="leave-workspace"')+'</section>'+note('Google and GitHub accounts remain separate. Matching emails do not merge accounts.')+'</div><aside class="card">'+invite_form()+'</aside></div>'
 page('workspace-members.html','People, with clear permissions',content,'workspace-auth/05-workspace-members-access.png','Workspace',workspace=True,wsactive='Members & invitations')
def provider_buttons(signup=True):
 return '<div class="stack"><button type="button" class="btn block provider-button" data-action="provider" data-provider="Google"><span class="provider-g" aria-hidden="true">G</span>'+('Continue with Google' if signup else 'Sign in with Google')+'</button><button type="button" class="btn primary block provider-button" data-action="provider" data-provider="GitHub">'+icon('github')+('Continue with GitHub' if signup else 'Sign in with GitHub')+'</button></div>'
def auth(signup):
 title='Create your account' if signup else 'Welcome back'
 story='Your next<br>connection<br>starts here.' if signup else 'Pick up your<br>next connection.'
 copy='Create an account to start a private workspace or review an invitation.' if signup else 'Your agents, your context, and the tools you trust — coming together for useful results.'
 content='<div class="auth-layout"><section class="auth-story"><p class="eyebrow">Connected intelligence</p><h1>'+story+'</h1><p class="lead">'+copy+'</p><div class="auth-strand">'+strands([('Create account','Start with a trusted provider.'),('Join a workspace','Create one or accept an invitation.'),('Review before running','Inspect each step and its input.')],large=True)+'</div></section><section class="card auth-card">'+badge('Concept preview')+'<p class="eyebrow">'+('Get started' if signup else 'Returning sign-in')+'</p><h1>'+title+'</h1><p class="lead">'+('Continue securely with a provider you trust.' if signup else 'Sign in to your workspace.')+'</p>'+provider_buttons(signup)+'<div class="auth-notes"><div class="evidence-item">'+icon('user')+'<p>'+('Your first successful sign-in creates an account.<br>Use the same provider when you return. Google and GitHub accounts stay separate.' if signup else 'Use the provider you used to create your account.')+'</p></div><div class="evidence-item">'+icon('users')+'<p>An account does not automatically grant access to a shared workspace.</p></div></div><hr class="divider"><p class="small">Review our <a href="terms.html">Terms of Service</a> and <a href="privacy.html">Privacy Policy</a>.</p><p class="small">'+('Already have an account? <a href="sign-in.html">Sign in</a>' if signup else 'New here? <a href="sign-up.html">Create an account</a>')+'</p><p class="notice">Design preview · Provider buttons do not create a real account.</p>'+btn('View workspace layout','workspace.html','arrow','small')+'</section></div>'
 if not signup:
  content+='<section class="grid two section"><div class="card"><h3>Sign-in cancelled</h3><p>Choose a provider to try again.</p>'+btn('Back to sign in','sign-in.html','back')+'</div><div class="card"><h3>Provider unavailable</h3><p>An existing account stays with its original provider.</p>'+btn('Google unavailable',attrs='disabled')+btn('Sign in with GitHub',cls='primary',attrs='data-action="provider" data-provider="GitHub"')+btn('Check availability again',attrs='data-action="availability"')+'</div></section>'
 content=content.replace('<h1>'+title+'</h1>','<h2>'+title+'</h2>')
 page('sign-up.html' if signup else 'sign-in.html',title,content,'workspace-auth/06-sign-up-google-github.png' if signup else 'workspace-auth/07-sign-in-and-recovery-states.png','Workspace',auth=True)
def signout_card():
 return '<div class="center">'+pearl('large')+'<h2>You’re signed out</h2><p>Your Agent Concierge session has ended.<br>Your Google or GitHub session is unchanged.</p><div class="actions">'+btn('Sign in again','sign-in.html','arrow','primary')+btn('Back to discovery','explore.html','back')+'</div><p class="caption">Saved workspace content is retained.</p></div>'
def account():
 content=heading('Account and sign-out · Concept preview','Your account, clearly connected.','Manage your workspace access and sign out of Agent Concierge.')
 content+=state(1,'Account menu','<div class="card account-preview"><h3>Your account</h3><p><span class="provider-g" aria-hidden="true">G</span> Signed in with Google</p><hr class="divider">'+''.join('<a class="side-item" href="'+href+'">'+icon(ico)+title+'</a>' for title,href,ico in [('Your workspaces','workspace.html','home'),('Members & invitations','workspace-members.html','users'),('Account','account.html','user')])+btn('Sign out',ico='logout',cls='block',attrs='data-action="sign-out"')+'<p class="caption">Provider example only.</p></div>')
 content+=state(2,'Unsaved changes','<div class="card sample-dialog"><h2>Leave without saving?</h2><p>Your unsaved edits will be lost when you sign out.</p><div class="actions">'+btn('Keep editing','workspace-studio.html',cls='primary')+btn('Discard edits and sign out',attrs='data-action="sign-out"')+'</div><p class="caption">Shown only when unsaved edits exist.</p></div>')
 content+=state(3,'Signed-out screen','<div class="card">'+signout_card()+'</div>')
 content+=state(4,'Sign-out not confirmed','<div class="card">'+note('Separate error state. The session may still be active. Sign-out could not be confirmed. Please try again.','info','warn')+btn('Try again',attrs='data-action="sign-out"')+'</div>')
 page('account.html','Account and sign-out',content,'workspace-auth/08-account-and-sign-out.png','Workspace',auth=True)
 page('signed-out.html','You are signed out','<section class="section narrow"><h1 class="sr-only">You are signed out</h1>'+signout_card()+'</section>','workspace-auth/08-account-and-sign-out.png','Workspace',auth=True)
def mobile_workspace():
 phones=[('Create account','<h2>Create your account</h2>'+provider_buttons()+'<p>Your first successful sign-in creates an account.</p><a href="sign-in.html">Sign in</a>'),('Your workspaces','<h2>Your workspaces</h2>'+btn('Create workspace',ico='plus',cls='primary',attrs='data-action="create-workspace"')+'<div class="card"><h3>Example workspace</h3>'+badge('Owner')+'<p>A private workspace for reviewed tasks.</p>'+btn('Open workspace','workspace.html','arrow')+'</div><h3>Invitations</h3>'+btn('Review an invitation',attrs='data-action="invite-review"')),('Review test','<h2>Technology news brief</h2>'+review_steps()+'<div class="card"><p>Topic: Technology news</p><p>3 read-only steps</p></div>'+check('I authorize these exact inputs for one test.','mobile-run','data-enable="mobile-run-button"')+btn('Run reviewed workflow once',cls='primary',attrs='disabled id="mobile-run-button" data-action="run-reviewed"')),('Signed out',signout_card())]
 content=heading('Mobile · Concept preview','Every connection, on any screen.','Responsive workspace and account surfaces.')+'<div class="phone-grid">'+''.join('<section><h3 class="center">'+title+'</h3><div class="phone">'+brand()+content+'<div class="bottom caption"><a href="terms.html">Terms of Service</a> · <a href="privacy.html">Privacy Policy</a></div></div></section>' for title,content in phones)+'</div>'
 page('mobile-workspace.html','Mobile workspace and account',content,'workspace-auth/09-mobile-workspace-and-auth.png','Workspace',auth=True)

def policy_documents():
 docs={}
 source=(ROOT.parent/'extracted_html.txt').read_text()
 for line in source.splitlines():
  if re.match(r'  "(tos|privacy|ccpa|accessibility|ai|cancellation)": \{',line):
   key,raw=line.strip().split(': ',1)
   value=json.loads(raw.rstrip(','))
   # Preserve policy prose; interactive controls are built separately for this preview.
   value['html']=''.join('<h3>'+m.group(1)+'</h3>' if m.group(1) is not None else '<p>'+m.group(2)+'</p>' for m in re.finditer(r'<h4>(.*?)</h4>|<p>(.*?)</p>',value['html'],re.S))
   docs[json.loads(key)]=value
 return docs
DOCS=policy_documents()
def policy_shell(key):
 doc=DOCS[key]
 return '<div class="policy-layout"><nav class="side-nav" aria-label="Policy documents">'+''.join('<a class="side-item" href="'+href+'.html">'+name+'</a>' for name,href in POLICIES)+'</nav><article class="policy-copy"><h2>'+doc['title']+'</h2><p class="caption">'+doc['sub']+'</p>'+doc['html']+'<p class="notice">Live service policy text · Design layout preview</p></article></div>'
def policies():
 mapping=[('terms','tos','system/02-terms-privacy-dialogs.png'),('privacy','privacy','system/02-terms-privacy-dialogs.png'),('privacy-choices','ccpa','system/03-privacy-accessibility-disclosure.png'),('accessibility','accessibility','system/03-privacy-accessibility-disclosure.png'),('disclosures','ai','system/03-privacy-accessibility-disclosure.png')]
 for filename,key,ref in mapping:
  content=heading('Service information',e(DOCS[key]['title']),e(DOCS[key]['sub']))+'<section class="card">'+policy_shell(key)+'</section>'
  if key=='ccpa':content+='<section class="card section"><h3>Your browser choice</h3>'+btn('Record preview opt-out',cls='primary',attrs='data-action="privacy-opt-out"')+'<p class="caption">This design preview does not submit a privacy request.</p></section>'
  page(filename+'.html',DOCS[key]['title'],content,ref,'Policies')
 content=heading('Separate states · Policy layers','Information, with room to read.','Terms and privacy are independent document states. Reading does not require agreement.')
 for n,key in enumerate(['tos','privacy'],1):
  content+=state(n,DOCS[key]['title'],'<div class="card sample-dialog"><div class="modal-heading"><h2>'+DOCS[key]['title']+'</h2>'+btn('Open dialog',ico='arrow',cls='small',attrs='data-action="policy" data-policy="'+key+'"')+'</div><article class="policy-copy">'+DOCS[key]['html']+'</article></div>')
 page('policy-dialogs.html','Terms and privacy layers',content,'system/02-terms-privacy-dialogs.png','System')
 content=heading('Separate states · Service choices','Clarity, privacy and choice.','Three distinct service information surfaces.')
 for n,key in enumerate(['ccpa','accessibility','ai'],1):
  content+=state(n,DOCS[key]['title'],'<div class="card sample-dialog"><article class="policy-copy"><h2>'+DOCS[key]['title']+'</h2>'+DOCS[key]['html']+'</article></div>')
 page('service-disclosures.html','Privacy, accessibility and disclosures',content,'system/03-privacy-accessibility-disclosure.png','System')

def setting(title,copy,name,checked=False,disabled=False):
 return '<div class="setting-row"><div><label for="'+name+'">'+title+'</label><p>'+copy+'</p></div><input class="switch" type="checkbox" id="'+name+'" aria-label="'+title+'"'+(' checked' if checked else '')+(' disabled' if disabled else '')+'></div>'
def cookie_settings(suffix=''):
 return '<h2>Cookie preferences</h2><p>Choose optional storage for this browser.</p>'+setting('Essential','Required for selected service functions.','essential'+suffix,True,True)+setting('Optional analytics','Optional and off unless you choose it.','analytics'+suffix)+setting('Advertising','Advertising delivery is disabled.','ads'+suffix,False,True)+'<div class="actions">'+btn('Reject non-essential',attrs='data-action="reject-cookies"')+btn('Save preferences',cls='primary',attrs='data-action="save-cookies"')+'</div>'
def cookies():
 banner='<div class="cookie-banner"><div><h3>Your privacy, your choice.</h3><p>Essential storage supports the service. Optional analytics stays off until you choose it.</p><a href="privacy.html">Read our Privacy Policy</a></div><div class="actions">'+btn('Accept optional analytics',attrs='data-action="accept-cookies"')+btn('Reject non-essential',attrs='data-action="reject-cookies"')+btn('Preferences',cls='primary',attrs='data-action="cookie-settings"')+'</div></div>'
 content=heading('Separate states · Browser preferences','A clear choice, without interruption.','Equal access to accept, reject and preference controls.')
 content+=state(1,'Cookie banner',banner)+state(2,'Preferences','<div class="card sample-dialog">'+cookie_settings()+'</div>')+state(3,'Global Privacy Control','<div class="card sample-dialog">'+note('Example state: Global Privacy Control is detected. Non-essential telemetry remains off.','shield')+'<p class="caption">A browser preference is not a permanent cross-device setting.</p></div>')
 page('cookies.html','Cookie banner and preferences',content,'system/04-cookie-banner-preferences.png','System')

def notifications():
 content=heading('Notification preferences','Updates you chose. Control you keep.','Manage task updates separately from other service records.')+'<section class="card narrow"><div class="between"><h2>Technology research</h2>'+badge('Example preview')+'</div><p>Recommendation protocol: A2A</p><p>Delivery: Manual check</p><p class="caption">Manual check is separate from browser notifications.</p>'+setting('Task updates','Example preference only.','task-enabled',True)+'<div class="actions">'+btn('Pause updates',attrs='data-action="pause-updates"')+btn('Renew request',attrs='data-action="renew-updates"')+btn('Stop updates',cls='danger',attrs='data-action="stop-updates"')+'</div><hr class="divider"><h3>Separate marketing permission</h3><p>Optional, independent and available only after destination verification. Advertising delivery is disabled.</p>'+check('Optional marketing permission','marketing','disabled')+btn('Withdraw marketing permission',attrs='data-action="withdraw-marketing"')+'<hr class="divider"><h3>Delete notification data</h3><p>This does not delete unrelated conversation records.</p>'+btn('Delete notification data',cls='danger',attrs='data-action="delete-notifications"')+'</section>'
 page('notifications.html','Notification preferences',content,'system/05-notification-preferences.png','System')
def task_updates():
 content=heading('Separate states · Optional task updates','Stay informed, by choice.','Task purpose, delivery verification and marketing permission stay separate.')
 request='<div class="card sample-dialog"><h2>Request task updates</h2><form data-form="task-updates">'+field('Task label',placeholder='A short public task label',required=True)+select('Recommendation protocol',['A2A','MCP','x402','Any'],'update-protocol')+select('Delivery method',['Manual check','Browser notifications'],'delivery-method')+check('I request updates for this task and authorize this purpose.','task-purpose','required')+'<p class="caption">Browser notifications need permission, a subscription and confirmation by clicking a delivered test notification.</p><button class="btn primary">Review request</button></form></div>'
 content+=state(1,'Choose task and purpose',request)
 content+=state(2,'Verify the destination','<div class="card sample-dialog"><h2>Confirm your browser</h2>'+review_steps()+note('Use the live service to allow notifications and click the delivered test notification. This preview does not request permission or create a subscription.','bell')+'<div class="actions">'+btn('Review browser setup',attrs='data-action="notification-setup"')+btn('Decline pending verification',cls='danger',attrs='data-action="decline-verification"')+'</div></div>')
 content+=state(3,'Separate optional permission','<div class="card sample-dialog"><h2>Marketing is a separate choice.</h2><p>Eligibility follows destination verification. Advertising delivery is disabled.</p>'+check('I separately choose optional marketing messages.','task-marketing','disabled')+'<a href="notifications.html">Manage task updates independently</a></div>')
 page('task-updates.html','Optional task updates and verification',content,'system/06-task-update-verification.png','System')
def report_content():
 return badge('Example report')+'<h3>Technology news agent</h3><p>Recorded example output · Historical evidence</p><div class="tabs"><button class="tab" data-tab="report-summary" aria-selected="true">Overview</button><button class="tab" data-tab="report-evidence" aria-selected="false">Evidence</button></div><div data-tab-panel="report-summary"><h4>Task and scope</h4><p>Find and summarize public technology information with source references.</p><h4>Example output</h4><p>A structured brief with selected findings and citations.</p><h4>Limitations</h4><p>Recorded checks do not guarantee current availability. Review the agent and inputs before use.</p></div><div data-tab-panel="report-evidence" hidden><p>Inspect the recorded task scope, source references and observed output.</p></div>'
def agent_reports():
 content=heading('Separate states · Agent and report','Inspect before you connect.','Capabilities, recorded evidence and connection information in separate surfaces.')
 content+=state(1,'Agent details','<div class="card sample-dialog details-panel">'+agent_details()+'</div>')
 content+=state(2,'Recorded report','<div class="card sample-dialog">'+report_content()+'</div>')
 page('agent-reports.html','Agent and recorded report details',content,'system/07-agent-report-details.png','System')
def workflow_review_page():
 content=heading('Review before running','One run. Clear inputs.','Confirm the selected workflow and information shared.')+'<div class="card sample-dialog">'+run_review()+'</div>'
 page('run-review.html','Workflow run review',content,'system/08-workflow-run-review.png','System')
def workflow_results():
 content=heading('Separate states · Workflow result','From selected inputs to a useful brief.','Execution and completion are independent example states.')
 content+=state(1,'Result and step details','<div class="grid two"><div class="card">'+brief()+'</div><div class="card"><h2>Run details</h2><ol class="step-list"><li>Find news</li><li>Review sources</li><li>Prepare brief</li></ol>'+badge('Illustrative result')+'</div></div>')
 content+=state(2,'Downloaded web app','<div class="card sample-dialog"><h2>Technology news brief</h2><p>Review the request before each run.</p>'+field('Your request','Find recent technology news.','textarea',name='download-task')+btn('Run workflow',ico='play',cls='primary',attrs='data-action="webapp-run"')+'<p id="webapp-status" role="status">Ready · Example preview</p></div>')
 page('workflow-results.html','Workflow results and web app',content,'system/09-workflow-result-webapp.png','System')
def import_form():
 return '<form data-form="import"><h3>Import agent information</h3><p>Paste a public Agent Card, MCP manifest or OpenAPI document. Importing does not submit it.</p>'+field('Public document',typ='textarea',placeholder='Paste a public document without secrets or personal information',name='import-document',required=True)+'<div class="actions"><button class="btn primary">Review imported fields</button>'+btn('Cancel',attrs='data-action="close-dialog"')+'</div></form>'
def registration_import():
 content=heading('Separate states · Agent registration','Import carefully. Submit deliberately.','Review public fields before a separate submission.')+state(1,'Import document','<section class="card sample-dialog">'+import_form()+'</section>')+state(2,'Review and authorize submission','<section class="card sample-dialog"><h2>Agent details</h2>'+listing_form()+'</section>')
 page('registration-import.html','Import and submission consent',content,'system/10-registration-import-consent.png','System')
def components():
 content=heading('Pearl Connection · Component library','Small details. One clear language.','Buttons, fields and states share the same visual foundation.')+'<section class="card"><div class="component-group"><h3>Buttons</h3><div class="row">'+btn('Primary action',ico='arrow',cls='primary',attrs='data-action="sample"')+btn('Secondary action',attrs='data-action="sample"')+btn('Disabled',attrs='disabled')+btn('Run example',ico='play',attrs='data-action="webapp-run"')+'</div></div><div class="component-group"><h3>Fields and selection</h3><div class="grid two">'+field('Task',placeholder='What would you like to accomplish?',name='component-task')+select('Category',['Research','News','Documentation'],'component-category')+'</div>'+protocol('component-protocol')+check('Example checkbox — not a consent setting','example-checkbox')+'</div><div class="component-group"><h3>Tabs and badges</h3><div class="row">'+badge('A2A','protocol')+badge('Draft')+badge('Example state','success')+badge('Review needed','warning')+'</div><div class="tabs"><button class="tab" data-tab="component-overview" aria-selected="true">Overview</button><button class="tab" data-tab="component-evidence" aria-selected="false">Evidence</button></div><p data-tab-panel="component-overview">An overview of the selected capability.</p><p data-tab-panel="component-evidence" hidden>Recorded evidence is separate from current availability.</p></div><div class="component-group"><h3>Pearl stepper</h3>'+strands([('Discover','Find a relevant capability.'),('Review','Inspect the evidence.'),('Connect','Review every input.')])+'</div><div class="component-group"><h3>Additional results</h3>'+btn('Load More Agents',ico='plus',cls='primary',attrs='data-action="sample-more"')+'</div></section>'
 page('components.html','Common components',content,'system/11-common-components.png','System')
def feedback():
 content=heading('Separate states · Feedback','A response to every deliberate action.','Keep inputs, make progress local and end every loading state.')
 states=[('Search action','<div class="card"><h3>Search for an agent</h3>'+field('Task',placeholder='Technology news',name='feedback-search')+btn('Search example',ico='search',cls='primary',attrs='data-action="sample-search"')+'</div>'),('No matching results','<div class="card empty">'+icon('search')+'<h2>No matching example agents</h2><p>Try a broader task or choose Any protocol.</p>'+btn('Change search','explore.html')+'</div>'),('Request timed out','<div class="card"><h3>The request took too long.</h3><p>Your input is kept. Try again when you are ready.</p>'+btn('Try again',attrs='data-action="sample-search"')+'</div>'),('Stop updates','<div class="card sample-dialog"><h2>Stop task updates?</h2><p>You can stop this request without giving a reason.</p><div class="actions">'+btn('Keep updates',attrs='data-action="sample"')+btn('Stop updates',cls='danger',attrs='data-action="stop-updates"')+'</div></div>'),('Confirmation','<div class="card">'+note('Example preference saved.','check')+btn('Show toast',attrs='data-action="toast"')+'</div>')]
 for n,(title,body) in enumerate(states,1):content+=state(n,title,body)
 page('feedback.html','Loading, errors and empty states',content,'system/12-feedback-loading-errors.png','System')
def footer_board():
 content=heading('Responsive service information','Every detail has a place.','The same eight service links, with space to read and choose.')+state(1,'Desktop footer','<div class="card">'+footer()+'</div>')+state(2,'Mobile footer','<div class="phone"><div>'+brand()+'<p>Purposeful connections.<br>Inspectable evidence.</p></div><nav class="policy-nav-links" aria-label="Mobile footer">'+''.join('<a class="link-button" href="'+key+'.html">'+name+'</a>' for name,key in POLICIES)+'</nav><p class="caption">© 2026 Agent Concierge<br>contact@agentconcierge.biz</p></div>')
 page('footer.html','Desktop and mobile footer',content,'system/01-footer-desktop-mobile.png','System')
def mobile_system():
 bodies=[('Navigation','<nav class="side-nav" aria-label="Mobile navigation">'+''.join('<a class="side-item" href="'+key+'.html">'+name+'</a>' for name,key in NAV)+'</nav>'),('Agent details','<div class="details-panel">'+agent_details()+'</div>'),('Privacy policy','<h3>Privacy Policy</h3><article class="policy-copy">'+DOCS['privacy']['html']+'</article>'),('Footer','<nav class="policy-nav-links" aria-label="Mobile service links">'+''.join('<a class="link-button" href="'+key+'.html">'+name+'</a>' for name,key in POLICIES)+'</nav>')]
 content=heading('Separate states · Mobile','A clear interface, within reach.','Navigation, details, policy reading and all footer choices.')+'<div class="phone-grid">'+''.join('<section><h3>'+title+'</h3><div class="phone">'+brand()+body+'</div></section>' for title,body in bodies)+'</div>'
 page('mobile-surfaces.html','Mobile common surfaces',content,'system/13-mobile-common-surfaces.png','System')
def dark_board():
 content=heading('Separate states · Dark theme','The same clarity, after dark.','Pearl accents, readable text and restrained contrast.')+state(1,'Footer',footer())+state(2,'Cookie preferences','<div class="card sample-dialog">'+cookie_settings('-dark')+'</div>')+state(3,'Agent details','<div class="card sample-dialog details-panel">'+agent_details()+'</div>')
 page('dark-surfaces.html','Dark theme surfaces',content,'system/14-dark-theme-surfaces.png','System',dark=True)
def contact_form():
 return '<form data-form="contact">'+select('Category',['General inquiries','Technical support','Partnership','Security and abuse','Privacy request'],'contact-category')+field('Contact email',typ='email',placeholder='Your reply address',required=True)+field('Subject',placeholder='How can we help?',required=True)+field('Message',typ='textarea',placeholder='Describe your question. Do not include credentials or sensitive information.',required=True)+'<button class="btn primary">Submit inquiry</button><p class="notice">Design preview · Nothing is sent from this form.</p></form>'
def contact():
 content=heading('Contact','Let’s make a useful connection.','Questions about the service, an agent, or a connection?')+'<div class="split"><section class="card"><h2>Contact Agent Concierge</h2>'+contact_form()+'</section><aside class="card"><h3>Official service contact</h3><a href="mailto:contact@agentconcierge.biz">contact@agentconcierge.biz</a><hr class="divider"><h3>Before you send</h3><p>Include the affected page and interaction. Avoid credentials, private destinations and unnecessary personal information.</p><a href="privacy.html">Read our Privacy Policy</a></aside></div>'+state(2,'Validation guidance','<div class="card sample-dialog"><h3>Check the required fields.</h3><p class="error-text">Add a valid reply address, subject and message before continuing.</p><p>The form keeps your input for correction.</p></div>')+state(3,'Preview confirmation','<div class="card sample-dialog">'+note('Your example inquiry has been reviewed. No inquiry was sent.','check')+'</div>')
 page('contact.html','Contact Agent Concierge',content,'system/15-contact-inquiry.png','System')
def node_inspector():
 content=heading('Separate states · Workflow properties','One node. A clear purpose.','Inspect a selected step before reviewing a new draft.')
 content+=state(1,'Node properties','<div class="split"><div class="card">'+workflow_graph()+'</div><form class="card" data-form="node"><h2>Node properties</h2>'+field('Node title','Find news',name='node-title')+select('Protocol kind',['A2A','MCP','x402'],'node-protocol')+field('Action / Tool method',placeholder='Read-only action',name='node-action')+field('Sample / Expected output',typ='textarea',placeholder='Describe the expected result',name='node-output')+'<div class="actions"><button class="btn primary">Review changes</button>'+btn('Delete node',cls='danger',attrs='data-action="delete-node"')+'</div></form></div>')
 content+=state(2,'Delete node confirmation','<div class="card sample-dialog"><h2>Delete this node?</h2><p>The selected step and its connections will be removed from this draft.</p><div class="actions">'+btn('Keep node',attrs='data-action="sample"')+btn('Delete node',cls='danger',attrs='data-action="confirm-delete-node"')+'</div></div>')
 content+=state(3,'Reset template confirmation','<div class="card sample-dialog"><h2>Reset to the default template?</h2><p>Your current unsaved draft changes will be replaced.</p><div class="actions">'+btn('Keep editing','workspace-studio.html')+btn('Reset template',cls='danger',attrs='data-action="reset-template"')+'</div></div>')
 page('node-inspector.html','Workflow node properties',content,'system/16-workflow-node-inspector.png','System')

def gallery_and_compare():
 existing=list(PAGES)
 content=heading('Pearl Connection · HTML publication','A connected design, brought to life.','Browse the published layouts and compare each one with its original design image.')+'<p class="caption">Design preview only. Search, authentication, submissions and execution use local illustrative states.</p>'
 for group in ['Pages','Workspace','System','Policies']:
  content+='<section class="section"><h2>'+group+'</h2><div class="gallery-grid">'
  for p in existing:
   if p['group']!=group:continue
   content+='<article class="card gallery-card"><a class="thumb" href="'+p['file']+'" tabindex="-1" aria-hidden="true"><img src="'+p['reference']+'" alt="" loading="lazy"></a><h3>'+e(p['title'])+'</h3><div class="actions">'+btn('Open layout',p['file'],ico='arrow',cls='primary small')+btn('Compare','compare.html?page='+p['file'],cls='small')+'</div></article>'
  content+='</div></section>'
 page('gallery.html','All Pearl Connection layouts',content,'concept/04-pearl-connection.png','Index',auth=True)
 options=''.join('<option value="'+p['file']+'">'+e(p['title'])+'</option>' for p in existing)
 content='<h1 class="compare-title">Compare the published layout.</h1><div class="compare-controls"><label for="compare-page">Compare page</label><select id="compare-page">'+options+'</select><label for="compare-width">Capture</label><select id="compare-width"><option value="1440">Desktop · 1440 px</option><option value="390">Mobile · 390 px</option></select>'+btn('Open full layout','index.html',cls='small',attrs='id="compare-open"')+'<p class="caption">The left image is a real browser capture. Reference boards may contain separate states. Open the layout to interact.</p></div><div class="comparison"><section><h2>HTML browser capture</h2><div class="reference"><img id="compare-publication" src="assets/previews/index-1440.png" alt="Published Home layout in a real browser"></div><details class="card"><summary>Interact with this layout</summary><p class="caption">This live frame adapts to its available width.</p><iframe id="compare-frame" title="Published HTML layout" src="index.html" sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-downloads"></iframe></details></section><section><h2>Design reference</h2><div class="reference"><img id="compare-reference" src="../design/revisions/2026-10-19-catalog-status/01-home-with-catalog-status.png" alt="Selected page design reference"></div></section></div>'
 page('compare.html','Compare HTML and design reference',content,'concept/04-pearl-connection.png','Index',auth=True)
 (OUT/'assets/pages.json').write_text(json.dumps(existing,indent=2))
 # External JavaScript data works from both file previews and isolated HTTP QA.
 (OUT/'assets/page-data.js').write_text('window.PEARL_PAGES = '+json.dumps(existing)+';\n')
 for p in [OUT/'compare.html']:
  p.write_text(p.read_text().replace('<script src="assets/app.js"','<script src="assets/page-data.js" defer></script><script src="assets/app.js"'))

def main():
 OUT.mkdir(exist_ok=True)
 marker='/* Shared reference interactions. */'
 application=OUT/'assets/app.js'
 application.write_text(application.read_text().partition(marker)[0].rstrip()+'\n'+marker+'\n'+(ROOT/'shared-ui.js').read_text())
 styles=OUT/'assets/styles.css'
 typography=(ROOT/'live-assets/pearl-menus.css').read_text().split('/* Explore keeps',1)[0]
 styles.write_text(styles.read_text().partition('/* Shared reference presentation. */')[0].rstrip()+'\n/* Shared reference presentation. */\n'+(ROOT/'shared-style.css').read_text()+'\n'+typography)
 (OUT/'assets/favicon.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 40"><g fill="#f8f7f3" stroke="#a48154" stroke-width="1.5"><circle cx="12" cy="25" r="10"/><circle cx="31" cy="15" r="13"/><circle cx="51" cy="25" r="10"/></g></svg>')
 home();agent_status();explore();test_page();workflows();chat();learn();listing();about()
 workspace_overview();workspace_start();studio();workspace_review();members();auth(True);auth(False);account();mobile_workspace()
 footer_board();policies();cookies();notifications();task_updates();agent_reports();workflow_review_page();workflow_results();registration_import();components();feedback();mobile_system();dark_board();contact();node_inspector()
 gallery_and_compare()
 for p in OUT.glob('*.html'):
  html=re.sub(r'<footer\b[^>]*class="site-footer"[^>]*>.*?</footer>',lambda _:footer(),p.read_text(),flags=re.S)
  html=html.replace('<link rel="stylesheet" href="assets/styles.css">','<link rel="stylesheet" href="assets/styles.css"><link rel="stylesheet" href="assets/necklace.css">')
  html=html.replace('class="tabs"','class="tabs" role="tablist"')
  html=re.sub(r'<button class="tab"([^>]*?)data-tab="([^"]+)"([^>]*?)>',lambda m:'<button class="tab" role="tab" id="tab-'+m[2]+'" aria-controls="panel-'+m[2]+'"'+m[1]+'data-tab="'+m[2]+'"'+m[3]+'>',html)
  html=re.sub(r'<(div|p) data-tab-panel="([^"]+)"',r'<\1 role="tabpanel" id="panel-\2" aria-labelledby="tab-\2" data-tab-panel="\2"',html)
  p.write_text(html.replace('><','>\n<'))
 (ROOT/'publication-manifest.json').write_text(json.dumps({'html_count':len(list(OUT.glob('*.html'))),'generated_html_count':len(PAGES),'pages':PAGES,'superseded_references':{'pages/01-home-full.png':'revisions/2026-10-19-catalog-status/01-home-with-catalog-status.png'},'scope':'Isolated HTML/CSS/JS publication with example interactions; no live API integration.'},indent=2))
 print(f'Published {len(PAGES)} standalone HTML layouts.')

if __name__=='__main__':main()
