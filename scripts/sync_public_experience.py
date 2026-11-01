"""Keep the retained standalone HTML and the published runtime extension aligned."""
import ast
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def main():
    path=ROOT/'agent_market/concierge/front.py';source=path.read_text();module=ast.parse(source)
    assignment=next(n for n in module.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HTML' for t in n.targets))
    html=assignment.value.value
    for tag,identity,asset in [('style','publicExperienceStyle','experience.css'),('script','publicExperienceRuntime','experience.js')]:
        content=(ROOT/'new/en/assets'/asset).read_text()
        block='<'+tag+' id="'+identity+'">\n'+content+'\n</'+tag+'>'
        pattern=r'<'+tag+r'\b[^>]*\bid="'+identity+r'"[^>]*>.*?</'+tag+'>'
        if re.search(pattern,html,re.S):html=re.sub(pattern,lambda match,block=block:block,html,flags=re.S)
        else:
            external='<link rel="stylesheet" href="/new/en/assets/experience.css">' if tag=='style' else '<script src="/new/en/assets/experience.js"></script>'
            assert external in html,'Missing runtime insertion point'
            html=html.replace(external,block)
    lines=source.splitlines(keepends=True);lines[assignment.lineno-1:assignment.end_lineno]=['HTML = '+repr(html)+'\n'];path.write_text(''.join(lines));(ROOT/'extracted_html.txt').write_text(html)
    path=ROOT/'new/en-manifest.json';data=json.loads(path.read_text());data['source_html_sha256']=hashlib.sha256(html.encode()).hexdigest();path.write_text(json.dumps(data,indent=2)+'\n')

if __name__=='__main__':main()
