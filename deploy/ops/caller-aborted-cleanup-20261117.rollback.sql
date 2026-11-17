-- Restore for caller-aborted-cleanup-20261117.sql: puts the 4 runs, 4 evidence rows and 2 eligibility rows back to
-- their values before the change (values read 11-17 14:2x with scripts.prod_ro_sql). The eligibility rows are only
-- put back if nothing newer was written to them since the change (executed_at still the restored value).
BEGIN;
DO $$
DECLARE n integer;
BEGIN
  UPDATE edge_gateway_runs SET state = 'outcome_unknown', error_code = 'OUTCOME_UNKNOWN'
   WHERE id IN ('er_abf1c3a24a8ff1b90e78c14d01af09f5', 'er_792abbbacce5b39661a918c5333abe1d',
                'er_d90eae7974268f253ec56a7aa23ddf7f', 'er_72e7f5ac7cf908a8c1b223741d712bde')
     AND state = 'caller_aborted' AND error_code = 'CALLER_ABORTED';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 4 THEN RAISE EXCEPTION 'edge_gateway_runs: expected 4 rows, got %', n; END IF;

  UPDATE capability_evidence SET code = 'UPSTREAM_TIMEOUT', expires = finished + (expires_was.ttl)
    FROM (SELECT 86400.0 AS ttl) expires_was
   WHERE capability_evidence.id IN ('ev_76f86fb76d5eecd374cd046d1b5726b4', 'ev_5a7b268ad6b1043d587be47037bc2bf8',
                'ev_7a6c0ac3b4aaea22f65a0645b4898584', 'ev_8d3b3280ad00a083b6c50e0ea46d1d06')
     AND code = 'CALLER_ABORTED';
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 4 THEN RAISE EXCEPTION 'capability_evidence: expected 4 rows, got %', n; END IF;

  UPDATE capability_eligibility SET outcome = 'unknown', executed_at = 1794878436.579, expires = 1794878436.579 + 86400
   WHERE resource_id = 147960 AND round(executed_at::numeric, 3) = 1794634761.579;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'capability_eligibility 147960: expected 1 row, got %', n; END IF;

  UPDATE capability_eligibility SET outcome = 'unknown', executed_at = 1794879718.992, expires = 1794879718.992 + 86400
   WHERE resource_id = 241601 AND round(executed_at::numeric, 3) = 1794879354.626;
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'capability_eligibility 241601: expected 1 row, got %', n; END IF;
END $$;
COMMIT;
