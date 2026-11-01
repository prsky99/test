"""Place operating controls inside the approved published page compositions."""
from dom import Node, parse
from html import unescape


def fragment(value):
    nodes = parse(value)
    return nodes.children[0] if len(nodes.children) == 1 else nodes


def has_class(node, value):
    return value in node.attrs.get('class', '').split()


def child(node, value):
    return next(n for n in node.children if isinstance(n, Node) and has_class(n, value))


def move_children(source, target):
    for item in list(source.children):
        target.append(item)


def adopt_heading(section, published):
    heading = child(published, 'page-heading')
    previous = next((n for n in section.children if isinstance(n, Node) and has_class(n, 'page-heading')), None)
    if previous:
        previous.replace(heading)
    else:
        heading.remove()
        heading.parent = section
        section.children.insert(0, heading)


def compose(tree, published_main):
    """Retain runtime IDs, delegated actions, forms, evidence and permission gates."""
    explore = tree.find('secExplore')
    published = published_main('explore.html')
    adopt_heading(explore, published)
    search, results = [n for n in explore.children if isinstance(n, Node) and has_class(n, 'card')]
    search.attrs['class'] = 'card pearl-search-panel'
    for id, label in [('xQ', 'Search for an agent or task'), ('xKind', 'Protocol'), ('xCategory', 'Category')]:
        control = tree.find(id)
        field = fragment('<div class="field"></div>')
        control.replace(field)
        field.append(fragment('<label for="'+id+'">'+label+'</label>'))
        field.append(control)
    for node in search.walk():
        for index,value in enumerate(node.children):
            if isinstance(value,str):node.children[index]=value.replace('Zero Account','No account required').replace('Test Report','Recorded reports')
    layout = child(published, 'results-layout')
    target = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'section')
    target.children = []
    results.attrs['class'] = 'pearl-search-results'
    target.append(results)
    aside = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'aside')
    aside.attrs['id'] = 'pearlAgentPreview'
    aside.children = []
    aside.append(fragment('<span class="badge">Agent details</span><h3>Select an agent</h3><p>Choose a result to inspect its capabilities, public connection details and recorded evidence.</p><p class="caption">Recorded checks describe past observations. Availability can change.</p>'))
    explore.append(layout)
    explore.append(child(published, 'section'))

    test = tree.find('secTest')
    published = published_main('test.html')
    adopt_heading(test, published)
    strand = child(published, 'strand')
    test.append(strand)
    recipes = tree.find('testbenchRecipesGrid').parent
    next(n for n in recipes.walk() if n.tag=='p').children=['Choose an example, then review its request before running.']
    studio = child(test, 'testbench-studio-grid')
    inputs, output = [n for n in studio.children if isinstance(n, Node) and has_class(n, 'card')]
    layout = child(published, 'test-layout')
    left = child(layout, 'test-input')
    left.children = []
    left.append(recipes)
    left.append(inputs)
    sample_output = next(n for n in layout.children if isinstance(n, Node) and n.attrs.get('id') == 'test-result')
    sample_output.replace(output)
    test.append(layout)
    studio.remove()
    # Keep the session history after the input/result composition.
    history = tree.find('tbHistoryTable')
    while history.parent is not test:
        history = history.parent
    history.remove()
    test.append(child(published, 'section'))
    test.append(history)
    banner = next(n for n in test.children if isinstance(n, Node) and has_class(n, 'banner-notice'))
    banner.remove()
    headings={
        'Live Agent Examples':'Examples',
        'Target Endpoint & Parameters':'Agent and request',
        'Target Endpoint &amp; Parameters':'Agent and request',
        'Execution Inspector & Wire Analyzer':'Test result',
        'Execution Inspector &amp; Wire Analyzer':'Test result',
        'Recent Test Session History':'Recent tests',
        'INVOCATION ARGUMENTS (JSON)':'Request input (JSON)',
        'SELECT TARGET AGENT':'Selected agent',
        'PROTOCOL FILTER':'Protocol',
    }
    for node in test.walk():
        joined=unescape(''.join(value for value in node.children if isinstance(value,str))).strip()
        if joined in headings:
            node.children=[value for value in node.children if isinstance(value,Node)]+[headings[joined]]
        for index,value in enumerate(node.children):
            if isinstance(value,str):
                for before,after in headings.items():value=value.replace(before,after)
                node.children[index]=value
    output=tree.find('tbOutputPre')
    output.tag='div'
    output.attrs['class']='pearl-test-output'

    workflows = tree.find('secWorkflows')
    published = published_main('workflows.html')
    adopt_heading(workflows, published)
    layout = child(published, 'workflow-layout')
    aside = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'aside')
    aside.children = []
    aside.attrs['id'] = 'pearlWorkflowTemplates'
    # Nested inside the workflows region, a complementary landmark is not top level; an aside may
    # take the region role (ARIA in HTML), which keeps the element later build steps look for.
    aside.attrs['role'] = 'region'
    aside.attrs['aria-label'] = 'Workflow templates'
    aside.append(fragment('<h3>Workflow templates</h3><p class="small">Choose a published connection, then review its current inputs and steps.</p><div id="pearlWorkflowChoices" class="side-nav" aria-label="Published workflows"><p class="caption">Loading available workflows…</p></div>'))
    canvas = tree.find('frontWfCanvasView')
    target = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'section')
    target.children = []
    target.append(canvas)
    workflows.append(layout)
    # The full template search remains available below the primary composition.
    hub = tree.find('frontWfTemplatesView')
    workflows.append(hub)
    toolbar = next(n for n in workflows.children if isinstance(n, Node) and any(x.attrs.get('id') == 'btnFrontWfViewCanvas' for x in n.walk()))
    toolbar.attrs['class'] = 'pearl-workflow-toolbar'
    for n in canvas.walk():
        if has_class(n, 'ok-badge') and any('100% Free Agents' in str(c) for c in n.children):
            n.remove()

    chat = tree.find('secChat')
    published = published_main('chat.html')
    heading = child(published, 'page-heading')
    original_heading = child(chat, 'chat-heading')
    original_heading.replace(heading)
    layout = child(published, 'chat-layout')
    conversation = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'section')
    conversation.children = []
    conversation.append(tree.find('chatMessages'))
    conversation.append(tree.find('chatForm'))
    aside = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'aside')
    aside.children = []
    aside.append(fragment('<span class="pearl" aria-hidden="true"></span><h3>One purposeful connection.</h3><p>Describe what you want to accomplish. Compare up to three relevant recommendations and the evidence behind it.</p><hr class="divider"><h4>How agents are selected</h4><p>Recent successful verification, recent activity, then quality grade.</p><h4>Your protocol, your choice</h4><p>A2A is the default. Choose MCP, x402 or Any to refine your request.</p><p class="caption">Connection and task execution checks have different scopes.</p>'))
    chat.append(layout)
    disclosure = child(chat, 'chat-disclosure')
    disclosure.remove()
    chat.append(disclosure)

    # Keep runtime targets private to the presentation; the published guide is
    # the sole visible Learn interface.
    learn = tree.find('secLearn')
    guide = fragment('<div id="retainedGuideTargets" hidden aria-hidden="true"></div>')
    for id in ['learnProtoCards', 'learnSubPills', 'learnBody']:
        guide.append(tree.find(id))
    move_children(published_main('learn.html'), learn)
    learn.append(guide)
    about = tree.find('secAbout')
    about.attrs['class'] = ' '.join(c for c in about.attrs.get('class','').split() if c != 'about-page')
    for n in list(about.children):
        if isinstance(n, Node) and n.tag != 'meta':
            n.remove()
    move_children(published_main('about.html'), about)

    registration = tree.find('secRegister')
    published = published_main('list-agent.html')
    adopt_heading(registration, published)
    strand = child(published, 'strand')
    heading = child(registration, 'page-heading')
    strand.remove()
    strand.parent = registration
    registration.children.insert(registration.children.index(heading)+1, strand)
    layout = child(registration, 'grid')
    layout.attrs['class'] = 'split section pearl-registration-layout'
    intro = next(n for n in registration.children if isinstance(n, Node) and has_class(n, 'card'))
    intro.attrs['class'] = 'pearl-registration-intro'


def compose_footer(tree, published):
    old = next(n for n in tree.walk() if n.tag=='footer')
    replacement = next(n for n in published.walk() if n.tag=='footer')
    mapping={'terms':'tos','privacy':'privacy','privacy-choices':'ccpa','accessibility':'accessibility','disclosures':'ai','notifications':'cancellation','contact':'contact'}
    buttons={n.attrs.get('data-doc'):n for n in old.walk() if n.tag=='button' and n.attrs.get('data-doc')}
    cookie=next(n for n in old.walk() if n.tag=='button' and 'Cookie Preferences' in ''.join(c for c in n.children if isinstance(c,str)))
    for link in list(replacement.walk()):
        key=link.attrs.get('data-footer-key')
        if not key:continue
        button=cookie if key=='cookies' else buttons[mapping[key]]
        button.children=[]
        for item in list(link.children):button.append(item)
        button.attrs.update({'class':'footer-link-btn pf-link','data-footer-key':key,'data-footer-order':link.attrs['data-footer-order']})
        button.tag='a'
        button.attrs.pop('type',None)
        button.attrs.pop('data-ac-click',None)
        button.attrs['href']='/#'+('cookie-preferences' if key=='cookies' else mapping[key])
        link.replace(button)
    for n in replacement.walk():
        if n.attrs.get('href')=='index.html':n.attrs['href']='#overview'
    old.replace(replacement)
    labels={'tos':'Terms','privacy':'Privacy','ccpa':'Privacy choices','accessibility':'Accessibility','ai':'Service disclosure','cancellation':'Notifications','contact':'Contact'}
    inverse={value:key for key,value in mapping.items()}
    tabs=tree.find('legalModalTabs')
    tabs.attrs['aria-orientation']='vertical'
    for button in tabs.walk():
        doc=button.attrs.get('data-doc')
        if doc not in labels:continue
        key=inverse[doc]
        source=next(n for n in replacement.walk() if n.attrs.get('data-footer-key')==key)
        icon=next(n for n in source.walk() if n.tag=='svg')
        button.children=[]
        button.append(parse(icon.render()))
        button.append(fragment('<span>'+labels[doc]+'</span>'))
        button.attrs.update({'id':'policy-tab-'+doc,'role':'tab','aria-controls':'legalModalBody','aria-selected':str(doc=='tos').lower(),'tabindex':'0' if doc=='tos' else '-1'})
    tree.find('legalModalBody').attrs.update({'role':'tabpanel','tabindex':'0'})
