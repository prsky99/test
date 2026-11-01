# Private runtime simulation

This is a private staff-controlled simulation profile, not a billing service.
`workspace_metering.py` records logical private runs separately from actual
business dispatch attempts. A successful logical run consumes the configured
integer `TEST_UNIT` once, with two signed balanced entries. Preparation,
handshakes, unsuccessful calls and uncertain outcomes do not create successful
usage. Multi-node flows retain one logical operation and up to six attempts.

The current workspace owner authorizes an expiring, bounded policy using a
fresh purpose-specific notice. Its signature binds the owner session, current
workspace/member revisions and global role. Admission and dispatch recheck this
authority. A new policy cannot silently replace the policy of an admitted run.
Tickets still require their own execution consent; a simulation policy grants
no provider-call authority. Execute-only app tokens cannot administer policies.

Admission, dispatch and terminal accounting share the corresponding native run
writer transactions. A terminal write failure rolls back its accounting and
does not repeat the provider call. Unknown results remain unknown and have zero
successful simulated usage. Current-owner recovery only finalizes expired
simulation metadata from signed private/typed run records; it never resends or
changes the actual external outcome. Replays cannot duplicate entries.

Each workspace retains at most 10,000 simulated operations. The summary checks
signed operations, ordered attempts and balanced entries, rejecting orphaned or
tampered records. Restore removes authorization policies; prior operation
revisions remain reserved to prevent a reset from reusing an old policy budget.
This bounded profile is not a global retention or physical-erasure policy.

The existing manual shadow ledger and agreement allocation simulations are
separate explicit review tools. These modules do not charge customers, transmit
payment credentials, create actual provider payouts, infer advertising consent
or change recommendation ranking. They must not be presented as real commerce.

The administrator opens **Workspace simulation and support → Runtime
simulation**. The public Workspace access surface remains closed by default.
Tests use isolated SQLite/PostgreSQL fixtures and synthetic providers; actual
operating metering and commerce acceptance require separate evidence.
