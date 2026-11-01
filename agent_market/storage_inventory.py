"""Bounded, syntax-only inventory of the repository's Python storage boundary.

No source is imported or executed. SQL strings are inspected in memory and are
never included in the report. Complete means the bounded AST scan completed;
it does not mean that aliases, dynamic SQL or migration coverage are resolved.
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat

PROFILE = 'static-storage-boundary-v1'
LIMITS = {'files': 1024, 'directories': 256, 'directory_entries': 1024, 'depth': 12, 'file_bytes': 2 * 1024 * 1024,
          'total_bytes': 32 * 1024 * 1024, 'file_ast_nodes': 250000,
          'total_ast_nodes': 4000000, 'findings': 100000,
          'resolution_steps': 4096, 'analysis_string_bytes': 16 * 1024 * 1024,
          'total_resolution_steps': 100000, 'total_analysis_string_bytes': 64 * 1024 * 1024}
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:\.py)?\Z')
SQL_START = re.compile(r'(?is)^\s*(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|PRAGMA|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|WITH|EXPLAIN|REINDEX|VACUUM|REPLACE|ANALYZE|ATTACH|DETACH|END)\b')
FEATURES = {
    'sql.pragma': r'\bPRAGMA\b',
    'sql.fts': r'\b(?:fts3|fts4|fts5|MATCH|bm25|highlight|snippet)\b',
    'sql.json': r'\bjson(?:b)?(?:_[A-Za-z0-9_]+)?\s*\(|->>?',
    'sql.rowid': r'\b(?:rowid|_rowid_|oid)\b',
    'sql.sqlite_catalog': r'\b(?:sqlite_master|sqlite_schema|sqlite_sequence|sqlite_temp_master)\b',
    'sql.autoincrement': r'\bAUTOINCREMENT\b',
    'sql.on_conflict': r'\bON\s+CONFLICT\b',
    'sql.insert_or_replace': r'\bINSERT\s+OR\s+REPLACE\b',
    'sql.insert_or_ignore': r'\bINSERT\s+OR\s+IGNORE\b',
    'sql.sqlite_function': r'\b(?:strftime|julianday|unixepoch|datetime|date|time|ifnull|group_concat|printf|randomblob|random|hex|changes|last_insert_rowid|total|iif)\s*\(',
    'sql.placeholder_qmark': r'\?(?![0-9])',
    'sql.placeholder_numbered': r'\?[0-9]+|\$[0-9]+',
    'sql.placeholder_named': r'(?<!:)(?:[:@$])[A-Za-z_][A-Za-z0-9_]*',
    'sql.placeholder_pyformat': r'%s|%\([A-Za-z_][A-Za-z0-9_]*\)s',
    'sql.schema_statement': r'\b(?:CREATE|ALTER|DROP)\s+(?:VIRTUAL\s+)?(?:TABLE|INDEX|TRIGGER|VIEW)\b',
    'sql.collation': r'\bCOLLATE\b',
    'sql.glob': r'\bGLOB\b',
    'sql.returning': r'\bRETURNING\b',
    'sql.transaction_statement': r'(?:^|;)\s*(?:BEGIN|COMMIT|ROLLBACK|SAVEPOINT|RELEASE|END)\b',
}
FEATURES = {key: re.compile(pattern, re.I) for key, pattern in FEATURES.items()}
DB_NAMES = {'db', 'connection', 'conn', 'cursor', 'cur', 'source', 'target', 'reader', 'writer'}
LIMITATIONS = [
    'Occurrences are syntactic locations, not executed operations or proven receiver types.',
    'Only fixed-tree Python source is scanned; templates, generated SQL, external packages and runtime state are outside this inventory.',
    'Simple lexical string bindings are followed conservatively; aliasing, interprocedural calls, branches and dynamically built SQL may remain unresolved.',
    'SQL feature matches are lexical indicators, not a SQL parser or an automatic SQL translation specification.',
    'Nested contexts describe lexical nesting only; they do not prove shared connection ownership or nested commits.',
    'Per-file hashes identify scanned bytes; the repository is not read as one atomic filesystem snapshot.',
    'This inventory does not establish PostgreSQL compatibility, migration completeness or operating acceptance.',
]


class InventoryError(ValueError):
    def __init__(self, code='source_unavailable'):
        self.code = code if code in ('source_unavailable', 'invalid_arguments', 'scan_interrupted') else 'source_unavailable'
        super().__init__(self.code)


def mask_sql(text):
    """Consume SQL quotes/comments linearly, including unterminated tails."""
    pieces = []; start = index = 0; length = len(text)
    while index < length:
        quote = text[index] if text[index] in ("'", '"') else None
        if quote:
            end = index + 1
            while True:
                closing = text.find(quote, end)
                if closing < 0: end = length; break
                if closing + 1 < length and text[closing + 1] == quote:
                    end = closing + 2; continue
                end = closing + 1; break
        elif text.startswith('--', index):
            closing = text.find('\n', index + 2); end = length if closing < 0 else closing
        elif text.startswith('/*', index):
            closing = text.find('*/', index + 2); end = length if closing < 0 else closing + 2
        else:
            index += 1; continue
        pieces.extend((text[start:index], ' ')); index = start = end
    pieces.append(text[start:])
    return ''.join(pieces)


def _bindings(body, arguments=()):
    """Only a single lexical assignment is a resolvable string binding."""
    found = {name: None for name in arguments}; counts = Counter(arguments)
    pending = [(node, True) for node in body]
    while pending:
        node, direct = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found[node.name] = None; counts[node.name] += 1; continue
        if isinstance(node, ast.Lambda): continue
        rebound = []
        if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)): rebound.append(node.target)
        elif isinstance(node, ast.withitem) and node.optional_vars: rebound.append(node.optional_vars)
        elif isinstance(node, (ast.NamedExpr, ast.Delete)):
            rebound.extend(node.targets if isinstance(node, ast.Delete) else [node.target])
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split('.')[0]; found[name] = None; counts[name] += 1
        elif isinstance(node, ast.ExceptHandler) and node.name:
            found[node.name] = None; counts[node.name] += 1
        for target in rebound:
            for part in ast.walk(target):
                if isinstance(part, ast.Name): found[part.id] = None; counts[part.id] += 1
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for part in ast.walk(target):
                    if isinstance(part, ast.Name):
                        counts[part.id] += 1
                        found[part.id] = node.value if direct and counts[part.id] == 1 and not isinstance(node, ast.AugAssign) else None
        pending.extend((child, False) for child in ast.iter_child_nodes(node))
    return found


class Analyzer(ast.NodeVisitor):
    def __init__(self, tree, file, maximum, work_remaining=None):
        self.file, self.maximum = file, maximum
        self.findings, self.seen, self.issues, self.sql_seen = [], set(), set(), set()
        self.scopes = [_bindings(tree.body)]; self.classes = []; self.contexts = []
        self.store_methods = set()
        self.sqlite_modules, self.sqlite_connects = {'sqlite3'}, set()
        remaining = work_remaining or {}
        self.step_limit = min(LIMITS['resolution_steps'], remaining.get('resolution_steps', LIMITS['resolution_steps']))
        self.string_limit = min(LIMITS['analysis_string_bytes'], remaining.get('analysis_string_bytes', LIMITS['analysis_string_bytes']))
        self.resolution_steps = self.analysis_string_bytes = 0; self.literal_sizes = {}

    def literal_size(self, node):
        if id(node) not in self.literal_sizes:
            self.literal_sizes[id(node)] = len(node.value.encode('utf-8', 'surrogatepass'))
        return self.literal_sizes[id(node)]

    def charge(self, size):
        if size > self.string_limit - self.analysis_string_bytes:
            self.issues.add('string_work_limit'); return False
        self.analysis_string_bytes += size; return True

    def mask(self, text, size):
        return mask_sql(text) if self.charge(size) else None

    def add(self, node, category):
        key = (id(node), category)
        if key in self.seen: return
        if len(self.findings) >= self.maximum:
            self.issues.add('finding_limit'); return
        self.seen.add(key)
        self.findings.append({'file': self.file, 'line': getattr(node, 'lineno', 1),
                              'column': getattr(node, 'col_offset', 0) + 1, 'category': category})

    def resolve(self, node, visited=None):
        if self.resolution_steps >= self.step_limit:
            self.issues.add('resolution_limit'); return None
        self.resolution_steps += 1
        visited = set() if visited is None else visited
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            size = self.literal_size(node)
            return (node.value, [node], size) if self.charge(size) else None
        if isinstance(node, ast.Name):
            if node.id in visited: return None
            for scope in reversed(self.scopes):
                if node.id in scope:
                    value = scope[node.id]
                    return self.resolve(value, visited | {node.id}) if value is not None else None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.resolve(node.left, visited)
            if left is None: return None
            right = self.resolve(node.right, visited)
            if right is None: return None
            size = left[2] + right[2]
            if size > LIMITS['file_bytes']:
                self.issues.add('string_work_limit'); return None
            if self.charge(size): return left[0] + right[0], left[1] + right[1], size
        return None

    def sql(self, expression, *, forced=False):
        resolved = self.resolve(expression)
        text = resolved[0] if resolved is not None else ''
        masked = self.mask(text, resolved[2]) if resolved is not None else None
        if resolved is not None and masked is None: return False
        if resolved is not None and (forced or SQL_START.match(masked)):
            parts = resolved[1]
        elif forced:
            parts = [part for part in ast.walk(expression) if isinstance(part, ast.Constant) and isinstance(part.value, str)]
        else: return False
        for part in parts:
            if id(part) in self.sql_seen: continue
            masked = self.mask(part.value, self.literal_size(part))
            if masked is None: return False
            self.sql_seen.add(id(part))
            for category, pattern in FEATURES.items():
                if pattern.search(masked): self.add(part, category)
        return resolved is not None

    def visit_Import(self, node):
        for item in node.names:
            if item.name == 'sqlite3': self.sqlite_modules.add(item.asname or 'sqlite3')

    def visit_ImportFrom(self, node):
        if node.module == 'sqlite3':
            for item in node.names:
                if item.name == 'connect': self.sqlite_connects.add(item.asname or 'connect')

    def visit_ClassDef(self, node):
        if node.name == 'Store':
            self.store_methods.update(id(part) for part in node.body if isinstance(part, (ast.FunctionDef, ast.AsyncFunctionDef)))
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def visit_FunctionDef(self, node):
        if id(node) in self.store_methods and node.name in ('tx', 'query'):
            self.add(node, 'definition.store_' + node.name)
        arguments = [part.arg for part in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
        if node.args.vararg: arguments.append(node.args.vararg.arg)
        if node.args.kwarg: arguments.append(node.args.kwarg.arg)
        old_contexts = self.contexts; self.contexts = []
        self.scopes.append(_bindings(node.body, arguments))
        self.generic_visit(node)
        self.scopes.pop(); self.contexts = old_contexts

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        if any(isinstance(target, ast.Name) and 'SCHEMA' in target.id.upper() for target in node.targets):
            self.sql(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if isinstance(node.target, ast.Name) and 'SCHEMA' in node.target.id.upper() and node.value is not None:
            self.sql(node.value)
        self.generic_visit(node)

    def visit_Attribute(self, node):
        category = {'_db': 'attribute.private_db', '_lock': 'attribute.private_lock',
                    'lastrowid': 'sqlite.lastrowid', 'row_factory': 'sqlite.row_factory',
                    'rowcount': 'dbapi.rowcount', 'total_changes': 'sqlite.total_changes'}.get(node.attr)
        if category: self.add(node, category)
        if node.attr == 'Row' and isinstance(node.value, ast.Name) and node.value.id in self.sqlite_modules:
            self.add(node, 'sqlite.row_mapping')
        self.generic_visit(node)

    def is_connect(self, node):
        return isinstance(node, ast.Call) and ((isinstance(node.func, ast.Attribute) and node.func.attr == 'connect'
            and isinstance(node.func.value, ast.Name) and node.func.value.id in self.sqlite_modules)
            or isinstance(node.func, ast.Name) and node.func.id in self.sqlite_connects)

    @staticmethod
    def db_receiver(node):
        return isinstance(node, ast.Attribute) and node.attr == '_db' or isinstance(node, ast.Name) and node.id in DB_NAMES

    def visit_Call(self, node):
        if self.is_connect(node): self.add(node, 'sqlite.connect')
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if method in ('tx', 'query', 'executescript', 'commit', 'rollback', 'executemany'):
                self.add(node, 'call.' + method)
            if method == 'commit' and 'transaction' in self.contexts:
                self.add(node, 'transaction.explicit_commit_in_tx_with')
            if method == 'tx' and 'transaction' in self.contexts:
                self.add(node, 'transaction.tx_call_inside_tx_with')
            if method in ('execute', 'executemany', 'executescript', 'query'):
                resolved = self.resolve(node.args[0]) if node.args else None
                masked = self.mask(resolved[0], resolved[2]) if resolved is not None else None
                sql_like = masked is not None and bool(SQL_START.match(masked))
                sql_sink = method in ('executescript', 'query', 'executemany') or self.db_receiver(node.func.value) or sql_like
                if sql_sink:
                    self.add(node, 'sql.call')
                    complete = bool(node.args) and self.sql(node.args[0], forced=True)
                    self.add(node, 'sql.call_resolved_string' if complete else 'sql.call_unresolved')
        self.generic_visit(node)

    def visit_With(self, node):
        entered = []
        for item in node.items:
            expression = item.context_expr
            if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute) and expression.func.attr == 'tx': kind = 'transaction'
            elif self.is_connect(expression) or self.db_receiver(expression): kind = 'connection'
            elif isinstance(expression, ast.Attribute) and expression.attr == '_lock': kind = 'lock'
            else: kind = None
            if kind:
                if self.contexts: self.add(expression, 'context.nested_storage_with')
                if kind == 'transaction' and 'transaction' in self.contexts: self.add(expression, 'transaction.nested_tx_with')
                self.add(expression, 'context.' + kind)
            self.visit(expression)
            if item.optional_vars: self.visit(item.optional_vars)
            if kind: self.contexts.append(kind); entered.append(kind)
        for statement in node.body: self.visit(statement)
        for _ in entered: self.contexts.pop()

    visit_AsyncWith = visit_With


def analyze_source(text, relative_file='agent_market/_synthetic.py', *, maximum=None, _work_remaining=None):
    """Pure testable AST analysis; the scan CLI never accepts a source/root."""
    if (not isinstance(relative_file, str) or not relative_file.startswith('agent_market/')
            or any(not NAME.fullmatch(part) for part in relative_file.split('/')) or not relative_file.endswith('.py')):
        raise InventoryError()
    maximum = LIMITS['findings'] if maximum is None else maximum
    if type(maximum) is not int or not 0 <= maximum <= LIMITS['findings']: raise InventoryError()
    if _work_remaining is not None and (not isinstance(_work_remaining, dict)
            or set(_work_remaining) != {'resolution_steps', 'analysis_string_bytes'}
            or any(type(value) is not int or value < 0 for value in _work_remaining.values())): raise InventoryError()
    try: tree = ast.parse(text, filename='<repository-source>')
    except (SyntaxError, UnicodeError, RecursionError, ValueError):
        return {'findings': [], 'ast_nodes': 0, 'resolution_steps': 0, 'analysis_string_bytes': 0, 'issues': ['parse_failed']}
    pending = [tree]; nodes = 0
    while pending:
        part = pending.pop(); nodes += 1
        if nodes > LIMITS['file_ast_nodes']:
            return {'findings': [], 'ast_nodes': nodes, 'resolution_steps': 0, 'analysis_string_bytes': 0, 'issues': ['ast_node_limit']}
        pending.extend(ast.iter_child_nodes(part))
    analyzer = Analyzer(tree, relative_file, maximum, _work_remaining)
    try: analyzer.visit(tree)
    except (RecursionError, ValueError, TypeError): analyzer.issues.add('analysis_incomplete')
    return {'findings': sorted(analyzer.findings, key=lambda row: (row['line'], row['column'], row['category'])),
            'ast_nodes': nodes, 'resolution_steps': analyzer.resolution_steps,
            'analysis_string_bytes': analyzer.analysis_string_bytes, 'issues': sorted(analyzer.issues)}


def _source_root(): return Path(__file__).resolve().parent


def scan():
    """Read only regular Python files under the fixed application source tree."""
    root = _source_root(); result = {'ok': True, 'profile': PROFILE, 'complete': True,
        'scope': {'root': 'agent_market', 'python_source_only': True, 'source_execution': False},
        'files': [], 'findings': [], 'issues': [], 'limits': dict(LIMITS), 'limitations': list(LIMITATIONS)}
    counters = Counter(); issues = set(); exact = True
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try: root_fd = os.open(root, flags)
    except OSError: raise InventoryError() from None

    def read_file(directory_fd, name, relative):
        item = {'file': relative, 'complete': False, 'bytes': 0, 'ast_nodes': 0,
                'resolution_steps': 0, 'analysis_string_bytes': 0, 'issues': []}
        try:
            fd = os.open(name, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0), dir_fd=directory_fd)
            with os.fdopen(fd, 'rb') as source:
                before = os.fstat(source.fileno())
                if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                    item['issues'].append('non_regular_source'); return item
                if before.st_size > LIMITS['file_bytes']:
                    item['issues'].append('file_byte_limit'); return item
                if counters['bytes_read'] + before.st_size > LIMITS['total_bytes']:
                    item['issues'].append('total_byte_limit'); return item
                data = source.read(LIMITS['file_bytes'] + 1); after = os.fstat(source.fileno())
            item['bytes'] = len(data); counters['bytes_read'] += len(data)
            if len(data) > LIMITS['file_bytes'] or counters['bytes_read'] > LIMITS['total_bytes']:
                item['issues'].append('file_byte_limit'); return item
            if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
                item['issues'].append('source_changed'); return item
            item['sha256'] = hashlib.sha256(data).hexdigest()
            try: text = data.decode('utf-8')
            except UnicodeError:
                item['issues'].append('encoding_failed'); return item
            analysis = analyze_source(text, relative, maximum=LIMITS['findings'] - len(result['findings']),
                _work_remaining={'resolution_steps': max(0, LIMITS['total_resolution_steps'] - counters['resolution_steps']),
                                 'analysis_string_bytes': max(0, LIMITS['total_analysis_string_bytes'] - counters['analysis_string_bytes'])})
            item['ast_nodes'] = analysis['ast_nodes']; counters['ast_nodes'] += item['ast_nodes']
            for name in ('resolution_steps', 'analysis_string_bytes'):
                item[name] = analysis[name]; counters[name] += analysis[name]
            if 'parse_failed' not in analysis['issues']: counters['parsed_files'] += 1
            if counters['ast_nodes'] > LIMITS['total_ast_nodes']:
                item['issues'].append('total_ast_node_limit'); return item
            result['findings'].extend(analysis['findings']); item['issues'].extend(analysis['issues'])
            item['complete'] = not item['issues']
        except OSError: item['issues'].append('source_unavailable')
        return item

    def walk(directory_fd, relative, depth):
        nonlocal exact
        if counters['discovered_files'] > LIMITS['files']: return
        counters['directories'] += 1
        if counters['directories'] > LIMITS['directories'] or depth > LIMITS['depth']:
            issues.add('directory_limit'); exact = False; return
        try:
            with os.scandir(directory_fd) as entries:
                names = []
                for index, entry in enumerate(entries):
                    if index >= LIMITS['directory_entries']:
                        issues.add('directory_entry_limit'); exact = False; break
                    if not entry.name.startswith('.') and entry.name != '__pycache__': names.append(entry.name)
                names.sort()
        except OSError: issues.add('source_unavailable'); exact = False; return
        for name in names:
            if counters['discovered_files'] > LIMITS['files']: return
            path = relative + '/' + name
            try: info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError: issues.add('source_unavailable'); exact = False; continue
            if not stat.S_ISDIR(info.st_mode) and not name.endswith('.py'):
                if stat.S_ISLNK(info.st_mode): issues.add('excluded_source_symlink'); exact = False
                continue
            if not NAME.fullmatch(name):
                issues.add('unrecognized_source_name'); exact = False; continue
            if stat.S_ISDIR(info.st_mode):
                try: child = os.open(name, flags, dir_fd=directory_fd)
                except OSError: issues.add('source_unavailable'); exact = False; continue
                try: walk(child, path, depth + 1)
                finally: os.close(child)
            elif name.endswith('.py'):
                counters['discovered_files'] += 1
                if counters['discovered_files'] > LIMITS['files']:
                    issues.add('file_limit'); exact = False; return
                result['files'].append(read_file(directory_fd, name, path))
    try: walk(root_fd, 'agent_market', 0)
    finally: os.close(root_fd)
    result['files'].sort(key=lambda row: row['file'])
    result['findings'].sort(key=lambda row: (row['file'], row['line'], row['column'], row['category']))
    if not result['files']: issues.add('no_python_source')
    result['issues'] = sorted(issues)
    result['complete'] = not issues and bool(result['files']) and all(item['complete'] for item in result['files'])
    categories = Counter(item['category'] for item in result['findings'])
    result['counts'] = {'discovered_files': counters['discovered_files'], 'file_count_exact': exact,
        'parsed_files': counters['parsed_files'], 'incomplete_files': sum(not item['complete'] for item in result['files']),
        'bytes_read': counters['bytes_read'], 'ast_nodes': counters['ast_nodes'], 'findings': len(result['findings']),
        'resolution_steps': counters['resolution_steps'], 'analysis_string_bytes': counters['analysis_string_bytes'],
        'categories': dict(sorted(categories.items()))}
    result['coverage'] = {'complete_means': 'bounded_syntactic_scan_only', 'all_runtime_storage_access_resolved': False,
        'sql_dialect_compatibility_verified': False, 'receiver_types_verified': False,
        'nested_transaction_ownership_verified': False, 'single_atomic_repository_snapshot': False,
        'detected_unresolved_sql_calls': categories['sql.call_unresolved']}
    return result


class Parser(argparse.ArgumentParser):
    def error(self, message): raise InventoryError('invalid_arguments')


class ScanOnce(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest, False): raise InventoryError('invalid_arguments')
        setattr(namespace, self.dest, True)


def main(argv=None):
    parser = Parser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--scan', action=ScanOnce, nargs=0, default=False, help='Scan only the fixed repository application source tree.')
    try:
        args = parser.parse_args(argv)
        if args.scan is not True: raise InventoryError('invalid_arguments')
        result = scan(); status = 0 if result['complete'] else 1
    except InventoryError as exc:
        result = {'ok': False, 'profile': PROFILE, 'error': exc.code}; status = 2 if exc.code == 'invalid_arguments' else 1
    except KeyboardInterrupt:
        result = {'ok': False, 'profile': PROFILE, 'error': 'scan_interrupted'}; status = 130
    except Exception:
        result = {'ok': False, 'profile': PROFILE, 'error': 'source_unavailable'}; status = 1
    print(json.dumps(result, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return status


if __name__ == '__main__': raise SystemExit(main())
