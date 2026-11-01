"""Validated anonymous inquiries, durable duplicate receipts and scoped quotas."""
import hashlib
import time
from email.headerregistry import Address
from email.errors import HeaderParseError

from ..gateway.sanitizer import sanitize_text, EMAIL_SAFE_REGEX
from .registration_policy import PublicRequestError, text_field

CATEGORIES = ('general','technical','partnership','security_abuse','custom_agent','billing')


def validated_inquiry(body):
    if type(body) is not dict or set(body)-{'name','email','subject','message','category'}:
        raise PublicRequestError('request', 'Use the supported inquiry fields.', status=422)
    result = {field:text_field(body.get(field), field, lo, hi, status=422, multiline=field=='message')
        for field,lo,hi in (('name',2,100),('email',5,150),('subject',3,200),('message',5,4000))}
    category = body.get('category', 'general')
    if type(category) is not str or category not in CATEGORIES:
        raise PublicRequestError('category', 'Choose a supported inquiry category.', status=422, allowed=CATEGORIES)
    email = result['email']
    try:
        address = Address(addr_spec=email)
        if not email.isascii() or not address.username or '.' not in address.domain or address.addr_spec!=email or not EMAIL_SAFE_REGEX.fullmatch(email):
            raise ValueError()
    except (ValueError, IndexError, HeaderParseError):
        raise PublicRequestError('email', 'Please provide a valid contact email address.', status=422) from None
    result.update(category=category, email=email.lower())
    for field,lo,hi in (('name',2,100),('subject',3,200),('message',5,4000)):
        result[field] = text_field(sanitize_text(result[field], max_length=hi), field, lo, hi,
            multiline=field=='message', status=422)
    return result


def _key(value):
    return int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], 'big', signed=True)


def record_inquiry(store, body, *, ip, user_agent, visitor_reference=None, now=None):
    value = validated_inquiry(body)
    now = time.time() if now is None else now
    with store.tx() as db:
        # One email lock serializes public receipts across PostgreSQL web slots.
        if getattr(store,'backend',None)=='postgresql':
            store._execute('SELECT pg_advisory_xact_lock(%s::bigint)', (_key('public-inquiry:'+value['email']),))
        duplicate = db.execute('''SELECT inquiry_id FROM customer_inquiries
            WHERE email=? AND ip=? AND category=? AND name=? AND subject=? AND message=?
            AND created_at>? ORDER BY created_at DESC LIMIT 1''',
            (value['email'],ip,value['category'],value['name'],value['subject'],value['message'],now-600)).fetchone()
        if duplicate:
            return {'inquiry_id': duplicate[0], 'duplicate': True}
        email_count = db.execute('SELECT COUNT(*) FROM customer_inquiries WHERE email=? AND created_at>?',
            (value['email'],now-3600)).fetchone()[0]
        if email_count>=5:
            raise PublicRequestError('email', 'Please wait before sending another inquiry.', status=429,
                code='INQUIRY_RATE_LIMIT', headers={'Retry-After':'3600','RateLimit-Policy':'"contact-email";q=5;w=3600','Cache-Control':'no-store'})
        ip_count = db.execute('SELECT COUNT(*) FROM customer_inquiries WHERE ip=? AND created_at>?',
            (ip,now-600)).fetchone()[0]
        if ip_count>=15:
            raise PublicRequestError('request', 'Please wait before sending another inquiry.', status=429,
                code='INQUIRY_RATE_LIMIT', headers={'Retry-After':'600','RateLimit-Policy':'"contact-ip";q=15;w=600','Cache-Control':'no-store'})
        identity = store.record_customer_inquiry(**value, visitor_token=visitor_reference, ip=ip, user_agent=user_agent)
    return {'inquiry_id': identity, 'duplicate': False}
