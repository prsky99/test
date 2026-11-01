"""Arrange operating menus around real tasks and realistic catalog volume."""
from dom import Node
from menu_presentation import fragment, direct, classes


def insert_before(node, other):
    parent = other.parent
    node.remove()
    parent.children.insert(parent.children.index(other), node)
    node.parent = parent


def apply(tree):
    band=next(n for n in tree.find('secOverview').walk()if classes(n,'catalog-band'))
    band.append(fragment('<p id="uxHomeSnapshotState" class="caption" role="status">Refreshing catalog…</p>'))
    band.append(fragment('<details id="uxCatalogHelp" class="context-help"><summary>About these numbers</summary><div class="context-help-body" id="uxCatalogDetails"><p id="uxCatalogScope">Catalog totals include A2A, MCP and x402 listings, including unavailable entries. Explore defaults to reachable A2A and MCP matches and applies safety filters.</p></div></details>'))
    status=tree.find('connection-status')
    tree.find('snapshot-feedback').attrs['hidden']=None
    if status:
        status.append(fragment('<details class="context-help"><summary>What do the statuses mean?</summary><div class="context-help-body"><p id="uxConnectionMeaning">Healthy and Reachable describe connection responses, not completed tasks. Unknown also includes retired or unclassified listings. Execution checks count recorded attempts in their stated time window.</p></div></details>'))
    hero=next(n for n in tree.find('secOverview').walk()if classes(n,'catalog-hero'))
    for link in hero.walk():
        if link.tag=='a'and link.attrs.get('href')=='#explore':
            link.children=[n for n in link.children if isinstance(n,Node)]+['Explore agents']
    examples=[n for n in tree.find('secOverview').walk()if classes(n,'example-card')]
    for card,title,description in zip(examples,['Technology news','Racket comparison research','Camera documentation'],['Read recent technology news with source links.','Find published racket records and source links.','Search official camera permission guidance.']):
        next(n for n in card.walk()if n.tag=='h3').children=[title]
        next(n for n in card.children if isinstance(n,Node)and n.tag=='p').children=[description]
    for id in ['secExplore','secTest','secWorkflows','secChat','secRegister']:
        section = tree.find(id)
        section.attrs['class'] += ' ux-workspace-page'
        heading = direct(section, 'page-heading')
        heading.attrs['class'] += ' ux-task-heading'

    explore = tree.find('secExplore')
    layout = direct(explore, 'results-layout')
    layout.attrs['class'] += ' ux-explore-results'
    tree.find('pearlAgentPreview').attrs['hidden'] = None
    title = tree.find('xTitle')
    toolbar = fragment('<div class="ux-results-toolbar"><div class="ux-results-heading"></div><div class="ux-view-switch" role="group" aria-label="Result layout"><button type="button" data-ux-view="cards" aria-pressed="true">Cards</button><button type="button" data-ux-view="list" aria-pressed="false">List</button></div></div>')
    title.replace(toolbar)
    next(n for n in toolbar.children if isinstance(n,Node)).append(title)
    tree.find('xResults').attrs['data-layout'] = 'cards'
    search = tree.find('xQ')
    search.attrs['placeholder'] = 'Search agents, capabilities or tasks'
    toolbar.append(fragment('<button type="button" class="btn ux-clear-search" id="uxClearSearch">Clear search and filters</button>'))
    layout.parent.children.insert(layout.parent.children.index(layout),fragment('<p id="uxExploreStatus" class="caption" role="status" aria-live="polite"></p>'))
    tree.find('uxExploreStatus').parent=explore

    test = tree.find('secTest')
    layout = direct(test, 'test-layout')
    layout.attrs['class'] += ' ux-test-layout'
    inputs = direct(layout, 'test-input')
    recipes = tree.find('testbenchRecipesGrid').parent
    recipes.attrs['class'] += ' ux-example-picker'
    insert_before(recipes, layout)
    for strand in [n for n in test.children if isinstance(n,Node) and classes(n,'strand')]:
        strand.remove()
    request = direct(inputs, 'pearl-test-request')
    editor = fragment('<div class="ux-test-editors"></div>')
    position = tree.find('tbProtocolActionBox')
    position.replace(editor)
    editor.append(position)
    editor.append(tree.find('tbArgsStudio'))
    args_studio=tree.find('tbArgsStudio')
    raw=fragment('<details id="uxRawArgs" class="ux-raw-args"><summary>Advanced: edit request JSON</summary></details>')
    for n in list(args_studio.children):
        raw.append(n)
    args_studio.append(fragment('<div id="uxRequestFields" class="ux-request-fields"></div>'))
    args_studio.append(raw)
    extra=next(n for n in test.walk()if classes(n,'pearl-selection-options'))
    extra.attrs['class']+=' ux-agent-chooser'
    tree.find('tbAgentSearch').attrs['placeholder']='Search registered agents by name or capability'
    extra.append(fragment('<p id="uxAgentSearchStatus" class="caption" role="status">Search the registered catalog, or select a format demo. Changing filters does not change your current request.</p>'))
    inputs.attrs['class'] += ' ux-test-input'
    result = direct(layout, 'pearl-test-result')
    result.attrs.update({'id':'uxTestResultPanel','class':result.attrs['class']+' ux-result-panel','data-expanded':'false'})
    result_controls = fragment('<div class="ux-result-controls"><p id="uxTestResultHint" class="caption" role="status">No test run yet. Results appear here after you run a test.</p><button type="button" class="btn" id="uxToggleTestResult" aria-expanded="false" aria-controls="uxTestResultBody">Show result</button></div>')
    result.append(result_controls)
    body = fragment('<div id="uxTestResultBody" class="ux-result-body" hidden></div>')
    children = [n for n in result.children if isinstance(n,Node)]
    for n in children[1:]:
        if n is not result_controls:
            body.append(n)
    result.append(body)
    advanced = fragment('<details class="ux-test-options"><summary>Advanced options</summary></details>')
    advanced.append(tree.find('tbCustomToolInput'))
    timeout = tree.find('tbTimeoutSelect').parent
    advanced.append(timeout)
    request.append(advanced)
    runbar = tree.find('tbRunBtn').parent
    actions = fragment('<div class="ux-test-primary"></div>')
    actions.append(tree.find('tbRunBtn'))
    actions.append(tree.find('tbResetBtn'))
    direct(request,'pearl-selected-example').append(actions)
    direct(request,'pearl-selected-example').append(fragment('<p id="uxSelectedConnection" class="caption" aria-live="polite"></p>'))
    runbar.remove()
    history = tree.find('tbHistoryTable')
    while history.parent is not test:
        history = history.parent
    fold = fragment('<details class="ux-history"><summary>Recent tests and export</summary></details>')
    history.replace(fold)
    fold.append(history)
    help_section = direct(test,'section')
    help_fold = fragment('<details class="ux-help"><summary>What does a test check?</summary></details>')
    help_section.replace(help_fold)
    help_fold.append(help_section)

    workflow = tree.find('secWorkflows')
    layout = direct(workflow, 'workflow-layout')
    layout.attrs['class'] += ' ux-workflow-layout'
    templates = tree.find('pearlWorkflowTemplates')
    templates.attrs['class'] += ' ux-template-picker'
    canvas = tree.find('frontWfCanvasView')
    graph = tree.find('frontWfCanvasContainer')
    graph_fold = fragment('<details class="ux-canvas-editor"><summary>Advanced: inspect and edit the canvas</summary><p class="caption">Canvas edits stay in your draft. Run Workflow uses the selected published template.</p></details>')
    graph.replace(graph_fold)
    graph_fold.append(graph)
    review = direct(workflow,'pearl-workflow-review')
    review.attrs['class'] += ' ux-workflow-steps'
    for node in review.walk():
        if node.tag == 'h3':
            node.children = ['Workflow steps']
        if node.tag == 'p' and not classes(node, 'pearl-workflow-loading'):
            node.children = ['Review each published input before running.']
    insert_before(review, graph_fold)
    results = direct(workflow,'pearl-workflow-run-grid')
    results.attrs['class'] = 'ux-workflow-results'
    result = next(n for n in results.children if isinstance(n,Node))
    result.attrs.update({'id':'uxWorkflowResultPanel','class':result.attrs['class']+' ux-result-panel','data-expanded':'false'})
    old_details = tree.find('pearlWorkflowRunDetails').parent
    old_details.attrs['hidden'] = None
    result.append(fragment('<button id="uxFullRunDetails" type="button" class="btn" hidden>Open full run details</button>'))
    insert_before(results, graph_fold)
    canvas.append(tree.find('frontWfSelectedTemplate'))
    tree.find('btnFrontStopWorkflow').attrs['aria-label'] = 'Stop current workflow run'
    toolbar = direct(workflow,'pearl-workflow-toolbar')
    insert_before(toolbar, layout)
    tree.find('btnFrontWfViewCanvas').children=['Selected workflow']
    tree.find('btnFrontWfViewTemplates').children=['Browse templates']
    tree.find('btnFrontResetCanvas').attrs['aria-label']='Reset to the default technology news workflow'

    chat = tree.find('secChat')
    layout = direct(chat,'chat-layout')
    layout.attrs['class'] += ' ux-chat-layout'
    tree.find('pearlChatAgentDetails').attrs['hidden'] = None
    welcome = next(n for n in tree.find('chatMessages').walk() if classes(n,'chat-welcome'))
    welcome.append(fragment('<div class="ux-chat-starters" role="group" aria-label="Example tasks"><button type="button" data-ux-task="Search research papers with source links.">Research with sources</button><button type="button" data-ux-task="Find an agent to search official documentation.">Search documentation</button><button type="button" data-ux-task="Find a weather forecast agent.">Weather forecast</button></div>'))
    tree.find('chatInput').attrs['rows'] = '2'

    registration = tree.find('secRegister')
    layout = direct(registration,'pearl-registration-layout')
    layout.attrs['class'] += ' ux-registration-layout'
    aside = next(n for n in layout.children if isinstance(n,Node) and n.tag=='aside')
    help_fold = fragment('<details class="ux-help ux-registration-help"><summary>Submission guidelines</summary></details>')
    aside.replace(help_fold)
    help_fold.append(aside)
    form = tree.find('regForm')
    endpoint = tree.find('regUrl').parent
    endpoint.remove()
    form.children.insert(0,endpoint)
    endpoint.parent = form
    endpoint.attrs['class'] += ' ux-endpoint-field'
    endpoint.append(fragment('<button id="uxInspectEndpoint" type="button" class="btn">Check and autofill</button><p class="caption">Use a public endpoint. Check its information, or enter the details below.</p>'))
    tree.find('regName').parent.attrs['class'] += ' ux-registration-name'
    tree.find('regCategory').parent.attrs['class'] += ' ux-registration-category'
    insert_before(tree.find('regCategory').parent, tree.find('regKind').parent)
    for section in [n for n in registration.children if isinstance(n,Node) and classes(n,'two')]:
        help_fold.append(section)
    for strand in [n for n in registration.children if isinstance(n,Node) and classes(n,'strand')]:
        strand.remove()
