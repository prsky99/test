# Peer handoff — restart continuation

Review `verification.json` with the previous nine-step/42-requirement acceptance
package. The broad diagnostic is5761 pass/5 fail; all five failing cases have
passing complete-module retests. No frozen319-module whole acceptance is claimed.

Review three owned changes: publication coverage in check_front_content.py;
mandatory test_pearl_* regression selection; staged_publication and build_en.py
wrapper. Rendering failure must preserve the previous served tree. Index may
never be replaced by the transient design preview. Completed file replacement
is atomic per file, not transactional across all asset generations.

Reproduce using the project interpreter: tests/test_pearl_publication.py,
tests/test_front_regression_shards.py, and the current affected browser modules.
The source hashes, precise case XML and complete disposable builder rehearsal
are linked in verification.json. The running server was neither restarted nor
replaced; only read-only public navigation/API and admin denial checks ran.

The new builder helper is used by future invocations of new/build_en.py. No
operating publication was rebuilt here. Changes to verification tools and this
offline builder do not require another server restart. A rollback of this
continuation is source-only; preserve operating DBs, sessions, credentials and
grants. Reverting the staging wrapper would reintroduce transient preview risk.

Await final-source confirmation after other frontend edits before final broad
acceptance. Original external HTTPS/SDK/Push/recovery, A2A/evaluation, HA/DR,
payment eligibility, hosted CI and peer conditions remain. ChatGPT inference
remains held. Public Workspace activation still needs the user's final request.
