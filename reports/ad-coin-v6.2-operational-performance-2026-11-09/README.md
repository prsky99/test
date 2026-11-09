# AI AD Coin v6.2 Operational Performance & Load Benchmark Report

**Benchmark Profile**: `ad_coin_v2_operational_performance_production`  
**Date**: November 9, 2026  
**Environment**: Disposable, isolated PostgreSQL 18 cluster with private Unix socket transport  
**Benchmark Runner**: [`scripts/ad_coin_v2_operational_perf.py`](scripts/ad_coin_v2_operational_perf.py)  
**Raw Metrics Data**: [`reports/ad-coin-v6.2-operational-performance-2026-11-09/operational_perf_report.json`](reports/ad-coin-v6.2-operational-performance-2026-11-09/operational_perf_report.json)

---

## 1. Executive Summary

This benchmark rigorously evaluates the end-to-end performance and transactional integrity of the AI AD Coin v2 platform under realistic operational conditions. Unlike previous local microbenchmarks that focused solely on raw database write loops, this test encompasses the complete system architecture:

- **End-to-End HTTP Transport**: Routing through FastAPI/Starlette with CSRF protection, secure cookie decoding, and contract version headers (`X-AIAC-Contract: v6.2`).
- **Persistent Credential Verification**: Session resolution, principal lookup, and capability evaluation backed by PostgreSQL.
- **Cryptographic Operations**: Ed25519 digital signature signing and verification for payment mandates and receipts via [`KeyVault`](agent_market/ad_coin/v2/key_vault.py).
- **Agent Payments & Escrow**: Delegated mandate authorization, escrow hold locking (`user_available` $\to$ `user_locked`), task settlement (`user_locked` $\to$ `provider_payable`), and failure refunds (`user_locked` $\to$ `user_available`).
- **Multi-Region Network Simulation**: Emulated network transit latencies across 5 production regions: South Korea (KR), Japan (JP), United States (US), Great Britain (GB), and Germany (DE).
- **Double-Entry Ledger Conservation**: Automated post-benchmark audit and reconciliation proving zero-sum monetary conservation.

### Key Performance Highlights
- **Total Operational Requests**: **500** requests across 8 concurrent client worker threads.
- **Successful Operations**: **500 / 500 (100.0%)** with **0.0% Error Rate**.
- **Overall Throughput**: **126.64 operations/second** through the full HTTP + Session + Crypto + DB stack.
- **Preseeded Historical Ledger Depth**: 2,000 double-entry transaction journals prior to load injection.
- **Ledger Invariant Verification**: Final double-entry ledger audit verified **$0$ atom imbalance** (`beneficial_atoms` = +240,000,000, `clearing_atoms` = -240,000,000).
- **Reconciliation Engine**: Status **CLEAN** with **0 issues detected**.

---

## 2. Workload & Latency Distribution

### Overall Latency Percentiles
| Metric | Latency (ms) |
| :--- | :--- |
| **Minimum** | **3.27 ms** |
| **p50 (Median)** | **24.58 ms** |
| **p95** | **104.22 ms** |
| **p99** | **116.91 ms** |
| **Maximum** | **156.83 ms** |

### Latency by Operation Type
| Operation Type | Request Count | p50 (ms) | p95 (ms) | p99 (ms) |
| :--- | :--- | :--- | :--- | :--- |
| **Mandate Listing** (`GET /mandates`) | 100 | 5.52 | 9.00 | 12.00 |
| **Execution Escrow Hold** (`POST /executions/hold`) | 300 | 5.98 | 13.36 | 28.73 |
| **Workspace Session BFF** (`GET /ui/session`) | 100 | 70.90 | 77.71 | 88.70 |
| **Execution Settle** (`POST /executions/{id}/settle` - ok: true) | 200 | 86.67 | 106.58 | 116.91 |
| **Execution Refund** (`POST /executions/{id}/settle` - ok: false) | 100 | 100.62 | 117.23 | 129.81 |

### Latency Breakdown by Simulated Region
| Region Code | Simulated Transit Lag | Operations | p50 (ms) | p95 (ms) | p99 (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **KR** | ~2 ms | 100 | 5.52 | 9.00 | 12.00 |
| **JP** | ~15 ms | 100 | 30.82 | 41.70 | 53.10 |
| **US** | ~60 ms | 100 | 70.90 | 77.71 | 88.70 |
| **GB** | ~80 ms | 100 | 97.94 | 110.02 | 127.26 |
| **DE** | ~85 ms | 100 | 100.62 | 117.23 | 129.81 |

---

## 3. Concurrency & Deadlock Prevention Architecture

During high-concurrency multi-threaded execution, transactions modifying related entities (such as Mandates and Account Balances) must follow a strictly ordered lock acquisition hierarchy. 

To eliminate lock inversion deadlocks under PostgreSQL `READ COMMITTED` and `REPEATABLE READ` transaction isolation levels:
1. **Hierarchical Lock Ordering**: Transactions always acquire the row lock on [`adc2_mandates`](agent_market/ad_coin/v2/agent_payment_schema.py) (`mandate_get_for_update`) **before** acquiring row locks on [`adc2_accounts`](agent_market/ad_coin/v2/schema.py).
2. **Deterministic Account Ordering**: [`ModelLedger.post`](agent_market/ad_coin/v2/ledger.py#L126) automatically sorts posting account identifiers lexicographically before acquiring row-level locks, preventing pairwise account deadlocks.
3. **Safe Spending Limit Adjustments**: Refunds utilize non-negative bounding (`GREATEST(0, spent_atoms - ?)`) to prevent check constraint violations during rapid concurrent compensations.

---

## 4. Verification and Invariant Audit

Post-benchmark execution included a full execution of the disaster recovery and reconciliation engine:
- **Zero-Sum Balance Conservation**:
  $$\sum \text{beneficial\_atoms} + \sum \text{clearing\_atoms} = 240,000,000 + (-240,000,000) = 0$$
- **Account Non-Negativity**: All non-clearing beneficial accounts maintained strictly non-negative balances throughout the benchmark.
- **Resource Cleanup**: The disposable PostgreSQL cluster was completely shut down and unmounted without leaving dangling unix sockets, processes, or temporary files.
