"""jobs wiring of the verified MCP registry (E7): hourly, its own thread, a skipped or failed run retried next pass."""
import json

from agent_market.registry_schedule import VerifiedRegistryStep


def test_the_step_runs_hourly_and_retries_a_skipped_or_failed_run_at_the_next_pass(tmp_path):
    clock = [1_800_000_000.0]
    answers = [{'skipped': 'measurement_window'}, RuntimeError('db'), {'listed': 6900, 'entries': 6953, 'changes': 2}]

    def job(store):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    step = VerifiedRegistryStep(object(), clock=lambda: clock[0], job=job, background=False, log=tmp_path / 'r.jsonl')
    assert step.run_due()['verified_registry']['skipped'] == 'measurement_window'
    clock[0] += 60
    assert step.run_due()['verified_registry']['error'] == 'RuntimeError'      # retried at the next pass
    clock[0] += 60
    done = step.run_due()['verified_registry']
    assert (done['listed'], done['entries'], done['changes']) == (6900, 6953, 2)
    clock[0] += 1800
    assert step.run_due() is None                                              # within the hour after a finished run
    clock[0] += 1900
    answers.append({'listed': 1, 'entries': 1, 'changes': 0})
    assert step.run_due()['verified_registry']['listed'] == 1
    lines = [json.loads(x) for x in (tmp_path / 'r.jsonl').read_text().splitlines()]
    assert [('skipped' in x, x.get('error'), x.get('listed')) for x in lines] == [
        (True, None, None), (False, 'RuntimeError', None), (False, None, 6900), (False, None, 1)]


def test_a_running_thread_is_not_started_twice(tmp_path):
    import threading
    gate = threading.Event()
    step = VerifiedRegistryStep(object(), job=lambda store: gate.wait(5) and {'listed': 0}, log=tmp_path / 'r.jsonl')
    assert step.run_due() == {'verified_registry': 'started'}
    assert step.run_due() is None
    gate.set()
    step.thread.join(5)
