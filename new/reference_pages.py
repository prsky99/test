"""Reference-led compositions with accessible text and reusable pearl artwork."""


def about(icon, pearl, btn):
    positions = [(451, 16, 16), (419, 20, 21), (385, 27, 25), (347, 39, 29),
                 (308, 56, 34), (269, 80, 42), (235, 112, 52), (227, 153, 65),
                 (273, 197, 83), (365, 237, 102), (487, 274, 112), (628, 307, 125)]
    points = [(x,y) for x,y,_ in positions]
    curve = 'M '+str(points[0][0])+' '+str(points[0][1])
    for i in range(len(points)-1):
        a,b,c,d = points[max(0,i-1)],points[i],points[i+1],points[min(len(points)-1,i+2)]
        curve += ' C '+' '.join(str(round(v,3)) for v in (b[0]+(c[0]-a[0])/6,b[1]+(c[1]-a[1])/6,c[0]-(d[0]-b[0])/6,c[1]-(d[1]-b[1])/6,c[0],c[1]))
    cord = '<path d="'+curve+'" fill="none" stroke="#b49061" stroke-width="3"/>'
    beads = ''.join('<image href="assets/pearl.webp" x="'+str(x-size/2)+'" y="'+str(y-size/2)+'" width="'+str(size)+'" height="'+str(size)+'" opacity="'+str(.5+min(i/12,.5))+'"/>' for i,(x,y,size) in enumerate(positions))
    artwork = '<svg class="about-necklace-art" viewBox="0 0 700 400" aria-hidden="true" focusable="false">'+cord+beads+'</svg>'
    hero = '<section class="reference-about-hero"><div class="reference-about-intro"><p class="eyebrow">Our story</p><h1>Individual strengths.<br>Shared possibilities.</h1><p class="lead">Agent Concierge helps people discover agents, inspect recorded checks, and review supported workflows.</p></div>'+artwork+'<p class="reference-about-quote">Different<br>capabilities.<br>Greater<br>possibilities<br>together.</p></section>'
    beliefs = [('Discover with purpose','Find agents that match your goals and understand their strengths, limitations and intended use.'),('Choose with evidence','Review recorded checks and clear information so you can make informed decisions.'),('Connect with consent','Bring the right agents together in purposeful workflows, with your guidance and control.')]
    belief = '<section class="reference-about-belief"><p class="eyebrow">Our belief</p><h2>Value starts with one capable agent.</h2><div class="reference-about-columns"><p>Every agent brings something valuable — unique knowledge, skills, or a fresh perspective. Agent Concierge helps you find the right ones and understand what they can do.</p><p>When individual agents are thoughtfully connected, they can work together toward a shared purpose. We make these connections easier to explore, inspect, and use, with clear information and user choice.</p></div><div class="reference-about-principles">'+''.join('<article>'+pearl()+'<div><h3>'+title+'</h3><p>'+copy+'</p></div></article>' for title,copy in beliefs)+'</div></section>'
    actions = [('Explore agents','Browse and learn about capable agents across different domains.','search','explore.html','Explore agents'),('Test connections','Try agents and see how they work together in simple, safe examples.','file','test.html','Test agents'),('Review workflows','See supported workflows that combine agents for useful tasks.','network','workflows.html','Explore workflows'),('Ask for one recommendation','Tell us what you’re trying to do and get a thoughtful agent suggestion.','chat','chat.html','Get a recommendation')]
    started = '<section class="reference-about-start"><div class="reference-about-start-heading"><div><p class="eyebrow">Get started</p><h2>What you can do today.</h2></div><p>Take meaningful steps toward your goals with AI agents. Start small, explore freely, and build from what works for you.</p></div><div class="grid four">'+''.join('<article class="card"><span class="icon-disc">'+icon(i)+'</span><h3>'+title+'</h3><p>'+copy+'</p><a class="reference-text-link" href="'+href+'">'+label+' '+icon('arrow')+'</a></article>' for title,copy,i,href,label in actions)+'</div></section>'
    direction = '<section class="reference-about-direction"><p class="eyebrow">Our direction</p><div class="reference-about-direction-heading"><h2>More useful connections,<br>with clearer evidence and user choice.</h2><div>'+pearl()+'<p>A more capable tomorrow, built from thoughtful connections today.</p></div></div><div class="reference-about-columns"><p>We’re building a trusted place where people can discover capable agents, understand their behavior through recorded checks, and connect them in purposeful workflows.</p><p>Our vision is a more open and useful AI ecosystem — one where individual agents can be combined in transparent ways to help people solve real problems, on their own terms.</p></div></section>'
    cta = '<section class="card reference-about-cta"><div><h2>Find your next useful connection.</h2><p>Explore agents, try connections and see what’s possible.</p></div><div class="actions">'+btn('Explore agents','explore.html','arrow','primary')+btn('Contact Agent Concierge','contact.html','chat')+'</div></section>'
    return hero+belief+started+direction+cta



from reference_learn import learn
