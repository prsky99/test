-- 그래프 상한(scripts.embeddings_graph_cap) 복구 SQL. 2026-11-13 검색과 RAG.
-- 같은 내용을 도구로도 실행할 수 있다:
--   .venv/bin/python -m scripts.embeddings_graph_cap rollback --dsn-file <dsn> --i-have-approval
-- psql로 실행할 때는 트랜잭션 밖에서 한 줄씩 실행한다(CONCURRENTLY는 트랜잭션 안에서 안 됨). 연결은 하나만 쓴다.
--
-- 순서가 중요하다.
-- 1) 상한 색인 두 개를 먼저 내린다. 쓰기를 막지 않는다.
--    운영 코드(postgres_ann.layout)는 색인이 없으면 옛 종류별 색인으로 돌아간다.
DROP INDEX CONCURRENTLY IF EXISTS agentcon_search.embeddings_half_a2a_cap;
DROP INDEX CONCURRENTLY IF EXISTS agentcon_search.embeddings_half_x402_cap;
-- 2) 330초 기다린다.
--    각 프로세스는 그래프 구성을 최대 300초 기억한다(LAYOUT_SECONDS).
--    그 사이에는 검색이 아직 e.in_kind_graph를 조건에 쓴다. 열이 먼저 사라지면 그 검색이 오류를 낸다.
SELECT pg_sleep(330);
-- 3) 열을 지운다. 메타데이터만 바꾸므로 즉시 끝난다. 잠금은 2초까지만 기다린다.
SET lock_timeout = '2s';
ALTER TABLE agentcon_search.embeddings DROP COLUMN IF EXISTS in_kind_graph;
-- 확인:
--   public 트리거가 그대로 5개인지
--   embeddings_half_a2a/mcp/x402와 embeddings_cosine_hnsw가 그대로 valid인지
-- 옛 색인과 데이터는 이 변경으로 바뀌지 않는다. 그래서 데이터 복구는 필요 없다.
