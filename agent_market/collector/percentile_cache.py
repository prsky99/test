"""평가 점수 백분위를 잠깐 기억한다(2026-11-10, 운영·SRE).

score_percentile은 같은 종류의 평가된 자원 전체를 세는 쿼리라 한 번에 0.07~0.5초 걸린다.
평가마다 불러서 11-01~11-10에 73만 번, DB 시간 4.9만 초(전체의 9%)를 썼다.
점수 값은 종류마다 300여 개뿐이라 (종류, 점수)별 결과를 10분 쓰면 대부분 쿼리 없이 끝난다.
백분위는 참고 정보라 10분 늦게 바뀌어도 된다."""
import threading
import time

TTL_SECONDS = 600.0
MAX_ENTRIES = 4096
_lock = threading.Lock()


def score_percentile(store, score, kind, *, clock=time.monotonic):
    cache = getattr(store, '_score_percentile_cache', None)
    if cache is None:
        cache = {}
        try:
            store._score_percentile_cache = cache
        except AttributeError:
            return store.score_percentile(score, kind=kind)
    key, now = (kind, score), clock()
    with _lock:
        hit = cache.get(key)
    if hit is not None and now - hit[0] < TTL_SECONDS:
        return hit[1]
    value = store.score_percentile(score, kind=kind)
    with _lock:
        if len(cache) >= MAX_ENTRIES:
            for stale in [k for k, (at, _) in cache.items() if now - at >= TTL_SECONDS] or list(cache):
                del cache[stale]
        cache[key] = (now, value)
    return value
