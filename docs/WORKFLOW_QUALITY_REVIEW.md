# Scoped pre-run staff review management

`workspace-quality-review-v1` implements a private reservation, disclosure,
judgment and disagreement queue. It reuses the fixed six-dimension rubric and
digest from `ReviewPackets`. Existing metadata worksheets and controlled-pair
tools remain unchanged; their global run IDs are not silently imported into a
workspace. The initial queue accepts only retained scoped `wpr_` executions.

A current workspace owner reserves an active private snapshot, frozen dataset,
case and separate-source hashes plus an opaque source reference before creating
the measured run. The executor, two to four review accounts and adjudicator are
distinct current writable staff members. The reserving account cannot appoint
itself an outcome reviewer or adjudicator. This uses actual current database
sessions/accounts; it is not proof that distinct accounts belong to independent
people or qualified experts.

The reservation also pins workspace and participant membership revisions,
current global roles/account revision time, the actual registered resource
binding/observation generation and control epoch. Withdrawal/restoration does
not revive an old assignment. Current provider generation is checked against
both reservation and retained execution ticket without requiring the original
executor session to remain logged in. Historical metadata remains inspectable;
an archived or changed scope returns `retained_assignment_not_current` and no
current qualification claim.

Binding is separate and explicit. A retained signed private run must match the
exact workspace/draft/snapshot/executor, be created no earlier than the signed
reservation, and have a succeeded, dispatched and completed outcome. Historical,
unknown, altered, missing or cross-scope runs cannot be accepted as measured
proof. One run is linked to at most one assignment in its workspace. No workflow
or model is executed by reservation, binding, inspection, scoring or comparison.

Assigned reviewers explicitly open the retained private output; a signed
disclosure record and audit precede their judgment. Current session/membership
and active parent/snapshot are checked again for every operation. Reviewers
cannot judge their own execution or an unassigned case. Scores are explicit
integers 0–2 or null/unassessed for every pinned rubric dimension. Source
observation time, source-review and no-conflict declarations and bounded notes
are recorded without treating those declarations as verified facts. Original
judgments are immutable; exact resubmission is an idempotent read.

All assigned reviewers must finish with assessable dimensions before a result is
complete. Different scores require the separate assigned adjudicator, who must
also inspect the output, to record a reason and explicit scores. Missing evidence
stays unscored. The system never picks an automatic winner or promotes a provider
grade, publication, recommendation, fallback or execution authority.

Reviewer qualifications/actual independence and separate-source review require
trusted, readonly, audited server adapters. They are unconfigured by default.
Qualification records bind the exact assignment and distinct real-identity
commitments as well as qualification/independence/audit hashes and expiry.
Self-declarations, local hashes and isolated fixtures cannot establish operating
expert/source evidence. Even fully recorded staff judgments therefore remain
unqualified unless those independent current inputs exist. No expert roster,
source bundle, hidden holdout or production review result is fabricated here.

The database reservation proves the recorded application ordering, not independent
chronology, hidden-task access exclusion, representativeness, blinding or unseen
training status. `holdout_status` remains `not_established`. A proper independent
custodian and restricted source/task handling remain operating prerequisites.

Four separate private tables contain signed assignments, disclosures, judgments
and adjudications. Native writer transactions bind current authorization, exact
scope, immutable records and audit; accepted-SQL failure rolls back the bundle.
Source and qualification adapters run outside DB locks and the retained state is
checked again afterward. No raw exception or external source material is exposed
through a shared/public route. The native admin dialog renders selected output
and scores as text and clears state on session/workspace/modal changes. It does
not fetch source URLs, call a model, retry POST automatically or enable commerce.
