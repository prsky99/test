"""MCP tasks (protocol 2025-11-25) for published workflow runs (11-04, implemented as designed at the operator's request).

`run_workflow` starts the same public run that POST /api/workflows/run admits and, when the caller asks
for a task, answers at once with a CreateTaskResult. `tasks/get`, `tasks/result` and `tasks/cancel`
follow that run. No new authority: the published template, the reviewed definition_hash and the declared
input are checked as in REST, and the task id carries the run key, so only the caller that started a run
can read or cancel it (the X-Workflow-Key rule).
"""
import re
import time
from datetime import datetime, timezone

CAPABILITY = {'cancel': {}, 'requests': {'tools': {'call': {}}}}
TTL_MS = 3_600_000
POLL_MS = 2_000
RESULT_WAIT = 20  # seconds tasks/result waits for a terminal state before asking the caller to poll
STATES = {'queued': 'working', 'running': 'working', 'succeeded': 'completed', 'failed': 'failed',
          'cancelled': 'cancelled'}
TASK_ID = re.compile(r'([A-Za-z0-9_-]{8,100})\.([A-Za-z0-9_-]{16,100})')

TOOL = {
    'name': 'run_workflow',
    'title': 'Run a published workflow',
    'description': ('Run one published workflow after reviewing it with workflow_details. Pass the definition_hash '
                    'you reviewed; a changed workflow is refused. Ask for a task (params.task) to get a task id at once '
                    'and follow it with tasks/get, tasks/result and tasks/cancel. Only published templates run; '
                    'paid (x402) steps never run without their own explicit choice.'),
    'inputSchema': {'type': 'object', 'additionalProperties': False, 'required': ['template_id', 'definition_hash'],
                    'properties': {
                        'template_id': {'type': 'integer', 'minimum': 1, 'description': 'Published workflow id from search_workflows.'},
                        'definition_hash': {'type': 'string', 'pattern': '^[0-9a-f]{64}$',
                                            'description': 'definition_hash returned by workflow_details for the version you reviewed.'},
                        'input': {'type': 'object', 'description': 'Declared product input fields, when the workflow has them.'}}},
    'annotations': {'readOnlyHint': False, 'destructiveHint': False,
                    'idempotentHint': False, 'openWorldHint': True},
    'execution': {'taskSupport': 'optional'},
}


class TaskError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def _iso(seconds):
    return datetime.fromtimestamp(float(seconds), timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def start(front, args):
    """Admit one public run with the REST checks; returns {'run_id', 'run_key', 'status'}."""
    from ..workflows import WorkflowError, public_template
    if set(args) - {'template_id', 'definition_hash', 'input'}:
        raise TaskError(-32602, 'Use template_id, definition_hash and an optional input object.')
    template_id, reviewed = args.get('template_id'), args.get('definition_hash')
    if type(template_id) is not int or not 0 < template_id < 2**31:
        raise TaskError(-32602, 'A positive integer template_id is required.')
    if not isinstance(reviewed, str) or not re.fullmatch(r'[0-9a-f]{64}', reviewed):
        raise TaskError(-32602, 'Review the workflow with workflow_details and pass its definition_hash.')
    if 'input' in args and not isinstance(args['input'], dict):
        raise TaskError(-32602, 'input must be an object of the declared fields.')
    workflow = front.store.get_workflow(template_id)
    projected = public_template(workflow, front.workflows) if workflow else None
    if not projected:
        raise TaskError(-32602, 'Choose an available published template.')
    if reviewed != projected['definition_hash']:
        raise TaskError(-32602, 'The published workflow changed. Review it with workflow_details before running.')
    if 'input' in args and 'product' not in projected:
        raise TaskError(-32602, 'This template does not declare input fields.')
    try:
        run = front.workflows.submit(workflow if 'product' in projected else projected, actor='public', source='public',
                                     public=True, product_input=args.get('input', {}) if 'product' in projected else None)
    except WorkflowError as exc:
        raise TaskError(-32602, str(exc)) from None
    if not run.get('run_key'):
        raise TaskError(-32603, 'This run cannot be followed; use the REST API.')
    return run


def task_id(run):
    return run['run_id'] + '.' + run['run_key']


def _run(front, value):
    """The run behind a task id, or a not-found error for unknown ids and wrong keys alike."""
    from ..workflows import WorkflowError
    match = TASK_ID.fullmatch(value) if isinstance(value, str) else None
    if not match or not front.workflows.authorized(match[1], match[2]):
        raise TaskError(-32602, 'Task not found.')
    try:
        return front.workflows.get(match[1])
    except WorkflowError:
        raise TaskError(-32602, 'Task not found.') from None


def view(value, run):
    status = STATES.get(run.get('status'), 'completed')
    task = {'taskId': value, 'status': status, 'createdAt': _iso(run.get('created_at') or time.time()),
            'lastUpdatedAt': _iso(time.time()), 'ttl': TTL_MS}
    if status == 'working':
        task['pollInterval'] = POLL_MS
    message = run.get('error') if status == 'failed' else 'Workflow ' + str(run.get('status'))
    if message:
        task['statusMessage'] = str(message)[:300]
    return task


def tool_result(value, run):
    from ..workflows import public_outcome
    outcome = public_outcome(run)
    steps = outcome.get('node_results') or []
    done = sum(1 for step in steps if step.get('status') == 'succeeded')
    text = f"Workflow {outcome.get('workflow_name') or outcome.get('workflow_id')}: {outcome.get('status')} ({done}/{len(steps)} steps succeeded)."
    return {'content': [{'type': 'text', 'text': text}], 'structuredContent': outcome,
            'isError': outcome.get('status') != 'succeeded',
            '_meta': {'io.modelcontextprotocol/related-task': {'taskId': value}}}


def get(front, params):
    value = params.get('taskId')
    return view(value, _run(front, value))


def cancel(front, params):
    value = params.get('taskId')
    run = _run(front, value)
    if STATES.get(run.get('status')) != 'working':
        raise TaskError(-32602, 'Task is already ' + STATES.get(run.get('status'), 'completed') + '.')
    return view(value, front.workflows.cancel(value.split('.', 1)[0]))


def result(front, params, wait=RESULT_WAIT, sleep=time.sleep):
    """The run's final tool result; waits up to `wait` seconds, then asks the caller to keep polling."""
    value = params.get('taskId')
    deadline = time.monotonic() + wait
    while True:
        run = _run(front, value)
        if STATES.get(run.get('status'), 'completed') != 'working':
            return tool_result(value, run)
        if time.monotonic() >= deadline:
            raise TaskError(-32603, 'Task is still working; poll tasks/get and ask for the result again.')
        sleep(POLL_MS / 1000)


def refused(message):
    """An admission refusal is a tool result with isError (MCP), like the other tools' refusals."""
    return {'content': [{'type': 'text', 'text': message}],
            'structuredContent': {'ok': False, 'status': 'refused', 'error': message}, 'isError': True}


def started(value, run):
    """A run started without a task request: the ids a caller needs to follow it."""
    return {'content': [{'type': 'text', 'text': 'Workflow run queued. Follow it with tasks/get using taskId, '
                                                 'or GET /api/workflows/runs/{run_id} with X-Workflow-Key.'}],
            'structuredContent': {'status': 'queued', 'taskId': value, 'run_id': run['run_id'], 'run_key': run['run_key']},
            'isError': False}
