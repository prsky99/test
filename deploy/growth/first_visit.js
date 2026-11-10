  // 11-10: after a search or a Chat answer, bring the first result into view (one scroll, only when it is below the fold).
  {
    let lastInput=0;const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
    document.addEventListener('pointerdown',()=>{lastInput=Date.now();},true);document.addEventListener('keydown',()=>{lastInput=Date.now();},true);
    const reveal=el=>{if(!el)return;const top=el.getBoundingClientRect().top;if(top>innerHeight-120||top<0)el.scrollIntoView({block:'start',behavior:reduce?'auto':'smooth'});};
    if(typeof renderExplore==='function'){const priorReveal=renderExplore;renderExplore=function(...args){const value=priorReveal(...args);
      if(Date.now()-lastInput<4000){const first=document.querySelector('#xResults .acard[data-id]');if(first)requestAnimationFrame(()=>reveal(document.querySelector('#xTitle')||first));}return value;};}
    const log=document.getElementById('chatMessages');
    if(log&&'MutationObserver' in window){let shown=0;new MutationObserver(()=>{const cards=log.querySelectorAll('.chat-recommendation');
      if(cards.length>shown&&Date.now()-lastInput<30000){const first=cards[shown];shown=cards.length;requestAnimationFrame(()=>reveal(first));}else shown=cards.length;}).observe(log,{childList:true,subtree:true});}
  }
