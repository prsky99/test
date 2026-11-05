"""Advertiser console for AI AD Coin: accounts, members, campaigns, creatives,
review and appeals, budgets and schedules, reports, statements and history.

Modelled on Google Ads review statuses (Under review, Eligible, Eligible
(limited), Disapproved, appeals) with stricter money rules: a day never spends
more than its daily budget, budgets are pre-funded escrow, and invalid activity
is refunded by the platform without taking coins back from people.
Every read and write is scoped to an advertiser the actor belongs to.
"""
import csv
import io
import json
import re
import uuid
from urllib.parse import urlsplit

from . import ledger as L
from .config import COIN_VALUE_WON, FREQUENCY_CAP_PER_DAY
from .db import dumps, now
from .exchange import CATEGORY, task_floor_won
from .screening import ScreeningRejected, findings, normalize, screen_creative
from .service import _day, AdCoinError, BLOCKED_CATEGORIES, PRODUCTS, PUBLIC_URL, day_start

ROLES = {'viewer': 1, 'editor': 2, 'owner': 3}
CAMPAIGN_STATUS = ('enabled', 'paused', 'removed')
REVIEW_FOR_SERVING = ('eligible', 'eligible_limited')
SENSITIVE = re.compile(r'\b(guarantee[sd]?|risk[- ]free|get rich|free money|loan|casino|bet(ting)?|crypto|'
                       r'forex|miracle|cure[sd]?|weight loss)\b', re.IGNORECASE)
DAY = 86400
MAX_REPORT_DAYS = 90
MAX_NAME = 80


def _owner_ok(actor):
    return actor == 'admin'


def _host(url):
    try:
        host = urlsplit(url).hostname or ''
    except ValueError:
        return ''
    return host[4:] if host.startswith('www.') else host


class AdvertiserConsole:
    def __init__(self, service, people):
        self.svc = service
        self.db = service.db
        self.people = people

    # ---------- helpers ----------
    def _log(self, db, advertiser_id, actor, action, object_ref, detail=None):
        db.execute('INSERT INTO ad_coin_change_log VALUES (?,?,?,?,?,?,?)',
                   ('l_' + uuid.uuid4().hex[:20], advertiser_id, actor, action, object_ref,
                    dumps(detail or {}), now()))

    def role(self, advertiser_id, actor):
        if actor == 'admin':
            return 'owner'
        row = self.db.one('SELECT role FROM ad_coin_advertiser_members WHERE advertiser_id=? AND customer_id=? '
                          'AND revoked_at IS NULL', (advertiser_id, actor))
        return row['role'] if row else None

    def _require(self, advertiser_id, actor, need):
        role = self.role(advertiser_id, actor)
        advertiser = self.db.one('SELECT * FROM ad_coin_advertisers WHERE id=?', (advertiser_id,))
        if not advertiser or not role:
            raise AdCoinError('unknown_advertiser', 'No such advertiser account for you.', 404)
        if ROLES[role] < ROLES[need]:
            raise AdCoinError('role_required', 'This needs the %s role.' % need, 403)
        if advertiser['status'] != 'active' and need != 'viewer' and actor != 'admin':
            raise AdCoinError('advertiser_suspended', 'This advertiser account is suspended.', 403)
        return advertiser

    def _campaign_of(self, advertiser_id, campaign_id):
        meta = self.db.one('SELECT * FROM ad_coin_campaign_meta WHERE campaign_id=? AND advertiser_id=?',
                           (campaign_id, advertiser_id))
        if not meta:
            raise AdCoinError('unknown_campaign', 'No such campaign in this account.', 404)
        return meta

    @staticmethod
    def _text(value, limit, name):
        try:
            value = normalize(value)
        except ScreeningRejected:
            raise AdCoinError('invalid_' + name) from None
        if not value or len(value) > limit:
            raise AdCoinError('invalid_' + name)
        if findings(value):
            raise AdCoinError('invalid_' + name, 'Remove instructions, safety claims or wallet requests.')
        return value

    # ---------- accounts and members ----------
    def create_advertiser(self, actor, *, name, website):
        if actor != 'admin' and not self.people.invited(actor):
            raise AdCoinError('invitation_required', 'Only invited accounts can open an advertiser account.', 403)
        name = self._text(name, MAX_NAME, 'name')
        if type(website) is not str or not PUBLIC_URL.fullmatch(website):
            raise AdCoinError('invalid_website', 'Use the https address of your business website.')
        if actor != 'admin':
            owned = self.db.one("SELECT COUNT(*) AS n FROM ad_coin_advertiser_members WHERE customer_id=? AND "
                                "role='owner' AND revoked_at IS NULL", (actor,))['n']
            if owned >= 5:
                raise AdCoinError('advertiser_limit', 'One person can own at most 5 advertiser accounts.', 409)
        advertiser_id = 'adv_' + uuid.uuid4().hex[:16]
        with self.db.transaction() as db:
            db.execute('INSERT INTO ad_coin_advertisers VALUES (?,?,?,?,?,?,?)',
                       (advertiser_id, name, website, 'active', 'unverified', actor, now()))
            if actor != 'admin':
                db.execute('INSERT INTO ad_coin_advertiser_members VALUES (?,?,?,?,NULL)',
                           (advertiser_id, actor, 'owner', now()))
            self._log(db, advertiser_id, actor, 'advertiser.created', advertiser_id, {'name': name})
        return self.advertiser(advertiser_id, actor)

    def advertiser(self, advertiser_id, actor):
        row = self._require(advertiser_id, actor, 'viewer')
        return {'id': row['id'], 'name': row['name'], 'website': row['website'], 'status': row['status'],
                'verification': row['verification'], 'role': self.role(advertiser_id, actor),
                'limited_daily_won': None if row['verification'] == 'verified' else 20_000}

    def advertisers(self, actor):
        if actor == 'admin':
            rows = self.db.all('SELECT id FROM ad_coin_advertisers ORDER BY created_at')
        else:
            rows = self.db.all('SELECT m.advertiser_id AS id FROM ad_coin_advertiser_members m WHERE '
                               'm.customer_id=? AND m.revoked_at IS NULL ORDER BY m.created_at', (actor,))
        return [self.advertiser(r['id'], actor) for r in rows]

    def set_member(self, advertiser_id, actor, customer_id, role):
        self._require(advertiser_id, actor, 'owner')
        if role not in ROLES and role != 'removed':
            raise AdCoinError('invalid_role')
        if type(customer_id) is not str or not re.fullmatch(r'[A-Za-z0-9_:-]{3,100}', customer_id):
            raise AdCoinError('invalid_customer')
        if customer_id == actor and role != 'owner':
            owners = self.db.one("SELECT COUNT(*) AS n FROM ad_coin_advertiser_members WHERE advertiser_id=? AND "
                                 "role='owner' AND revoked_at IS NULL", (advertiser_id,))['n']
            if owners <= 1:
                raise AdCoinError('last_owner', 'Add another owner before changing your own role.', 409)
        with self.db.transaction() as db:
            if role == 'removed':
                db.execute('UPDATE ad_coin_advertiser_members SET revoked_at=? WHERE advertiser_id=? AND '
                           'customer_id=? AND revoked_at IS NULL', (now(), advertiser_id, customer_id))
            else:
                db.execute('INSERT INTO ad_coin_advertiser_members VALUES (?,?,?,?,NULL) ON CONFLICT(advertiser_id, '
                           'customer_id) DO UPDATE SET role=excluded.role, revoked_at=NULL',
                           (advertiser_id, customer_id, role, now()))
            self._log(db, advertiser_id, actor, 'member.' + role, customer_id)
        return self.members(advertiser_id, actor)

    def members(self, advertiser_id, actor):
        self._require(advertiser_id, actor, 'viewer')
        rows = self.db.all('SELECT customer_id, role FROM ad_coin_advertiser_members WHERE advertiser_id=? AND '
                           'revoked_at IS NULL ORDER BY created_at', (advertiser_id,))
        return [{'customer_id': r['customer_id'], 'role': r['role']} for r in rows]

    # ---------- review ----------
    def _review(self, advertiser, creative):
        """Automated review. Returns (status, note)."""
        try:
            screen_creative(creative['title'], creative['body'], creative['question'], creative['answer'])
        except ScreeningRejected as exc:
            return 'disapproved', 'Policy: ' + ', '.join(exc.reasons)
        text = ' '.join(creative[k] for k in ('title', 'body', 'question'))
        if SENSITIVE.search(text):
            return 'under_review', 'Sensitive claim; a person reviews it within one business day.'
        if _host(creative['public_url']) != _host(advertiser['website']) and \
                not _host(creative['public_url']).endswith('.' + _host(advertiser['website'])):
            return 'under_review', 'The public copy is not on your website; a person checks it.'
        if advertiser['verification'] != 'verified':
            return 'eligible_limited', 'Advertiser not verified yet: serving is limited to 20,000 won a day.'
        return 'eligible', ''

    def _refresh_campaign_review(self, db, campaign_id):
        rows = db.execute('SELECT review_status FROM ad_coin_creatives WHERE campaign_id=? AND removed_at IS NULL',
                          (campaign_id,)).fetchall()
        states = [r['review_status'] for r in rows]
        if 'eligible' in states:
            status = 'eligible'
        elif 'eligible_limited' in states:
            status = 'eligible_limited'
        elif 'under_review' in states:
            status = 'under_review'
        elif states:
            status = 'disapproved'
        else:
            status = 'draft'
        db.execute('UPDATE ad_coin_campaign_meta SET review_status=?, updated_at=? WHERE campaign_id=?',
                   (status, now(), campaign_id))
        return status

    def _creative_fields(self, data):
        fields = {}
        for key, limit in (('title', 80), ('body', 400), ('question', 160), ('answer', 40)):
            value = data.get(key)
            if type(value) is not str or not value.strip() or len(value) > limit:
                raise AdCoinError('invalid_' + key)
            fields[key] = value
        url = data.get('public_url')
        if type(url) is not str or not PUBLIC_URL.fullmatch(url):
            raise AdCoinError('invalid_public_url', 'A public https copy of the ad is required.')
        fields['public_url'] = url
        weight = data.get('weight', 1)
        if type(weight) is not int or not 1 <= weight <= 100:
            raise AdCoinError('invalid_weight')
        fields['weight'] = weight
        return fields

    # ---------- campaigns ----------
    def _settings(self, data, *, partial=False):
        out = {}
        if 'name' in data or not partial:
            out['name'] = self._text(data.get('name'), MAX_NAME, 'name')
        if 'categories' in data or not partial:
            cats = data.get('categories')
            if (not isinstance(cats, list) or not 1 <= len(cats) <= 8
                    or any(type(c) is not str or not re.fullmatch(CATEGORY, c) for c in cats)):
                raise AdCoinError('invalid_categories')
            if any(c in BLOCKED_CATEGORIES or c.split('/', 1)[0] in BLOCKED_CATEGORIES for c in cats):
                raise AdCoinError('restricted_category', 'Medical, political, adult, gambling, weapon and drug '
                                                         'categories are not available.')
            out['categories'] = sorted(set(cats))
        if 'bid_won' in data or not partial:
            bid = data.get('bid_won')
            if type(bid) is not int or not 10 <= bid <= 1_000_000 or bid % COIN_VALUE_WON:
                raise AdCoinError('invalid_bid', 'Bids are whole coins (10 won steps), 10 to 1,000,000 won.')
            out['bid_won'] = bid
        if 'daily_budget_won' in data or not partial:
            daily = data.get('daily_budget_won')
            if type(daily) is not int or not 100 <= daily <= 100_000_000 or daily % COIN_VALUE_WON:
                raise AdCoinError('invalid_daily_budget')
            out['daily_budget_won'] = daily
        if 'bid_won' in out and 'daily_budget_won' in out and out['daily_budget_won'] < out['bid_won']:
            raise AdCoinError('daily_budget_below_bid', 'The daily budget must cover at least one bid.')
        if 'starts_at' in data or not partial:
            starts = data.get('starts_at', now())
            if not isinstance(starts, (int, float)) or starts < 0:
                raise AdCoinError('invalid_schedule')
            out['starts_at'] = float(starts)
        if 'ends_at' in data or not partial:
            ends = data.get('ends_at')
            if ends is not None and (not isinstance(ends, (int, float)) or ends <= out.get('starts_at', 0)):
                raise AdCoinError('invalid_schedule', 'The end must be after the start.')
            out['ends_at'] = None if ends is None else float(ends)
        if 'frequency_cap' in data or not partial:
            cap = data.get('frequency_cap', FREQUENCY_CAP_PER_DAY)
            if type(cap) is not int or not 1 <= cap <= FREQUENCY_CAP_PER_DAY:
                raise AdCoinError('invalid_frequency_cap', 'At most 3 views per person a day.')
            out['frequency_cap'] = cap
        if 'excluded_categories' in data or not partial:
            ex = data.get('excluded_categories', [])
            if not isinstance(ex, list) or len(ex) > 30 or any(type(c) is not str or not re.fullmatch(CATEGORY, c)
                                                                 for c in ex):
                raise AdCoinError('invalid_exclusions')
            out['excluded'] = sorted(set(ex))
        return out

    def create_campaign(self, advertiser_id, actor, data):
        advertiser = self._require(advertiser_id, actor, 'editor')
        product = data.get('objective')
        if product not in PRODUCTS:
            raise AdCoinError('invalid_objective', 'Choose S1 (sponsor a task), P2 (view and confirm) or B1 '
                                                   '(signed offer for agents).')
        settings = self._settings(data)
        creative = self._creative_fields(data.get('creative') or {})
        status, note = self._review(advertiser, creative)
        title = creative['title'] if status != 'disapproved' else settings['name']
        try:
            campaign = self.svc.create_campaign(
                advertiser=advertiser['name'], product=product, title=title if status != 'disapproved' else 'Pending ad',
                body=creative['body'] if status != 'disapproved' else 'Pending review.',
                question=creative['question'] if status != 'disapproved' else 'Pending?',
                answer=creative['answer'] if status != 'disapproved' else 'pending',
                public_url=creative['public_url'], categories=settings['categories'], bid_won=settings['bid_won'])
        except AdCoinError as exc:
            if exc.code != 'creative_rejected':
                raise
            campaign = self.svc.create_campaign(advertiser=advertiser['name'], product=product, title='Pending ad',
                                                body='Pending review.', question='Pending?', answer='pending',
                                                public_url=creative['public_url'], categories=settings['categories'],
                                                bid_won=settings['bid_won'])
        creative_id = 'cr_' + uuid.uuid4().hex[:16]
        with self.db.transaction() as db:
            db.execute('INSERT INTO ad_coin_campaign_meta VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (campaign['id'], advertiser_id, settings['name'], settings['daily_budget_won'],
                        settings['starts_at'], settings['ends_at'], settings['frequency_cap'],
                        dumps(settings['excluded']), 'draft', '', 'enabled', now(), now()))
            db.execute('INSERT INTO ad_coin_creatives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                       (creative_id, campaign['id'], creative['title'], creative['body'], creative['question'],
                        creative['answer'], creative['public_url'], status, note, creative['weight'], now(), now()))
            self._refresh_campaign_review(db, campaign['id'])
            self._log(db, advertiser_id, actor, 'campaign.created', campaign['id'],
                      {'objective': product, 'review': status})
        return self.campaign(advertiser_id, actor, campaign['id'])

    def update_campaign(self, advertiser_id, actor, campaign_id, data):
        self._require(advertiser_id, actor, 'editor')
        meta = self._campaign_of(advertiser_id, campaign_id)
        if meta['user_status'] == 'removed':
            raise AdCoinError('campaign_removed', status=409)
        changes = self._settings(data, partial=True)
        status = data.get('status')
        if status is not None and status not in CAMPAIGN_STATUS:
            raise AdCoinError('invalid_status')
        with self.db.transaction() as db:
            for key, column in (('name', 'name'), ('daily_budget_won', 'daily_budget_won'), ('starts_at', 'starts_at'),
                                ('ends_at', 'ends_at'), ('frequency_cap', 'frequency_cap')):
                if key in changes:
                    db.execute('UPDATE ad_coin_campaign_meta SET ' + column + '=?, updated_at=? WHERE campaign_id=?',
                               (changes[key], now(), campaign_id))
            if 'excluded' in changes:
                db.execute('UPDATE ad_coin_campaign_meta SET excluded=?, updated_at=? WHERE campaign_id=?',
                           (dumps(changes['excluded']), now(), campaign_id))
            if 'bid_won' in changes:
                db.execute('UPDATE ad_coin_campaigns SET bid_won=? WHERE id=?', (changes['bid_won'], campaign_id))
            if 'categories' in changes:
                db.execute('UPDATE ad_coin_campaigns SET categories=? WHERE id=?',
                           (dumps(changes['categories']), campaign_id))
                self.svc._index_categories(db, campaign_id, changes['categories'])
            if status is not None:
                db.execute('UPDATE ad_coin_campaign_meta SET user_status=?, updated_at=? WHERE campaign_id=?',
                           (status, now(), campaign_id))
                db.execute('UPDATE ad_coin_campaigns SET status=? WHERE id=?',
                           ('active' if status == 'enabled' else 'paused', campaign_id))
            self._log(db, advertiser_id, actor, 'campaign.updated', campaign_id,
                      {k: v for k, v in {**changes, **({'status': status} if status else {})}.items()})
        return self.campaign(advertiser_id, actor, campaign_id)

    def campaign(self, advertiser_id, actor, campaign_id):
        self._require(advertiser_id, actor, 'viewer')
        meta = self._campaign_of(advertiser_id, campaign_id)
        base = self.svc.campaign(campaign_id)
        today = self.db.one("SELECT COALESCE(SUM(amount_won), 0) AS s FROM ad_coin_reservations WHERE campaign_id=? "
                            "AND created_at>=? AND status IN ('reserved','awarded')", (campaign_id, day_start()))['s']
        creatives = self.db.all('SELECT * FROM ad_coin_creatives WHERE campaign_id=? AND removed_at IS NULL '
                                'ORDER BY created_at', (campaign_id,))
        at = now()
        if meta['user_status'] != 'enabled':
            serving = meta['user_status']
        elif meta['review_status'] not in REVIEW_FOR_SERVING:
            serving = meta['review_status']
        elif meta['starts_at'] > at:
            serving = 'scheduled'
        elif meta['ends_at'] is not None and meta['ends_at'] <= at:
            serving = 'ended'
        elif base['escrow_won'] < base['bid_won']:
            serving = 'budget_empty'
        elif today + base['bid_won'] > meta['daily_budget_won']:
            serving = 'daily_budget_reached'
        else:
            serving = 'serving'
        return {'id': campaign_id, 'name': meta['name'], 'objective': base['product'], 'categories': base['categories'],
                'bid_won': base['bid_won'], 'daily_budget_won': meta['daily_budget_won'], 'spent_today_won': today,
                'escrow_won': base['escrow_won'], 'starts_at': meta['starts_at'], 'ends_at': meta['ends_at'],
                'frequency_cap': meta['frequency_cap'], 'excluded_categories': json.loads(meta['excluded']),
                'status': meta['user_status'], 'review_status': meta['review_status'], 'serving': serving,
                'floor_for_600_won_task': task_floor_won(600) if base['product'] == 'S1' else None,
                'test': base['test'],
                'creatives': [{'id': c['id'], 'title': c['title'], 'body': c['body'], 'question': c['question'],
                               'public_url': c['public_url'], 'weight': c['weight'],
                               'review_status': c['review_status'], 'review_note': c['review_note']}
                              for c in creatives]}

    def campaigns(self, advertiser_id, actor):
        self._require(advertiser_id, actor, 'viewer')
        rows = self.db.all("SELECT campaign_id FROM ad_coin_campaign_meta WHERE advertiser_id=? AND "
                           "user_status != 'removed' ORDER BY created_at", (advertiser_id,))
        return [self.campaign(advertiser_id, actor, r['campaign_id']) for r in rows]

    # ---------- creatives ----------
    def add_creative(self, advertiser_id, actor, campaign_id, data):
        advertiser = self._require(advertiser_id, actor, 'editor')
        self._campaign_of(advertiser_id, campaign_id)
        if self.db.one('SELECT COUNT(*) AS n FROM ad_coin_creatives WHERE campaign_id=? AND removed_at IS NULL',
                       (campaign_id,))['n'] >= 15:
            raise AdCoinError('creative_limit', 'At most 15 ads per campaign.', 409)
        creative = self._creative_fields(data)
        status, note = self._review(advertiser, creative)
        creative_id = 'cr_' + uuid.uuid4().hex[:16]
        with self.db.transaction() as db:
            db.execute('INSERT INTO ad_coin_creatives VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)',
                       (creative_id, campaign_id, creative['title'], creative['body'], creative['question'],
                        creative['answer'], creative['public_url'], status, note, creative['weight'], now(), now()))
            self._refresh_campaign_review(db, campaign_id)
            self._log(db, advertiser_id, actor, 'creative.created', creative_id, {'review': status})
        return self.campaign(advertiser_id, actor, campaign_id)

    def edit_creative(self, advertiser_id, actor, creative_id, data):
        """Editing sends the ad back through review, like Google Ads."""
        advertiser = self._require(advertiser_id, actor, 'editor')
        row = self.db.one('SELECT cr.* FROM ad_coin_creatives cr JOIN ad_coin_campaign_meta m ON '
                          'm.campaign_id=cr.campaign_id WHERE cr.id=? AND m.advertiser_id=? AND cr.removed_at IS NULL',
                          (creative_id, advertiser_id))
        if not row:
            raise AdCoinError('unknown_creative', status=404)
        if data.get('remove') is True:
            with self.db.transaction() as db:
                db.execute('UPDATE ad_coin_creatives SET removed_at=? WHERE id=?', (now(), creative_id))
                self._refresh_campaign_review(db, row['campaign_id'])
                self._log(db, advertiser_id, actor, 'creative.removed', creative_id)
            return self.campaign(advertiser_id, actor, row['campaign_id'])
        merged = {k: data.get(k, row[k]) for k in ('title', 'body', 'question', 'answer', 'public_url', 'weight')}
        creative = self._creative_fields(merged)
        status, note = self._review(advertiser, creative)
        with self.db.transaction() as db:
            db.execute('UPDATE ad_coin_creatives SET title=?, body=?, question=?, answer=?, public_url=?, weight=?, '
                       'review_status=?, review_note=?, updated_at=? WHERE id=?',
                       (creative['title'], creative['body'], creative['question'], creative['answer'],
                        creative['public_url'], creative['weight'], status, note, now(), creative_id))
            self._refresh_campaign_review(db, row['campaign_id'])
            self._log(db, advertiser_id, actor, 'creative.edited', creative_id, {'review': status})
        return self.campaign(advertiser_id, actor, row['campaign_id'])

    # ---------- appeals and operator review ----------
    def appeal(self, advertiser_id, actor, creative_id, reason):
        self._require(advertiser_id, actor, 'editor')
        row = self.db.one('SELECT cr.review_status FROM ad_coin_creatives cr JOIN ad_coin_campaign_meta m ON '
                          'm.campaign_id=cr.campaign_id WHERE cr.id=? AND m.advertiser_id=?', (creative_id, advertiser_id))
        if not row:
            raise AdCoinError('unknown_creative', status=404)
        if row['review_status'] not in ('disapproved', 'eligible_limited'):
            raise AdCoinError('nothing_to_appeal', 'Only disapproved or limited ads can be appealed.', 409)
        reason = self._text(reason, 500, 'reason')
        appeal_id = 'ap_' + uuid.uuid4().hex[:16]
        with self.db.transaction() as db:
            db.execute('INSERT INTO ad_coin_appeals VALUES (?,?,?,?,?,?,?,NULL)',
                       (appeal_id, advertiser_id, creative_id, reason, 'pending', '', now()))
            db.execute("UPDATE ad_coin_creatives SET review_status='under_review', review_note=?, updated_at=? "
                       "WHERE id=?", ('Appeal pending.', now(), creative_id))
            campaign = db.execute('SELECT campaign_id FROM ad_coin_creatives WHERE id=?', (creative_id,)).fetchone()
            self._refresh_campaign_review(db, campaign['campaign_id'])
            self._log(db, advertiser_id, actor, 'appeal.submitted', creative_id)
        return {'appeal_id': appeal_id, 'status': 'pending'}

    def review_queue(self):
        rows = self.db.all("SELECT cr.*, m.advertiser_id, a.name AS advertiser_name FROM ad_coin_creatives cr "
                           "JOIN ad_coin_campaign_meta m ON m.campaign_id=cr.campaign_id JOIN ad_coin_advertisers a "
                           "ON a.id=m.advertiser_id WHERE cr.review_status='under_review' AND cr.removed_at IS NULL "
                           "ORDER BY cr.updated_at LIMIT 200")
        return [{'creative_id': r['id'], 'campaign_id': r['campaign_id'], 'advertiser': r['advertiser_name'],
                 'advertiser_id': r['advertiser_id'], 'title': r['title'], 'body': r['body'],
                 'public_url': r['public_url'], 'note': r['review_note']} for r in rows]

    def decide(self, creative_id, decision, note=''):
        if decision not in ('eligible', 'eligible_limited', 'disapproved'):
            raise AdCoinError('invalid_decision')
        row = self.db.one('SELECT cr.campaign_id, m.advertiser_id FROM ad_coin_creatives cr JOIN ad_coin_campaign_meta m '
                          'ON m.campaign_id=cr.campaign_id WHERE cr.id=?', (creative_id,))
        if not row:
            raise AdCoinError('unknown_creative', status=404)
        note = str(note or '')[:300]
        with self.db.transaction() as db:
            db.execute('UPDATE ad_coin_creatives SET review_status=?, review_note=?, updated_at=? WHERE id=?',
                       (decision, note, now(), creative_id))
            db.execute("UPDATE ad_coin_appeals SET status='resolved', resolution=?, resolved_at=? WHERE "
                       "object_ref=? AND status='pending'", (decision, now(), creative_id))
            self._refresh_campaign_review(db, row['campaign_id'])
            self._log(db, row['advertiser_id'], 'admin', 'review.' + decision, creative_id, {'note': note})
        return {'creative_id': creative_id, 'review_status': decision}

    def set_verification(self, advertiser_id, verification):
        if verification not in ('verified', 'unverified', 'rejected'):
            raise AdCoinError('invalid_verification')
        with self.db.transaction() as db:
            if not db.execute('UPDATE ad_coin_advertisers SET verification=? WHERE id=?',
                              (verification, advertiser_id)).rowcount:
                raise AdCoinError('unknown_advertiser', status=404)
            self._log(db, advertiser_id, 'admin', 'verification.' + verification, advertiser_id)
        return self.advertiser(advertiser_id, 'admin')

    def set_account_status(self, advertiser_id, status):
        if status not in ('active', 'suspended'):
            raise AdCoinError('invalid_status')
        with self.db.transaction() as db:
            if not db.execute('UPDATE ad_coin_advertisers SET status=? WHERE id=?', (status, advertiser_id)).rowcount:
                raise AdCoinError('unknown_advertiser', status=404)
            self._log(db, advertiser_id, 'admin', 'account.' + status, advertiser_id)
        return self.advertiser(advertiser_id, 'admin')

    # ---------- money ----------
    def fund(self, advertiser_id, actor, campaign_id, amount_won, idem):
        self._require(advertiser_id, actor, 'owner')
        self._campaign_of(advertiser_id, campaign_id)
        result = self.svc.fund_campaign(campaign_id, amount_won, advertiser_id + ':' + str(idem)[:64])
        with self.db.transaction() as db:
            self._log(db, advertiser_id, actor, 'budget.funded', campaign_id, {'won': amount_won, 'virtual': True})
        return {'campaign_id': campaign_id, 'escrow_won': result['escrow_won'], 'virtual': True}

    def mark_invalid(self, reservation_id, reason):
        """Operator: an awarded view was invalid. The advertiser is refunded by the platform;
        the person keeps the coins they were promised."""
        row = self.db.one('SELECT * FROM ad_coin_reservations WHERE id=?', (reservation_id,))
        if not row or row['status'] != 'awarded':
            raise AdCoinError('not_an_awarded_view', status=409)
        if self.db.one('SELECT 1 FROM ad_coin_invalid_activity WHERE reservation_id=?', (reservation_id,)):
            raise AdCoinError('already_refunded', status=409)
        amount = row['amount_won']
        postings, left = [(L.escrow(row['campaign_id']), amount)], amount
        for account in (L.PLATFORM_REVENUE, L.PLATFORM_DIRECT, L.PROMOTION_RESERVE):   # the platform pays
            take = min(left, self.svc.ledger.balance(account))
            if take:
                postings.append((account, -take))
                left -= take
        if left:
            raise AdCoinError('platform_funds_short', 'Top up the platform refund reserve before refunding.', 409)
        with self.db.transaction() as db:
            self.db.lock_rows('ad_coin_campaigns', [row['campaign_id']])
            journal = self.svc.ledger.post('invalid_refund', 'invalid_refund:' + reservation_id,
                                           [p for p in postings if p[1]], {'reason': str(reason)[:100]})
            db.execute('INSERT INTO ad_coin_invalid_activity VALUES (?,?,?,?,?)',
                       (reservation_id, row['campaign_id'], str(reason)[:100], amount, now()))
            self.svc._daily(db, row['campaign_id'], _day(row['created_at']), invalid=amount)
            meta = db.execute('SELECT advertiser_id FROM ad_coin_campaign_meta WHERE campaign_id=?',
                              (row['campaign_id'],)).fetchone()
            if meta:
                self._log(db, meta['advertiser_id'], 'admin', 'invalid.refunded', reservation_id, {'won': amount})
        self.svc._after_money_move()
        return {'reservation_id': reservation_id, 'refunded_won': amount, 'journal_id': journal,
                'person_keeps_coins': True}

    def fund_platform_reserve(self, amount_won, idem):
        """Operator: a virtual platform deposit that pays invalid-activity refunds."""
        if type(amount_won) is not int or not 10 <= amount_won <= 100_000_000 or amount_won % COIN_VALUE_WON:
            raise AdCoinError('invalid_amount_won')
        try:
            self.svc.ledger.post('platform_reserve', 'platform_reserve:' + str(idem)[:64],
                                 [(L.EXTERNAL_FUNDING, -amount_won), (L.PROMOTION_RESERVE, amount_won)],
                                 {'virtual': True})
        except L.Duplicate:
            pass
        self.svc._after_money_move()
        return {'reserve_won': self.svc.ledger.balance(L.PROMOTION_RESERVE), 'virtual': True}

    # ---------- reports ----------
    def report(self, advertiser_id, actor, *, campaign_id=None, days=30):
        self._require(advertiser_id, actor, 'viewer')
        if type(days) is not int or not 1 <= days <= MAX_REPORT_DAYS:
            raise AdCoinError('invalid_days')
        if campaign_id is not None:
            self._campaign_of(advertiser_id, campaign_id)
        since = day_start() - (days - 1) * DAY
        scope = ' AND r.campaign_id=?' if campaign_id else ''
        args = (advertiser_id, since) + ((campaign_id,) if campaign_id else ())
        reservations = self.db.all(
            'SELECT r.id, r.campaign_id, r.status, r.amount_won, r.created_at FROM ad_coin_reservations r JOIN '
            'ad_coin_campaign_meta m ON m.campaign_id=r.campaign_id WHERE m.advertiser_id=? AND r.created_at>=?' + scope,
            args)
        views = {r['reservation_id']: r for r in self.db.all(
            'SELECT e.reservation_id, e.user_ref FROM ad_coin_exposures e JOIN ad_coin_campaign_meta m ON '
            'm.campaign_id=e.campaign_id WHERE m.advertiser_id=? AND e.created_at>=?' +
            scope.replace('r.campaign_id', 'e.campaign_id'), args)}
        invalid = {r['reservation_id']: r['refunded_won'] for r in self.db.all(
            'SELECT i.reservation_id, i.refunded_won FROM ad_coin_invalid_activity i JOIN ad_coin_campaign_meta m ON '
            'm.campaign_id=i.campaign_id WHERE m.advertiser_id=? AND i.created_at>=?' +
            scope.replace('r.campaign_id', 'i.campaign_id'), args)}
        runs = {r['reservation_id']: r['status'] for r in self.db.all(
            "SELECT v.reservation_id, e.status FROM ad_coin_vouchers v JOIN ad_coin_executions e ON e.source_ref=v.id "
            "JOIN ad_coin_reservations r ON r.id=v.reservation_id JOIN ad_coin_campaign_meta m ON "
            "m.campaign_id=r.campaign_id WHERE m.advertiser_id=? AND r.created_at>=?" + scope, args)}
        by_day = {}
        for r in reservations:
            key = _korean_date(r['created_at'])
            row = by_day.setdefault(key, {'date': key, 'offers': 0, 'views': 0, 'people': set(), 'spend_won': 0,
                                          'invalid_refunded_won': 0, 'runs_started': 0, 'runs_succeeded': 0})
            row['offers'] += 1
            if r['status'] == 'awarded':
                row['spend_won'] += r['amount_won']
            if r['id'] in views:
                row['views'] += 1
                row['people'].add(views[r['id']]['user_ref'])
            if r['id'] in invalid:
                row['invalid_refunded_won'] += invalid[r['id']]
            if r['id'] in runs:
                row['runs_started'] += 1
                row['runs_succeeded'] += runs[r['id']] in ('succeeded', 'partial')
        rows = []
        for key in sorted(by_day):
            row = by_day[key]
            row['people'] = len(row['people'])
            row['net_spend_won'] = row['spend_won'] - row['invalid_refunded_won']
            row['view_rate'] = round(row['views'] / row['offers'], 4) if row['offers'] else 0.0
            row['cost_per_view_won'] = round(row['net_spend_won'] / row['views']) if row['views'] else None
            rows.append(row)
        totals = {k: sum(r[k] for r in rows) for k in ('offers', 'views', 'spend_won', 'invalid_refunded_won',
                                                        'net_spend_won', 'runs_started', 'runs_succeeded')}
        totals['people_upper_bound'] = sum(r['people'] for r in rows)
        totals['view_rate'] = round(totals['views'] / totals['offers'], 4) if totals['offers'] else 0.0
        return {'advertiser_id': advertiser_id, 'campaign_id': campaign_id, 'days': days, 'rows': rows,
                'totals': totals, 'virtual': True,
                'note': 'Views were rewarded and people knew it; a view is not purchase intent. '
                        'Invalid views are refunded by the platform.'}

    def report_csv(self, advertiser_id, actor, **kw):
        report = self.report(advertiser_id, actor, **kw)
        out = io.StringIO()
        fields = ['date', 'offers', 'views', 'people', 'view_rate', 'spend_won', 'invalid_refunded_won',
                  'net_spend_won', 'cost_per_view_won', 'runs_started', 'runs_succeeded']
        writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for row in report['rows']:
            writer.writerow({k: ('' if row.get(k) is None else row[k]) for k in fields})
        return out.getvalue()

    def statement(self, advertiser_id, actor, limit=200):
        self._require(advertiser_id, actor, 'viewer')
        rows = self.db.all(
            "SELECT j.id, j.kind, j.created_at, p.account, p.amount FROM ad_coin_postings p JOIN ad_coin_journals j "
            "ON j.id=p.journal_id JOIN ad_coin_campaign_meta m ON p.account='escrow:'||m.campaign_id "
            "WHERE m.advertiser_id=? ORDER BY j.created_at DESC LIMIT ?", (advertiser_id, max(1, min(int(limit), 500))))
        return {'entries': [{'journal_id': r['id'], 'kind': r['kind'], 'at': int(r['created_at']),
                             'campaign_id': r['account'].split(':', 1)[1], 'escrow_change_won': r['amount']}
                            for r in rows], 'virtual': True}

    def history(self, advertiser_id, actor, limit=100):
        self._require(advertiser_id, actor, 'viewer')
        rows = self.db.all('SELECT * FROM ad_coin_change_log WHERE advertiser_id=? ORDER BY created_at DESC LIMIT ?',
                           (advertiser_id, max(1, min(int(limit), 500))))
        return [{'at': int(r['created_at']), 'actor': r['actor'], 'action': r['action'], 'object': r['object_ref'],
                 'detail': json.loads(r['detail'])} for r in rows]

    def notifications(self, advertiser_id, actor):
        account = self.advertiser(advertiser_id, actor)
        items = []
        if account['verification'] != 'verified':
            items.append({'level': 'info', 'code': 'verify_advertiser',
                          'message': 'Verify your business to lift the 20,000 won daily limit.'})
        for c in self.campaigns(advertiser_id, actor):
            if c['review_status'] == 'disapproved':
                items.append({'level': 'error', 'code': 'disapproved', 'campaign_id': c['id'],
                              'message': c['name'] + ': every ad is disapproved. Edit an ad or appeal.'})
            if c['serving'] == 'budget_empty':
                items.append({'level': 'warning', 'code': 'budget_empty', 'campaign_id': c['id'],
                              'message': c['name'] + ': the budget cannot fund one more unit.'})
            elif c['escrow_won'] and c['escrow_won'] < c['bid_won'] * 10:
                items.append({'level': 'warning', 'code': 'budget_low', 'campaign_id': c['id'],
                              'message': c['name'] + ': less than ten units of budget left.'})
            if c['serving'] == 'daily_budget_reached':
                items.append({'level': 'info', 'code': 'daily_budget_reached', 'campaign_id': c['id'],
                              'message': c['name'] + ': today\'s budget is spent; serving resumes tomorrow.'})
        return items


def _korean_date(at):
    import time
    return time.strftime('%Y-%m-%d', time.gmtime(at + 9 * 3600))
