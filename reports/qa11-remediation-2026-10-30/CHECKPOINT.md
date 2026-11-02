# QA11 checkpoint — 2026-10-30 KST

User explicitly approved exact qa11-remediation-frontend/admin-20261030-r1. Both DEPLOYED active a; authenticated probes pass; prior QA10 r1 retained b. Jobs74786/execution75010/proxy79397 unchanged. Worker unchanged. No schema change. deployment-after-status/readiness JSON saved.

Postdeployment: status monitor178/178 HTTP200; publicAPI20/20; actual examplesAPI5/5 real success0.713–2.153s. IAB mcp query45→LoadMore90 loaderfinished. News firstUIattemptfailed generic unavailable; sameinputretrycompleted gateway838.2ms/total2.0s; Researchcompleted1387.6ms/2.1s. Honest screenshots: live-test-completed.jpg FAILURE; live-test-success.jpg NEWS SUCCESS; live-research-success.jpg RESEARCH SUCCESS; live-explore-load-more.jpg. ActualUI failurescope documented, preciseupstreamcause unresolved.

HTTP13searchsamplesmedian.424s,max5.927(firstregional;repeat.388); coldtail remains. Extra cachepartition/compactnegativefilter readOnlybench small4–7%gains rejected and experimentalroot edits reverted to deployedr1. No r2prepared/deployed. 140 experimentaltests passed before reverting, not counted as releasevalidation.

OwnedAPIQA visitor1/messages8/interest1 verifiedID/hash/time, privatebackedup+removed; otherusers untouched. No payment, externalwrite, credentials, fakehistoricalreport edits. Reports/candidates/OPERATIONS now markapplied+limits. Remainingfinal: conciseuserresult with report link+inlineproofimage; donotclaimalllatency/availability solved. No additionaldeploymentapprovalneeded tofinish currentapproveddeployment.
