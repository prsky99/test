"""Campaign review by platform operators (PM step 2, option A: review on the operator screen).

The original review needs a REVIEWER principal with verified mTLS, which production cannot issue.
Until it can, a platform operator (platform.operate) decides pending reviews on /ad-coin/v2/admin.
The decision goes through the same review evidence and state machine (Commercial.record_evidence and
Commercial._decide): evidence is a digest of the operator's decision, and the reviewer is the operator.
"""

import hashlib
import json
import re

from .commercial import etag
from .contracts import ContractError
from .ledger import identifier

VERDICTS = ("eligible", "rejected")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


def pending_reviews(commercial, principal, *, limit=50):
    commercial.access.require_operator(principal)
    with commercial.store.atomic():
        rows = commercial.store.all("reviews_pending_for_operator", (limit,))
    items = []
    for row in rows:
        payload = json.loads(row["payload_json"])
        items.append({"review_id": row["id"], "campaign_id": row["campaign_id"], "advertiser_id": row["advertiser_id"],
                      "name": str(payload.get("name", ""))[:100], "text": str(payload.get("creative_text", ""))[:2000],
                      "task_categories": list(payload.get("task_categories", ()))[:20],
                      "regions": list(payload.get("regions", ()))[:20]})
    return {"items": items}


def decide(commercial, principal, review_id, *, verdict, reason_code):
    """eligible or rejected, once; the campaign then follows the normal approval and activation."""
    commercial.access.require_operator(principal)
    if verdict not in VERDICTS or type(reason_code) is not str or not _REASON.match(reason_code):
        raise ContractError("invalid_review_decision", 422)
    review_id = identifier(review_id)
    digest = hashlib.sha256(json.dumps({"review_id": review_id, "verdict": verdict, "reason_code": reason_code,
                                        "operator": str(principal.id)}, sort_keys=True).encode()).hexdigest()
    store = commercial.store
    with store.atomic():
        review = commercial._review(review_id)
        commercial.access.guards.current(review["advertiser_id"])
        evidence_ref = commercial.record_evidence(review_id, digest)
        store.lock("2:campaign:" + review["campaign_id"])
        campaign = commercial._campaign(review["campaign_id"], True)
        view = commercial._review_view(commercial._review(review_id, True))
        body = {"revision_hash": view["revision_hash"], "verdict": verdict, "reason_code": reason_code,
                "evidence_ref": evidence_ref}
        return commercial._decide(principal, campaign, review_id, body, etag(view))
