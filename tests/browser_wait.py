"""Wait for a routed browser request without assuming synchronous dispatch."""
import time


def pending_request(page, requests, timeout=5):
    deadline=time.monotonic()+timeout
    while not requests:
        if time.monotonic()>=deadline:raise AssertionError('The expected browser request was not dispatched')
        page.wait_for_timeout(10)
    assert len(requests)==1
