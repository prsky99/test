"""Apply the five approved menu compositions to existing operating controls."""
from dom import Node, parse


def fragment(value):
    root = parse(value)
    return root.children[0] if len(root.children) == 1 else root


def classes(node, value):
    return value in node.attrs.get('class', '').split()


def direct(node, value):
    return next(n for n in node.children if isinstance(n, Node) and classes(n, value))


def field(control, label):
    wrapper = fragment('<div class="field"><label for="'+control.attrs['id']+'">'+label+'</label></div>')
    wrapper.append(control)
    return wrapper


def apply(tree, published_main):
    for id in ['secExplore', 'secTest', 'secWorkflows', 'secChat', 'secRegister']:
        section = tree.find(id)
        section.attrs['class'] += ' pearl-menu-page'
        heading = direct(section, 'page-heading')
        heading.attrs['class'] += ' pearl-menu-heading'

    explore = tree.find('secExplore')
    heading = direct(explore, 'page-heading')
    heading.append(fragment('<div class="pearl-search-art" aria-hidden="true"><span class="pearl"></span><span class="pearl"></span><span class="pearl"></span></div>'))
    checks = next(n for n in explore.walk() if classes(n, 'explore-checkboxes-row'))
    report = tree.find('xHasReport').parent
    report.children = [tree.find('xHasReport'), 'Recorded reports']
    tree.find('xHasReport').parent = report
    inputs = list(checks.children)
    bottom = fragment('<div class="pearl-filter-bottom"><div class="pearl-evidence-filter"><span class="field-label">Filter by evidence</span></div><div class="pearl-task-filter"><span class="field-label">Common tasks</span></div></div>')
    evidence, tasks = [n for n in bottom.children if isinstance(n, Node)]
    for item in inputs:
        evidence.append(item)
    tasks.append(tree.find('xChips'))
    checks.replace(bottom)
    tree.find('xLoadMore').attrs['class'] += ' primary'

    test = tree.find('secTest')
    recipes = tree.find('testbenchRecipesGrid').parent
    recipes.attrs['class'] = 'card pearl-example-sidebar'
    import json
    from agent_market.owned_data_agents.catalog import SPECS
    from agent_market.owned_data_agents.staging import TEST_IDS
    examples = tree.find('testbenchRecipesGrid')
    examples.attrs['aria-busy'] = 'true'
    examples.attrs['data-example-previews'] = json.dumps([
        {'title': SPECS[identity]['name'], 'description': SPECS[identity]['description']} for identity in TEST_IDS
    ])
    examples.children = []
    for identity in TEST_IDS:
        preview = fragment('<button type="button" class="side-item pearl-example-preview" disabled aria-disabled="true"></button>')
        title = Node('strong')
        title.children = [SPECS[identity]['name']]
        description = Node('span', {'class': 'pearl-example-description'})
        description.children = [SPECS[identity]['description']]
        state = Node('span', {'class': 'pearl-example-state'})
        state.children = ['Checking availability…']
        preview.append(title)
        preview.append(description)
        preview.append(state)
        examples.append(preview)
    recipes.append(fragment('<p id="pearlExampleLoadState" class="caption" role="status">Checking example availability…</p>'))
    recipes.append(fragment('<button id="pearlRetryExamples" type="button" class="btn small" hidden>Retry examples</button>'))
    request = next(n for n in direct(test, 'test-layout').walk() if n.tag == 'div' and any(isinstance(c, Node) and c.attrs.get('id') == 'tbProtocolActionBox' for c in n.children))
    request.attrs['class'] = 'card pearl-test-request'
    request.attrs.pop('style', None)
    header = fragment('<div class="pearl-selected-example"><p class="eyebrow">Selected example</p><h2 id="pearlTestExampleName">Choose an agent</h2><p id="pearlTestExampleDescription">Select an available example or choose a registered agent below.</p></div>')
    header.append(fragment('<p id="pearlTestConnectionState" class="caption" role="status" hidden></p>'))
    request.children.insert(1, header)
    header.parent = request
    # Preserve the catalog and protocol filters as an optional selection panel.
    protocol = next(n for n in request.children if isinstance(n, Node) and any(isinstance(x, Node) and classes(x, 'quick-chips') for x in n.children))
    agent = tree.find('tbAgentSelect').parent
    extra = fragment('<details class="pearl-selection-options"><summary>Choose another agent</summary></details>')
    extra.append(protocol)
    extra.append(agent)
    extra.append(tree.find('tbAgentMetaBox'))
    request.children.insert(request.children.index(header)+1, extra)
    extra.parent = request
    for id, label in [('tbA2aMessage', 'Your request'), ('tbToolSelect', 'Tool'), ('tbArgsEditor', 'Request input (JSON)')]:
        control = tree.find(id)
        search = tree.find('tbMcpControls') if id == 'tbToolSelect' else control.parent
        for n in search.walk():
            if n.tag == 'label':
                n.children = [label]
                n.attrs['for'] = id
                break
    tree.find('tbArgsEditor').attrs['spellcheck'] = 'false'
    tree.find('tbRunBtn').attrs['disabled'] = None
    tools = tree.find('tbToolSelect')
    tools.attrs['disabled'] = None
    tools.children = [fragment('<option value="">Choose an agent to load tools</option>')]
    request_header = tree.find('tbResetBtn').parent
    request_header.attrs['class'] = 'pearl-request-heading'
    for id in ['tbA2aControls', 'tbArgsStudio']:
        parent = tree.find(id)
        last = [n for n in parent.children if isinstance(n, Node)][-1]
        if last.tag == 'div' and last is not tree.find('tbArgsEditor'):
            details = fragment('<details class="pearl-input-presets"><summary>Request presets</summary></details>')
            last.replace(details)
            details.append(last)
    tree.find('tbCustomToolInput').attrs['placeholder'] = 'Custom tool name'
    runbar = tree.find('tbRunBtn').parent
    runbar.attrs['class'] = 'pearl-test-runbar'
    runbar.attrs.pop('style', None)
    output = tree.find('tbKpiBar').parent
    output.attrs['class'] = 'card pearl-test-result'
    output.attrs.pop('style', None)
    toolbar = next(n for n in output.children if isinstance(n, Node))
    tabs = next(n for n in toolbar.children if isinstance(n, Node) and classes(n, 'sub-pills'))
    tabs.remove()
    output.children.insert(output.children.index(tree.find('tbKpiBar'))+1, tabs)
    tabs.parent = output
    names = {'formatted': 'Summary', 'raw': 'Request & response', 'telemetry': 'Connection'}
    for button in tabs.walk():
        if button.tag == 'button':
            button.children = [names.get(button.attrs.get('data-subtab'), 'Summary')]
    tree.find('tbOutputPre').children = ['Your result will appear here after a test. Review the selected agent and request, then choose Run Test.']
    for n in test.walk():
        if n.tag == 'p' and ''.join(x for x in n.children if isinstance(x,str)).startswith('Recorded results are illustrative'):
            n.children = ['Results reflect the selected agent and its availability at the time of the test.']

    workflows = tree.find('secWorkflows')
    canvas = tree.find('frontWfCanvasView')
    actionbar = next(n for n in canvas.children if isinstance(n, Node) and classes(n, 'card'))
    actionbar.attrs['class'] = 'pearl-workflow-actions'
    actionbar.attrs.pop('style', None)
    active = tree.find('frontWfActiveName')
    active.tag = 'h2'
    identity = fragment('<div class="pearl-workflow-identity"></div>')
    identity.append(active)
    identity.append(fragment('<p id="pearlWorkflowDescription">Review the selected connection and its inputs.</p>'))
    identity.append(tree.find('frontSelectionContext'))
    canvas.children.insert(0, identity)
    identity.parent = canvas
    for n in actionbar.walk():
        for i, value in enumerate(n.children):
            if isinstance(value, str):
                n.children[i] = value.replace('Active Workflow:', '')
    actionbar.append(tree.find('frontWfNodeCountChip'))
    workflows.append(fragment('<section class="card pearl-workflow-review"><div><h3>Review inputs</h3><p>Inspect the published inputs before running. Canvas edits do not change the published run.</p></div><div id="pearlWorkflowInputSteps" class="pearl-workflow-input-steps"></div></section>'))
    tree.find('pearlWorkflowInputSteps').append(fragment('<p class="caption pearl-workflow-loading" role="status">Loading workflow steps…</p>'))
    workflows.append(fragment('<dialog id="pearlWorkflowInputDialog" aria-labelledby="pearlWorkflowInputTitle" class="pearl-input-dialog"><div class="between"><h2 id="pearlWorkflowInputTitle">Published input</h2><button type="button" id="pearlCloseWorkflowInput" class="btn">Close</button></div><p>This run uses the selected published template. Review the task and connection before continuing.</p><div id="pearlWorkflowInputContent"></div></dialog>'))
    workflows.append(fragment('<div class="pearl-workflow-run-grid"><section class="card"><span class="badge" id="pearlWorkflowResultState">No run yet</span><h3>Workflow result</h3><div id="pearlWorkflowResult"><p>Run the selected workflow to inspect its actual output. Results and source links will appear when available.</p></div></section><section class="card"><h3>Run details</h3><p>The steps in your current connection.</p><ol class="step-list" id="pearlWorkflowRunDetails"></ol></section></div>'))
    toolbar = direct(workflows, 'pearl-workflow-toolbar')
    for n in list(toolbar.children):
        if isinstance(n, Node) and n.tag == 'div' and not any(x.tag == 'button' for x in n.walk()):
            n.remove()

    chat = tree.find('secChat')
    direct(chat, 'chat-signals').remove()
    choice = next(n for n in chat.walk() if classes(n, 'chat-protocol-choice'))
    choice.attrs['class'] += ' pearl-chat-protocol'
    layout = direct(chat, 'chat-layout')
    choice.remove()
    chat.children.insert(chat.children.index(layout), choice)
    choice.parent = chat
    for n in choice.walk():
        if n.tag == 'label':
            n.children = ['Connection protocol']
            n.attrs['for'] = 'chatProtocol'
    conversation = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'section')
    conversation.attrs['class'] += ' pearl-conversation'
    title = fragment('<div class="pearl-conversation-title"><h2>Your conversation</h2><span class="caption">Up to three relevant recommendations per task</span></div>')
    conversation.children.insert(0, title)
    title.parent = conversation
    tree.find('chatForm').attrs['class'] += ' pearl-inline-composer'
    tree.find('chatInput').attrs.update({'placeholder': 'What do you want to accomplish?', 'rows': '2'})
    aside = next(n for n in layout.children if isinstance(n, Node) and n.tag == 'aside')
    aside.attrs['id'] = 'pearlChatAgentDetails'
    aside.children = []
    aside.append(fragment('<h3>Agent details</h3><div id="pearlChatSelectedAgent"><span class="icon-disc aqua" aria-hidden="true">'+icon('file')+'</span><h4>Your next connection</h4><p>Send a task to inspect a recommendation and its recorded evidence here.</p></div><hr class="divider"><h4>How agents are selected</h4><p>Recent successful verification, recent activity, then quality grade.</p><p class="caption">Connection checks and task execution checks have different scopes.</p>'))

    registration = tree.find('secRegister')
    direct(registration, 'pearl-registration-intro').remove()
    layout = direct(registration, 'pearl-registration-layout')
    formcard = next(n for n in layout.children if isinstance(n, Node) and classes(n, 'card'))
    formcard.attrs['class'] += ' pearl-registration-form'
    form = tree.find('regForm')
    blueprint = tree.find('regBlueprintChips').parent
    importer = tree.find('regAutoUrl').parent.parent
    optional = fragment('<details class="pearl-registration-import"><summary>Import agent information</summary><p>Use a public endpoint or an agent card to fill in the fields. Review the imported information before submitting.</p></details>')
    optional.append(importer)
    optional.append(blueprint)
    heading = next(n for n in formcard.children if isinstance(n, Node) and n.tag == 'h2')
    heading.children = ['Agent details']
    intro = fragment('<p>Provide information about your agent so it can be reviewed and discovered.</p>')
    intro.parent = formcard
    formcard.children.insert(formcard.children.index(heading)+1, intro)
    controls = {id: tree.find(id) for id in ['regName','regKind','regUrl','regCategory','regDesc']}
    xfields = tree.find('regX402Fields')
    banner = tree.find('regBanner')
    preview = tree.find('regLivePreviewCard')
    consent = tree.find('regTermsConsent').parent.parent
    for n in consent.walk():
        for i, value in enumerate(n.children):
            if isinstance(value, str):
                n.children[i] = value.replace(' (Enforceable electronic contracting).', '').replace('(Enforceable electronic contracting).', '')
    actions = tree.find('regSubmitBtn').parent
    for n in [*controls.values(), xfields, banner, preview, consent, actions]:
        n.remove()
    form.children = []
    for id, label in [('regName','Agent name'),('regKind','Protocol'),('regUrl','Public endpoint'),('regCategory','Category'),('regDesc','Description')]:
        control = controls[id]
        control.attrs.pop('style', None)
        control.attrs['required'] = None
        form.append(field(control, label))
    controls['regName'].attrs['placeholder'] = 'Your agent name'
    controls['regUrl'].attrs['placeholder'] = 'https://your-agent.example/a2a'
    controls['regDesc'].attrs['placeholder'] = 'Describe what your agent can do.'
    form.append(xfields)
    form.append(optional)
    preview_details = fragment('<details class="pearl-listing-preview"><summary>Preview listing</summary></details>')
    preview_details.append(preview)
    preview.find('regPrevGrade').attrs['hidden'] = None
    form.append(preview_details)
    form.append(banner)
    form.append(fragment('<label class="check pearl-listing-authority"><input id="pearlRegAuthority" type="checkbox" required>I am authorized to submit this public endpoint.</label>'))
    form.append(consent)
    form.append(actions)
    actions.attrs['class'] = 'pearl-registration-actions'
    actions.attrs.pop('style', None)
    tree.find('regSubmitBtn').attrs['type'] = 'button'
    tree.find('regSubmitBtn').children = [fragment(icon('arrow')), 'Submit for review']
    oldaside = next(n for n in layout.children if isinstance(n, Node) and n is not formcard)
    recent = tree.find('regRecentCard')
    recent.remove()
    sidebar = next(n for n in direct(published_main('list-agent.html'), 'split').children if isinstance(n, Node) and n.tag == 'aside')
    oldaside.replace(sidebar)
    registration.append(recent)
    registration.append(next(n for n in published_main('list-agent.html').children if isinstance(n, Node) and classes(n, 'two')))


def icon(name):
    paths = {'file':'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M8 13h8 M8 17h5',
             'arrow':'M5 12h14 M12 5l7 7-7 7'}
    return '<svg class="icon lucide" viewBox="0 0 24 24" aria-hidden="true"><path d="'+paths[name]+'"></path></svg>'
