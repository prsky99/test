"""Build design-only contracts. Does not import product code or access services."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'docs'


def ref(name):
    return {'$ref': '#/components/schemas/' + name}


def obj(fields, required=None):
    return {'type': 'object', 'additionalProperties': False, 'properties': fields,
            'required': list(fields) if required is None else required}


ID = {'type': 'string', 'format': 'uuid'}
TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 128}
HASH = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
TIME = {'type': 'string', 'format': 'date-time'}
ATOM = {'type': 'string', 'pattern': '^(0|[1-9][0-9]{0,77})$',
        'description': 'Integer atomic units. Server also enforces uint256 maximum.'}
POS = {'type': 'string', 'pattern': '^[1-9][0-9]{0,77}$',
       'description': 'Positive integer atomic units; server enforces uint256 maximum.'}
PROOF = {'type': 'string', 'minLength': 32, 'maxLength': 512}
FRESH = {'fresh_action_id': ID, 'fresh_action_proof': PROOF}
VER = {'type': 'integer', 'minimum': 1}
ASSET = {'type': 'string', 'minLength': 1, 'maxLength': 128}
CATEGORY = {'type': 'string', 'pattern': '^[a-z][a-z0-9_.-]{1,63}$',
            'description': 'Controlled taxonomy ID. Server rejects IDs outside its allowlist; never raw conversation text.'}


def build():
    s = {
        'Error': obj({'error': obj({'code': TEXT, 'message': {'type': 'string', 'maxLength': 240},
                                   'request_id': ID, 'retryable': {'type': 'boolean'}})}),
        'Capabilities': obj({'policy_version': {'const': 'v6.1'}, 'mode': {'const': 'model'},
                             'real_value_enabled': {'const': False},
                             'products': {'type': 'array', 'items': {'const': 'P1'}, 'maxItems': 1},
                             'renderers': {'type': 'array', 'items': {'const': 'platform_text_v1'}, 'maxItems': 1},
                             'external_renderer_enabled': {'const': False}}),
        'AssetView': obj({'asset_id': ASSET, 'namespace': {'const': 'model'},
                          'decimals': {'const': 6}, 'redeemable': {'const': False}}),
        'ChallengeRequest': obj({'action': {'enum': ['set_ad_preferences', 'approve_offer', 'approve_campaign']},
                                 'target_id': ID, 'target_revision_hash': HASH, 'request_digest': HASH}),
        'ChallengeView': obj({'fresh_action_id': ID, 'proof_challenge': PROOF, 'expires_at': TIME,
                              'action': TEXT, 'target_id': ID, 'request_digest': HASH}),
        'PreferencesRequest': obj({**FRESH, 'receive_offers': {'type': 'boolean'},
                                   'context_fields': {'type': 'array', 'uniqueItems': True, 'maxItems': 3,
                                                      'items': {'enum': ['task_category', 'language', 'coarse_region']}},
                                   'max_offers_per_day': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                                   'max_ads_per_campaign_day': {'type': 'integer', 'minimum': 0, 'maximum': 3}}),
        'PreferencesView': obj({'id': ID, 'receive_offers': {'type': 'boolean'},
                                'version': VER, 'revision_hash': HASH, 'effective_at': TIME}),
        'CampaignRequest': obj({'name': {'type': 'string', 'minLength': 1, 'maxLength': 100},
                                'asset_id': ASSET, 'total_budget_atoms': POS, 'daily_budget_atoms': POS,
                                'budget_timezone': {'const': 'UTC'}, 'starts_at': TIME, 'ends_at': TIME,
                                'task_categories': {'type': 'array', 'minItems': 1, 'maxItems': 20,
                                                    'uniqueItems': True, 'items': CATEGORY},
                                'regions': {'type': 'array', 'minItems': 1, 'maxItems': 30, 'uniqueItems': True,
                                            'items': {'type': 'string', 'pattern': '^[A-Z]{2}$'}},
                                'creative_text': {'type': 'string', 'minLength': 1, 'maxLength': 2000},
                                'gross_p1_atoms': POS, 'min_exposure_ms': {'const': 15000},
                                'split_policy_id': {'const': 'default_v5'},
                                'renderer_profile': {'const': 'platform_text_v1'}}),
        'CampaignView': obj({'id': ID, 'advertiser_id': ID, 'version': VER, 'revision_hash': HASH,
                             'state': {'enum': ['draft', 'in_review', 'eligible', 'active', 'paused',
                                                'completed', 'archived', 'rejected', 'suspended']}}),
        'ReviewRequest': obj({'revision_hash': HASH}),
        'ReviewView': obj({'id': ID, 'campaign_id': ID, 'version': VER, 'revision_hash': HASH,
                           'state': {'enum': ['pending', 'eligible', 'eligible_limited', 'rejected']}}),
        'ReviewDecision': obj({'revision_hash': HASH, 'verdict': {'enum': ['eligible', 'rejected']},
                               'reason_code': TEXT, 'evidence_ref': ID}),
        'ApprovalRequest': obj({**FRESH, 'revision_hash': HASH}),
        'RevisionRequest': obj({'revision_hash': HASH}),
        'PauseRequest': obj({'revision_hash': HASH, 'reason_code': TEXT}),
        'DeclineRequest': obj({'reason': {'enum': ['not_relevant', 'not_now', 'withdraw']}}),
        'CancelExposureRequest': obj({'reason': {'enum': ['user_stop', 'consent_withdrawn']}}),
        'OfferRequest': obj({'task_category': CATEGORY, 'language': {'type': 'string', 'minLength': 2, 'maxLength': 32},
                             'coarse_region': {'type': 'string', 'pattern': '^[A-Z]{2}$'},
                             'selection_digest': HASH}),
        'OfferSummary': obj({'id': ID, 'campaign_revision_hash': HASH, 'quote_hash': HASH,
                             'advertiser_name': TEXT, 'asset_id': ASSET, 'user_reward_atoms': POS,
                             'gross_atoms': POS, 'operator_reward_atoms': ATOM,
                             'direct_cost_atoms': ATOM, 'platform_reward_atoms': ATOM,
                             'fees_atoms': {'const': '0'},
                             'use_condition': {'const': 'Model balance for isolated tests; not redeemable.'},
                             'min_exposure_ms': {'const': 15000}, 'wallet_id': ID, 'expires_at': TIME,
                             'state': {'enum': ['reserved', 'consented', 'exposing', 'evidence_pending', 'review_pending',
                                                'awarded', 'declined', 'expired', 'cancelled', 'rejected']},
                             'disclosure': {'const': 'Sponsored offer'}, 'version': VER}),
        'ConsentRequest': obj({**FRESH, 'offer_id': ID, 'quote_hash': HASH}),
        'ConsentView': obj({'id': ID, 'offer_id': ID, 'quote_hash': HASH, 'version': VER, 'created_at': TIME}),
        'ExposureRequest': obj({'offer_id': ID, 'consent_id': ID, 'consent_version': VER}),
        'ExposureView': obj({'id': ID, 'offer_id': ID, 'state': TEXT, 'evidence_deadline': TIME,
                             'next_sequence': {'type': 'integer', 'minimum': 0}, 'next_nonce': PROOF}),
        'CreativeView': obj({'offer_id': ID, 'creative_revision_hash': HASH, 'advertiser_name': TEXT,
                             'disclosure': {'const': 'Advertisement'},
                             'plain_text': {'type': 'string', 'minLength': 1, 'maxLength': 2000}}),
        'EvidenceRequest': obj({'sequence': {'type': 'integer', 'minimum': 0, 'maximum': 300},
                                'nonce': PROOF, 'elapsed_claim_ms': {'type': 'integer', 'minimum': 0, 'maximum': 600000},
                                'visible': {'type': 'boolean'}, 'foreground': {'type': 'boolean'}}),
        'CompleteRequest': obj({'last_sequence': {'type': 'integer', 'minimum': 0, 'maximum': 300}}),
        'OperationView': obj({'id': ID, 'state': {'enum': ['pending', 'running', 'review_pending', 'succeeded', 'failed', 'no_offer']},
                              'resource_id': {'type': ['string', 'null'], 'format': 'uuid'},
                              'resource_type': {'enum': ['offer', 'exposure', 'award', 'none']},
                              'receipt_id': {'type': ['string', 'null'], 'format': 'uuid'},
                              'review_deadline': {'type': ['string', 'null'], 'format': 'date-time'}}),
        'WalletView': obj({'id': ID, 'asset_id': ASSET, 'available_atoms': ATOM, 'locked_atoms': ATOM,
                           'ownership': {'const': 'user_owned'}, 'mode': {'const': 'model'}}),
        'ReceiptView': obj({'id': ID, 'kind': {'const': 'p1_award'}, 'offer_id': ID, 'stage_key': {'const': 'P1'},
                            'asset_id': ASSET, 'user_reward_atoms': POS, 'quote_hash': HASH,
                            'issued_at': TIME, 'signature_state': {'enum': ['pending', 'signed']},
                            'signature': {'type': ['string', 'null'], 'maxLength': 2048}}),
    }
    s['ReceiptView']['allOf'] = [
        {'if': {'properties': {'signature_state': {'const': 'signed'}}},
         'then': {'properties': {'signature': {'type': 'string', 'minLength': 1}}},
         'else': {'properties': {'signature': {'type': 'null'}}}}]
    # method, path, operation ID, request/response schemas, actors, capabilities, human action, conditional version.
    routes = [
        ('get', '/capabilities', 'getCapabilities', None, 'Capabilities', ['public'], [], False, False),
        ('get', '/asset', 'getAsset', None, 'AssetView', ['public'], [], False, False),
        ('post', '/human-challenges', 'createHumanChallenge', 'ChallengeRequest', 'ChallengeView', ['human'], [], False, False),
        ('get', '/ad-preferences', 'getAdPreferences', None, 'PreferencesView', ['human'], [], False, False),
        ('put', '/ad-preferences', 'setAdPreferences', 'PreferencesRequest', 'PreferencesView', ['human'], [], True, True),
        ('post', '/advertisers/{advertiser_id}/campaigns', 'createCampaign', 'CampaignRequest', 'CampaignView', ['human'], ['campaign.edit'], False, False),
        ('get', '/advertisers/{advertiser_id}/campaigns/{campaign_id}', 'getCampaign', None, 'CampaignView', ['human'], ['campaign.read'], False, False),
        ('post', '/advertisers/{advertiser_id}/campaigns/{campaign_id}/review-request', 'requestReview', 'ReviewRequest', 'ReviewView', ['human'], ['campaign.edit'], False, True),
        ('post', '/reviews/{review_id}/decisions', 'decideReview', 'ReviewDecision', 'ReviewView', ['ops'], ['creative.review'], False, True),
        ('get', '/reviews/{review_id}', 'getReview', None, 'ReviewView', ['ops'], ['creative.review'], False, False),
        ('post', '/advertisers/{advertiser_id}/campaigns/{campaign_id}/approvals', 'approveCampaign', 'ApprovalRequest', 'CampaignView', ['human'], ['budget.approve'], True, True),
        ('post', '/advertisers/{advertiser_id}/campaigns/{campaign_id}/activation', 'activateCampaign', 'RevisionRequest', 'CampaignView', ['human'], ['budget.approve'], False, True),
        ('post', '/advertisers/{advertiser_id}/campaigns/{campaign_id}/pause', 'pauseCampaign', 'PauseRequest', 'CampaignView', ['human'], ['campaign.pause'], False, True),
        ('post', '/offers', 'requestOffer', 'OfferRequest', 'OperationView', ['human', 'agent'], ['offers.request'], False, False),
        ('get', '/offers/{offer_id}', 'getOffer', None, 'OfferSummary', ['human', 'agent'], ['offers.read'], False, False),
        ('post', '/offers/{offer_id}/decline', 'declineOffer', 'DeclineRequest', 'OfferSummary', ['human', 'agent'], ['offers.decline'], False, False),
        ('post', '/human-consents', 'approveOffer', 'ConsentRequest', 'ConsentView', ['human'], [], True, False),
        ('post', '/exposure-sessions', 'startExposure', 'ExposureRequest', 'ExposureView', ['human'], [], False, False),
        ('get', '/exposure-sessions/{session_id}/creative', 'getApprovedCreative', None, 'CreativeView', ['human'], [], False, False),
        ('post', '/exposure-sessions/{session_id}/evidence', 'submitEvidence', 'EvidenceRequest', 'ExposureView', ['human'], [], False, False),
        ('post', '/exposure-sessions/{session_id}/complete', 'completeExposure', 'CompleteRequest', 'OperationView', ['human'], [], False, False),
        ('post', '/exposure-sessions/{session_id}/cancel', 'cancelExposure', 'CancelExposureRequest', 'OperationView', ['human'], [], False, False),
        ('get', '/operations/{operation_id}', 'getOperation', None, 'OperationView', ['human', 'agent'], ['operations.read'], False, False),
        ('get', '/wallets/{wallet_id}', 'getWallet', None, 'WalletView', ['human', 'agent'], ['wallet.read'], False, False),
        ('get', '/receipts/{receipt_id}', 'getReceipt', None, 'ReceiptView', ['human', 'agent'], ['receipts.read'], False, False),
    ]
    doc = {'openapi': '3.1.1', 'info': {'title': 'AI AD Coin model P1 design contract', 'version': '6.1.0-design',
             'description': 'Proposed first vertical slice only. Not implemented; no real-value funding or settlement.'},
           'servers': [{'url': '/api/ad-coin/v2'}], 'paths': {},
           'x-status': 'design_only', 'x-release-profile': 'R0_model_p1',
           'x-authentication-conflict-policy': 'Reject mixed human and machine credentials; never select a stronger principal by header order.',
           'components': {'securitySchemes': {
               'HumanSession': {'type': 'apiKey', 'in': 'cookie', 'name': 'adc2_session', 'description': 'Proposed session adapter; principal kind must be human.'},
               'Csrf': {'type': 'apiKey', 'in': 'header', 'name': 'X-CSRF-Token'},
               'AgentKey': {'type': 'apiKey', 'in': 'header', 'name': 'X-Ad-Coin-Agent-Key'},
               'OpsService': {'type': 'http', 'scheme': 'bearer', 'description': 'Purpose-scoped reviewer service token; distinct audience.'},
               'MutualTLS': {'type': 'mutualTLS'}}, 'schemas': s}}
    for method, path, operation_id, req, resp, actors, scopes, fresh, conditional in routes:
        write = method != 'get'
        security = []
        if 'human' in actors:
            security.append({'HumanSession': [], **({'Csrf': []} if write else {})})
        if 'agent' in actors:
            security.append({'AgentKey': []})
        if 'ops' in actors:
            security.append({'OpsService': [], 'MutualTLS': []})
        params = [{'name': key, 'in': 'path', 'required': True, 'schema': ID} for key in re.findall(r'{(\w+)}', path)]
        if write:
            params.append({'name': 'Idempotency-Key', 'in': 'header', 'required': True,
                           'schema': {'type': 'string', 'minLength': 16, 'maxLength': 128}})
        if conditional:
            params.append({'name': 'If-Match', 'in': 'header', 'required': True, 'schema': TEXT,
                           'description': 'Current opaque object version; rejected if stale.'})
        async_result = operation_id in ('requestOffer', 'completeExposure', 'cancelExposure')
        responses = {('202' if async_result else '200'): {'description': 'Accepted for processing; inspect operation.' if async_result else 'Authorized resource result.',
                          'headers': {'Cache-Control': {'schema': {'type': 'string', 'const': 'no-store'}}},
                          'content': {'application/json': {'schema': ref(resp)}}},
                     'default': {'description': 'Safe error; no internal diagnostic details.', 'content': {'application/json': {'schema': ref('Error')}}}}
        if resp in ('CampaignView', 'ReviewView', 'PreferencesView'):
            responses['200']['headers']['ETag'] = {'schema': {'type': 'string'}, 'description': 'Opaque version for If-Match.'}
        op = {'operationId': operation_id, 'security': security, 'parameters': params, 'responses': responses,
              'x-principal-kinds': actors, 'x-capabilities': scopes, 'x-human-only': actors == ['human'],
              'x-fresh-action-required': fresh, 'x-object-authorization': 'server-bound owner and tenant; never body actor',
              'x-idempotency-required': write,
              'x-authorization-on-replay': True}
        if req:
            op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': ref(req)}}}
        if 'ops' in actors:
            op['x-ingress'] = 'restricted_review_service_only'
        if operation_id == 'getApprovedCreative':
            op['x-precondition'] = 'Active owner-bound consent/session; no creative before consent.'
        doc['paths'].setdefault(path, {})[method] = op

    module_policies = {
        'M01': [3, 11, 15, 18, 35, 37], 'M02': [1, 5, 6, 7, 8, 9, 10, 21, 22, 26, 28, 31],
        'M03': [4, 11, 12, 17, 31, 32, 33, 35, 37], 'M04': [12, 16, 21, 22, 23, 24],
        'M05': [16, 23], 'M06': [23, 38], 'M07': [13, 14, 17, 34],
        'M08': [18, 19, 20, 36], 'M09': [2, 5, 20, 25, 27, 29, 30, 38]}
    work_policies = {
        'WP-01': [2, 3, 11, 15, 18, 35, 37], 'WP-02': [2, 12, 21, 22, 23, 24, 29, 30],
        'WP-03': [1, 3, 5, 6, 7, 8, 9, 10, 21, 22, 26, 28, 31],
        'WP-04': [2, 11, 12, 16, 17, 18, 20, 32, 35, 37], 'WP-05': [15, 16, 23, 24],
        'WP-06': [2, 23, 27, 29, 38], 'WP-07': [4, 5, 7, 9, 10, 20, 25, 31, 32, 37],
        'WP-08': [8, 11, 12, 21, 33, 35], 'WP-09': [13, 14, 17, 18, 28, 34],
        'WP-10': [6, 14, 15, 25, 26, 28, 37], 'WP-11': [3, 18, 19, 20, 27, 36],
        'WP-12': [2, 24, 27, 29, 30, 38]}
    dependencies = {'WP-01': [], 'WP-02': ['WP-01'], 'WP-03': ['WP-02'], 'WP-04': ['WP-03'],
                    'WP-05': ['WP-02', 'WP-04'], 'WP-06': ['WP-01', 'WP-02'],
                    'WP-07': ['WP-04'], 'WP-08': ['WP-04', 'WP-07'], 'WP-09': ['WP-04'],
                    'WP-10': ['WP-03', 'WP-09'], 'WP-11': ['WP-03', 'WP-09'],
                    'WP-12': ['WP-01', 'WP-02', 'WP-03', 'WP-04']}
    roadmap = (DOCS/'AD_COIN_PLATFORM_ROADMAP.md').read_text()
    gate_trace = {}
    for gate, line in re.findall(r'^- \*\*(GROW-\d{2})\*\* (.+)$', roadmap, re.M):
        refs = []
        for n, tail in re.findall(r'PLAT-(\d{2})((?:·\d{2})*)', line):
            refs.extend('PLAT-'+i for i in [n, *re.findall(r'·(\d{2})', tail)])
        gate_trace[gate] = refs
    trace = {f'PLAT-{n:02}': {'modules': [m for m, ns in module_policies.items() if n in ns],
                             'work_packages': [w for w, ns in work_policies.items() if n in ns],
                             'planned_gates': [g for g, ns in gate_trace.items() if f'PLAT-{n:02}' in ns]}
             for n in range(1, 39)}
    spec = {'profile': 'ai-ad-coin-platform-design-v6.1', 'date_kst': '2026-11-07',
            'status': 'design_only', 'real_value_enabled': False, 'product_acceptance_passes_claimed': 0,
            'documents': ['AD_COIN_PLATFORM_ARCHITECTURE.md', 'AD_COIN_PLATFORM_DATA_API.md',
                          'AD_COIN_PLATFORM_IMPLEMENTATION_PLAN.md', 'AD_COIN_PLATFORM_POLICY.md',
                          'AD_COIN_ARCHITECTURE.md', 'ad_coin_platform_p1.openapi.json'],
            'inherited_asset_spec': 'ad_coin_v5_spec.json',
            'decisions': [f'DEC-{n:02}' for n in range(1, 8)],
            'reference_profile': {'model_asset': True, 'decimals': 6, 'initial_supply_atoms': '0',
                                  'uint256_max': str(2**256-1), 'min_exposure_ms': 15000,
                                  'offer_ttl_seconds': 300, 'evidence_ttl_seconds': 600,
                                  'review_max_seconds': 86400, 'max_parallel_offers_per_owner': 2,
                                  'max_campaign_ads_per_owner_day': 3, 'max_offers_per_owner_day': 10,
                                  'max_relay_hops': 3, 'statistics_min_distinct_users': 50,
                                  'statistics_min_advertisers': 5,
                                  'split_bps': {'user': 5000, 'operator': 1000, 'direct': 1500, 'platform': 2500},
                                  'reference_values_are_not_security_certification': True},
            'operation_catalog': [{'id': r[2], 'method': r[0].upper(), 'path': r[1], 'actors': r[5],
                                    'fresh_action_required': r[7]} for r in routes],
            'policy_trace': trace, 'planned_gates': gate_trace,
            'work_dependencies': dependencies,
            'states': {'offer_base_p1': {
                'reserved': {'consent': 'consented', 'decline': 'declined', 'expire': 'expired'},
                'consented': {'start': 'exposing', 'withdraw': 'cancelled', 'expire_before_start': 'expired'},
                'exposing': {'submit_completion': 'evidence_pending', 'cancel_before_qualified': 'cancelled'},
                'evidence_pending': {'accept_and_post': 'awarded', 'reject': 'rejected', 'review': 'review_pending'},
                'review_pending': {'accept_and_post': 'awarded', 'reject': 'rejected'},
                'awarded': {}, 'declined': {}, 'expired': {}, 'cancelled': {}, 'rejected': {}}},
            'money_guards': ['same_asset_only', 'all_beneficial_balances_nonnegative', 'journal_sum_zero',
                             'economic_event_unique', 'owner_tenant_bound', 'campaign_total_and_day_caps_atomic',
                             'pending_verdict_holds_not_expired', 'R_ge_S_and_C_ge_B_at_same_checkpoint'],
            'release_profiles': {'R0_model_p1': {'real_value': False, 'work_packages': ['WP-01','WP-02','WP-03','WP-04','WP-12']},
                                 'R1_agent_utility': {'real_value': False, 'requires': ['R0_model_p1'], 'adds': ['WP-05']},
                                 'R2_collateral_backed_p1': {'real_value': 'activation_gated', 'requires': ['R0_model_p1'],
                                                            'adds': ['WP-06'], 'v5_acceptance_and_legal_required': True},
                                 'R3_open_network': {'requires': ['R2_collateral_backed_p1'], 'adds': ['WP-07','WP-08','WP-09','WP-10']},
                                 'R4_intelligence_global': {'requires': ['R3_open_network'], 'adds': ['WP-11']}},
            'real_value_activation_required': ['chain_and_official_addresses', 'issuer_and_custodian', 'jurisdiction_and_reserve_eligibility',
                                                'redemption_and_customer_rights', 'AML_and_sanctions', 'risk_limits_and_fees',
                                                'independent_security_audit', 'key_separation_and_recovery', 'v5_and_release_acceptance_evidence']}
    (DOCS/'ad_coin_platform_p1.openapi.json').write_text(json.dumps(doc, indent=2)+'\n')
    (DOCS/'ad_coin_platform_v6_1_spec.json').write_text(json.dumps(spec, indent=2)+'\n')
    return doc, spec


if __name__ == '__main__':
    doc, spec = build()
    print(json.dumps({'design_operations': len(spec['operation_catalog']), 'schemas': len(doc['components']['schemas']),
                      'policy_mappings': len(spec['policy_trace']), 'status': 'design_only'}))
