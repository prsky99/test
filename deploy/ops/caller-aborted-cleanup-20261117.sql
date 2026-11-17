-- 11-17 PM decision 2 (ops analysis of the Worker c2702834 rollback): between 08:41 and 10:48 the Edge Worker
-- reported four calls our own runner cut at its 3.5 s slot deadline as outcome_unknown (closed 1.4-1.6 s after
-- start). The origin counted them as provider timeouts and recorded UPSTREAM_TIMEOUT execution evidence, which also
-- set capability_eligibility to "unknown" for 147960 and 241601. Nothing is deleted:
--   * the 4 runs get state 'caller_aborted' / error_code 'CALLER_ABORTED' (out of the 7-day bad count, which reads
--     only succeeded / failed / outcome_unknown);
--   * the 4 evidence rows get code 'CALLER_ABORTED' and expire at their own record time;
--   * the 2 eligibility rows go back to the last execution evidence before these rows.
-- Every statement must touch exactly the expected rows, or the whole change rolls back.
-- Restore: deploy/ops/caller-aborted-cleanup-20261117.rollback.sql. Rows before the change: export first (README in
-- the same commit message / ops note).
BEGIN;
DO $$
DECLARE n integer;
BEGIN
  UPDATE edge_gateway_runs SET state = 'caller_aborted', error_code = 'CALLER_ABORTED'
   WHERE id IN ('er_abf1c3a24a8ff1b90e78c14d01af09f5', 'er_792abbbacce5b39661a918c5333abe1d',
                'er_d90eae7974268f253ec56a7aa23ddf7f', 'er_72e7f5ac7cf908a8c1b223741d712bde')
     AND backend = 'worker' AND state = 'outcome_unknown' AND error_code = 'OUTCOME_UNKNOWN';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 4 THEN RAISE EXCEPTION 'edge_gateway_runs: expected 4 rows, got %', n; END IF;

  UPDATE capability_evidence SET code = 'CALLER_ABORTED', expires = recorded
   WHERE id IN ('ev_76f86fb76d5eecd374cd046d1b5726b4', 'ev_5a7b268ad6b1043d587be47037bc2bf8',
                'ev_7a6c0ac3b4aaea22f65a0645b4898584', 'ev_8d3b3280ad00a083b6c50e0ea46d1d06')
     AND scope = 'execution' AND outcome = 'unknown' AND code = 'UPSTREAM_TIMEOUT'
     AND dataset_version = 'edge-worker-execution-v1';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 4 THEN RAISE EXCEPTION 'capability_evidence: expected 4 rows, got %', n; END IF;

  -- 147960: last execution evidence before 10:20:36 is the 11-14 14:39:21 success (already expired 11-15).
  UPDATE capability_eligibility SET outcome = 'succeeded', executed_at = 1794634761.579, expires = 1794721161.579
   WHERE resource_id = 147960 AND version_id = 'cv_a4e1e7b744e41343e0f1e4c129dca475'
     AND outcome = 'unknown' AND round(executed_at::numeric, 3) = 1794878436.579;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'capability_eligibility 147960: expected 1 row, got %', n; END IF;

  -- 241601: last execution evidence before 10:41:58 is the 10:35:54 success.
  UPDATE capability_eligibility SET outcome = 'succeeded', executed_at = 1794879354.626, expires = 1794965754.626
   WHERE resource_id = 241601 AND version_id = 'cv_820fa8ec8fd5ffd8bcf67349e2910477'
     AND outcome = 'unknown' AND round(executed_at::numeric, 3) = 1794879718.992;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'capability_eligibility 241601: expected 1 row, got %', n; END IF;
END $$;
COMMIT;
