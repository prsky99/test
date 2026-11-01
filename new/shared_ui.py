"""Shared footer from the approved desktop/mobile information design."""
from html import escape


POLICIES = [
    ('Terms of Service','terms','file'),
    ('Privacy Policy','privacy','lock'),
    ('Cookie Preferences','cookies','settings'),
    ('Do Not Sell or Share My Personal Info','privacy-choices','shield'),
    ('Accessibility Statement','accessibility','user'),
    ('AI System Disclosures','disclosures','settings'),
    ('Notification Preferences','notifications','bell'),
    ('Contact','contact','mail'),
]


def footer(brand, icon):
    groups = [('Policies','file',[0,1,2,5]),('Your choices','settings',[3,6]),('Support','chat',[4,7])]
    columns = []
    for title, glyph, indices in groups:
        links = []
        for index in indices:
            name, page, symbol = POLICIES[index]
            links.append('<a class="pf-link" data-footer-key="'+page+'" data-footer-order="'+str(index)+'" href="'+page+'.html"><span class="pf-link-icon">'+icon(symbol)+'</span><span class="pf-link-label">'+escape(name)+'</span>'+icon('chevron')+'</a>')
        columns.append('<nav class="pf-group" aria-label="'+title+'"><h3>'+icon(glyph)+'<span>'+title+'</span></h3>'+''.join(links)+'</nav>')
    return '<footer class="pearl-footer"><div class="pf-shell"><div class="pf-strand" aria-hidden="true"><span class="pearl"></span><span class="pearl"></span></div><h2 class="pf-mobile-title">Help &amp; information</h2><div class="pf-grid"><div class="pf-brand">'+brand()+'<p class="pf-tagline">Purposeful connections. Inspectable evidence.</p><p>Agent Concierge helps you discover capable AI agents and connect them into purposeful workflows.</p></div>'+''.join(columns)+'</div><div class="pf-bottom"><span>© 2026 Agent Concierge.</span><a class="pf-email" href="mailto:contact@agentconcierge.biz">'+icon('mail')+'contact@agentconcierge.biz</a></div></div></footer>'
