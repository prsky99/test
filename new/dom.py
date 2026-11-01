"""Small dependency-free HTML tree for presentation-only build transforms."""
from html import escape
from html.parser import HTMLParser

VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def append(self, value):
        if isinstance(value, Node):
            if value.parent:
                value.parent.children.remove(value)
            value.parent = self
        self.children.append(value)
        return value

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def find(self, id):
        return next((n for n in self.walk() if n.attrs.get('id') == id), None)

    def remove(self):
        if self.parent:
            self.parent.children.remove(self)
        self.parent = None

    def replace(self, other):
        parent = self.parent
        index = parent.children.index(self)
        self.remove()
        if other.parent:
            other.remove()
        other.parent = parent
        parent.children.insert(index, other)

    def render(self):
        content = ''.join(c.render() if isinstance(c, Node) else c for c in self.children)
        if not self.tag:
            return content
        attrs = ''.join(' '+k+('="'+escape(v, quote=True)+'"' if v is not None else '') for k,v in self.attrs.items())
        return '<'+self.tag+attrs+'>' + ('' if self.tag in VOID else content+'</'+self.tag+'>')


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = Node()
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = self.current.append(Node(tag, attrs))
        if tag not in VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                break
            node = node.parent

    def handle_data(self, data): self.current.append(data)
    def handle_entityref(self, name): self.current.append('&'+name+';')
    def handle_charref(self, name): self.current.append('&#'+name+';')
    def handle_comment(self, data): self.current.append('<!--'+data+'-->')
    def handle_decl(self, data): self.current.append('<!'+data+'>')


def parse(value):
    parser = Parser()
    parser.feed(value)
    return parser.root


def fragment(value):
    return next(node for node in parse(value).children if isinstance(node, Node))
