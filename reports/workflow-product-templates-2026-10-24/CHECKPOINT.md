# Active objective

User authorizes activating fallback, creating varied real-service workflows and
publishing only templates that pass actual fallback tests. Do not publish fixture
or normal-only successes as fallback-tested products. Do not promise no failures.
No server deployment/restart by agent per AGENTS; isolated apps/TCP/DBs allowed.
No subagents requested. Preserve large dirty baseline and user changes.

Baseline generic I/O sources deployed in all3roles13/13 hashes verified in
reports/agent-fallback-validation-2026-10-24/generic-io-post-restart.json.
Operating controls false/rev0, policies0, profiles0. Existing approvals only
PaperFinder34807/search_papers andOwnedResearch133019/search_research_papers;
shared Crossref so not an independent pair. Generic I/O table already installed.
Current default R06 supports only news/docs informational MCP, 10%/100runs/24h
canary; compiler/publication explicitly refuse generic transform/composition mix.
Need product acceptance/publication lifecycle, not just is_template flip.

This turn CUA getState timed out32s again; no login session or browser profile
scraping. Authenticated operating UI currently unavailable. No operating writes
yet in this turn. All previous tests are preserved, do not add their counts.

Next first blocker: reviewed PaperFinder search_arxiv uses exact category regex
^[a-z][a-z-]*(\\.[A-Za-z-]+)?$ with maxLength30. Existing offline validator refuses
allpatterns. Implement narrowly reviewed bounded validation (no arbitrary regex,
no schema stripping) then isolated actual native calls before expanding products.
Primary OwnedResearch reallylocal->Crossref, alternate arXiv-only remote must have
actual source/operator/host review. Samehost/shared-upstream guard stays. Never
claim a schema conversion proves semantic/infrastructure independence.

Research opened official JSONSchema regex docs, OWASP ReDoS, tools.openkrill.app
support; cite links in eventual report. Actual live provider work still pending.

Progress:concierge/execution_policy.py now narrowly supports only reviewed category regex withtype string,maxLength<=30; other patterns/refs remain denied. tests/test_reviewed_schema_pattern.py27passed. Genericengine added get_root andenglish guard; IOProfiles provenance recognizes root reads. Fixed capability_registry projection to accept generic evidence only backed bycurrent signed I/Oprofile (IOProfiles.verified_evidence); otherwise fixedadapter dataset would wronglydeny owned research. Foundation selected94passed. Blueprint module workflow_product_blueprints.py defines3real distinct research-usecase candidates:ResearchSearchAPI,ResearchComparisonBoard(twoagents reciprocalpairs),SourceBibliographyAPI. No fake scientific synthesis/authors. No source publication code yet.
Nativeprobe actualarxiv2queries2records each(~2.5sec) source arXiv; local Crossref onequery2records(~0.7sec),batteryrecyclingqueryUPSTREAM_TOOL_ERROR. Source publicTLS/SSRF bounds intact. Files paper-tools-current.json,research-native-results.json.
exercise_products.py runsactualdata+controlledfaults in private disposable DB, separatekey. Initial all3config failedbecause rawPostgresdetailsTEXT was doubleJSONencoded bySQLiteupsert; correctedscript JSONdecode, guardunchanged. live-product-run-normalized.txt/live-product-tests.json now3/3pass:normalworkflowssucceeded, Crossref-source-unavailableinjection =>actual arXiv2realrecords, 1switch/search. Comparison reverse Paper preflightunavailable =>Crossref realcalls,succeeded1switch. Bothsources unavailable singlesfail safelyexpected notfake success. Sandbox selection samplingforced0onlylab (explicitreport),nooperatingwrites/templates/profiles. Actualproviders are real;faultscontrolled,notclaimexternalserverstopped. Need strengthened operator/product gate beforepublishing, notis_template flip.
Design next: product acceptance/publication module/table boundgraph+pairs+I/Ohash andnormal+controlledlivefaultproof; expirywithdrawal. Current R06canary10%/100/24h andpublic_template rejectsIOnodes so cannothonestlypublishproductiongoods yet. Needactiveprotectedmode gatedtestproof100% explicitperrunoptin, boundedcapacity/expiry (nozero-failureguarantee). Need dynamic productrequest per-run snapshot (do NOTmutatenodeinputandbreakpolicygraphfingerprint) andpublicprojection hidesrecipes/profileIDs. Admin/SDKcurrentappsallow_fallbackwebappunsupported; avoidfalseclaimexistingdownloadfallbackworks. Proposed dedicatedproductpublicAPI+inputschema gateway pack. Source deployment3roles mustuserperformonceafterallbatchcomplete;noagentserverrestart. CUAagaingetState32stimeoutthisturn =>noauthenticatedUI; do notscrapebrowserprofiles orimpersonatenamedstaff. TrustedownerCLIcouldperformauthorizedlocaladminopswithprivateconfigguard andactor0serviceaudit (userexplicitactivate/test/register);noCLI implementedyet. Prefer clear limitedscope to inventingblanketreadiness.

Final source milestone: Products lifecycle wired into runtime and explicit per-run
snapshot inputs; protected active mode (100% opt-in, <=1000, <=24h) cannot downgrade
to baseline. Both shell/Pearl publication regenerated; English product ZIPs and
authenticated admin download path added. Source-limit investigation found actual
Crossref429 on second list query, matching official1/s/concurrency1 list limits.
New source_limits.py serializes/paces calls, bounded cooldown, no automatic retries.
Paced live qualification3/3 passed,4controlled outage runs, public changed-input
runs3/3, repeat command reused products without new runs; all in disposable DB.
New source tables installed: reviewed emptyworkflow_product_templates only;
Postgres18.6 native8checks passed, sourcecatalog231tables/3711statements current.
Consolidatedpytest302passed +fourCLIguards+oneadminAPIcase =307unique cases;
latestproductCLI23overlapsdo notaddagain. Focusedruff/syntax pass;252publicfiles
0violations. No servers/deploymentschanged. Operatingreadonlygate confirms
fallbackoff/rev0,products0; mismatched oldsource rejects before mutation.
Next REQUIRED: user batchpackage/deploy frontend,admin,jobs,execution to one new
release per README. Then run scripts.qualify_workflow_products check/apply with
explicit provided flags (alreadyuserauthorized) and inspect operating hub/run/ZIP.
Do not treat disposableIDs4/5/6orreportZIPs asoperatingregistration. No further
source task planned before operating rollout; onlyfix actualnewfailures. Preserve
dirtybaseline. Userownsservers;donotdeploy/restartautomatically. Full scope,
validation, failurehistory andboundedlimits in README.md/docs/WORKFLOW_PRODUCTS.md.

Post-deploy follow-up: all four roles runworkflow-products-20261024-v1;21/21
critical filesmatch each. Activefrontend/adminBready;bothworkerprocessesrunning.
HTTPtemplates200(products0),Pearlruntime200matches,adminpage200. Operating
qualification notstarted: PostgreSQLmax_connections24/reserved3,all21appslots
occupied (20idle,1idle-in-transaction). OrdinaryconfiguredDSNgetsFATALremaining
slotsreserved. ReservedOSownerconnectionusedONLYforclusterread-onlydiagnostics,
notappwritesorconfigurationchanges. OldretainedfrontendA28133/adminA30180are
stillrunning,drained(active_requests0). Askeduserexplicitapproval viaasyncquestion
tostopONLYinactiveA2services;AGENTforbidsserverstopwithoutrequest. ActiveB,
DBserverandoldreleasefilesremain. Pendinganswer. No newapplicationwrites,
fallback/registrationremain0. Nextifapproved: recheckstateAinactive+drained, use
Deployment.stop(role,'a',timeout<=55)sequentially underdeploymentlock(noforcekill),
thenretryguardedreadinessCLI andactualqualify--applyflags, inspectactualhub/runZIP.
Do NOTrestart/redeployfourrolesagain orterminateunknownDBsessions. Evidence
post-deploy-readiness.json/post-deploy-http.json/operating-readiness.txt.

Later operating milestone/supersedes earlier pending slot request: user approved
ONLY oldinactiveA2stops; completedfrontend28133/admin30180, activeBready. Ordinary
DBconnectionrestored. CLIworker guard falselyexpectedheartbeat.release (absent);
fixedRootScriptCLI only: actualPIDcommand+manifest+freshheartbeat checks; readynow.
NativeRegistry.approve optionalSQLiteBEGINguardfailsinnativePGtransaction;
RootScriptownerprepare_owner_approval usesstandardvalidatedinternalAPIwithin
nativeowner-checkedwritertransaction andaudit, preservingexistingapprovals.
Initialnative operatingqualify passed3 andregistered41,42,43;actualpublicworker
changed-input tests ALLfailedUPSTREAM_PROTOCOL,firstownedattemptunknown/uncertain.
Realbrowser screenshot alsofailed despiteinitialloading-onlyassertion(passflag
corrected/scriptnowrequiresterminalsucceeded). NativeCLIhadnotloadedEdgeenv;
workerdoes. OwnedMCPwasoffloadedthroughpublicEdgeHTTP,notlocalhandler. Noauto
native replay(correct). WithdrewONLYnewproducts41..43(is_template0),globalfallback
paused(owneractualaudit),oldunknownrunsevidencepreserved. Operatingdelivery-
withdrawal.json authoritativecurrentstate (notinitialqualificationJSON).
Preparedfixedge_gateway/native.py: earlyis_owned(resource)returnsNonebeforeany
Edgeadmission/ticket/dispatch;ordinaryMcpProxythenvalidates&useslocalbinding.
CLIloadsidenticalEdgeenv,sourceguardextraNativehashONLYexecutionrole(otherroles
common21same),requalify_withdrawn regeneratesproofsandrepublishesSAMEIDs after
freshsuccess,notcreatenewtemplates. Newoperatorandedgefixturetests47passed;
broaderEdge+local+products+CLI96passedexit0. Staticpassedstandardfixtureexemptions,
SQLcatalogcheckunchanged231/3711. No sourceruntimeotherthanNativechanged; no
publicUIchange. Next REQUIREDuser ONLYpackagev2 +worker-deploy executionv2; no
frontend/admin/jobs/DB restart. OnceconfirmedrunqualifyCLIcheck/applyflags(which
repairswithdrawnIDs),publicHTTPchangedinputs/browserterminalsuccess/ZIPverify.
Do notsaycomplete/currentlyregistereduntilACTUALpublicverificationpasses. Do
notreplayoldunknownrequests orstopactiveservices. CLIandharnesssourceRootScript
changesneednoserverdeploy. Last96testsandREADMEaddendumcontainstatus/evidence.

FINAL v2 operating acceptance: user deployedexecutionv2; sourceRolecheckinitial
blockedunrelatedFinancewiringinRootdashboard.py. Keptuserchange;RootCLIsource
scopepinsALLmodule setup+router/auth/auditbootstrap+product/exportfunctions,
frozenwholefilehashintegrityalwaysrequired;scopepositive/negative12CLItestspass.
Adminhasotheruserreleaseweb-20261024-221110-0bb8;compatiblecriticalcodeverified.
QualifiedSAMEIDs41,42,43withserviceEdgeenv;normal+fourcontrolledoutagespassed;
publicAPIchangedquantum/solar/batteryinputsALLsucceeded3.0/5.6/3.3sec2/4/2English
records. Verifierinitiallyexpectedpublicinputlogs(whichareintentionallyhidden);
correctedread-onlyprivateauditsforinputverification,notAPIleak. HTTPSactualsite
Chromeall3choices/input/consent/loading,terminalSUCCEEDED1.4s,andZIPdownloadpass.
ExportedZIPappsall3testedunderseparateemulatedstaticoriginwithREALHTTPSgateway,
CORS202POST/200status,2/4/2records,consentreset,0capturedJSexceptions/failedrequests.
FinalnativeDBauditfallbackenabledrev3,policiesACTIVE100%optin/max1000,4private
casesexactly1successfulalternateeach,ownedEdgepacketsSINCEv2qualificationZERO.
Allthreeis_template1. Oldunknownrunsnotreplayed. ExpiryKST2026-10-25:
41=20:27:54,42=20:28:02,43=20:28:18;boundedapprovalsnotpermanent/autorenewed.
FINALauthorityreportOPERATING_V2.md;validation-summary.jsonstatusactive_and_publicly_verified;
READMEheaderupdatedhistorysuperseded. No further source/server action neededfor
thisbatch. Useralreadyapproved/completedonlyinactiveAretirementandworker_v2;
doNOTrestartotherroles. Futureexpiryrenewalisanoperatingcondition,notclaimof
perpetualSLA. Actualapphostingemulatedcustomerorigin(browserroute),notexternal
serverdeployment. No secrets/runkeys saved. Finishwithconcise Korean outcome,
3names/IDs/link#workflows,testsandsignedexpiry/1000capifmaterial. No new permission
question orbroaderimprovementbacklog. Preservehugeuserdirtybaseline/financework.
