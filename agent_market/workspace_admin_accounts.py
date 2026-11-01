"""Reviewed staff account changes; credential verifiers never enter API projections."""
import re
import time

from .gateway import admin_auth
from .workspace_admin_events import execute, register, rows, signature, transaction

register({
    'staff_account_get': 'SELECT * FROM admin_users WHERE id=?',
    'staff_account_name': 'SELECT * FROM admin_users WHERE username=?',
    'staff_account_insert': '''INSERT INTO admin_users
        (username,password_hash,salt,role,name,active,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)''',
    'staff_account_update': '''UPDATE admin_users SET name=?,role=?,active=?,password_hash=?,salt=?,updated_at=? WHERE id=?''',
    'staff_account_sessions': 'DELETE FROM admin_sessions WHERE user_id=?',
})


def project(payload):
    return {key: payload[key] for key in ('action', 'uid', 'username', 'changes', 'before', 'password_reset') if key in payload}


class AccountChanges:
    def __init__(self, store):
        self.store = store

    def stamp(self, row):
        # Login timestamps change independently; credential/identity/authority drift must invalidate approval.
        return signature(self.store._workspace_admin_event_key,
                         {k: row[k] for k in ('id', 'username', 'name', 'role', 'active', 'password_hash', 'salt')})

    @staticmethod
    def highest(db, uid):
        found = rows(db, 'staff_account_get', (uid,))
        if not found or not found[0]['active'] or found[0]['role'] != 'superadmin':
            raise ValueError('요청자 또는 승인자의 최고관리자 권한이 변경되었습니다.')
        return found[0]

    @staticmethod
    def protect(db, row, changes, action):
        if action == 'delete' and row['username'] == 'sadmin':
            raise ValueError('sadmin 계정은 삭제할 수 없습니다.')
        removing = action == 'delete' or changes.get('active', row['active']) == 0 or changes.get('role', row['role']) != 'superadmin'
        if row['active'] and row['role'] == 'superadmin' and removing:
            if not any(u['id'] != row['id'] and u['active'] and u['role'] == 'superadmin' for u in admin_auth.list_admin_users(db)):
                raise ValueError('마지막 활성 최고관리자는 삭제·비활성화하거나 권한을 낮출 수 없습니다.')

    def prepare(self, uid, action, target_id, body):
        if not isinstance(body, dict):
            raise ValueError('요청 형식이 잘못되었습니다.')
        allowed = {'reason', 'username', 'password', 'name', 'role'} if action == 'create' else {'reason', 'name', 'role', 'active', 'new_password'} if action == 'update' else {'reason'}
        if set(body) - allowed:
            raise ValueError('지원하지 않는 계정 변경 항목입니다.')
        reason = body.get('reason')
        if not isinstance(reason, str) or not 4 <= len(reason.strip()) <= 300 or not reason.isprintable():
            raise ValueError('변경 사유를 4~300자로 입력하세요.')
        changes = {k: body[k] for k in ('name', 'role', 'active') if k in body}
        if 'name' in changes and (not isinstance(changes['name'], str) or not 1 <= len(changes['name'].strip()) <= 100 or not changes['name'].isprintable()):
            raise ValueError('표시 이름을 1~100자로 입력하세요.')
        if 'role' in changes:
            if not isinstance(changes['role'], str):
                raise ValueError('Invalid administrator role')
            admin_auth.validate_role(changes['role'])
        if 'active' in changes and (type(changes['active']) is not int or changes['active'] not in (0, 1)):
            raise ValueError('활성 상태는 0 또는 1이어야 합니다.')
        password_key = 'password' if action == 'create' else 'new_password'
        credentials = None
        if password_key in body or action == 'create':
            admin_auth.validate_password(body.get(password_key))
            credentials = admin_auth.hash_password(body[password_key])  # outside the writer transaction
        if action == 'update' and not changes and credentials is None:
            raise ValueError('변경할 항목이 없습니다.')
        with transaction(self.store, True) as db:
            self.highest(db, uid)
            if action == 'create':
                username = body.get('username')
                if not isinstance(username, str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,64}', username):
                    raise ValueError('관리자 아이디 형식을 확인하세요.')
                if rows(db, 'staff_account_name', (username,)):
                    raise ValueError('이미 존재하는 관리자 아이디입니다.')
                changes = {'name': username, 'role': 'admin', **changes}
                target, expected, before = 'name:' + username, None, None
            else:
                found = rows(db, 'staff_account_get', (target_id,))
                if not found:
                    raise ValueError('사용자를 찾을 수 없습니다.')
                row = found[0]
                self.protect(db, row, changes, action)
                username, target, expected = row['username'], 'id:' + str(target_id), self.stamp(row)
                before = {k: row[k] for k in ('name', 'role', 'active')}
        payload = {'action': action, 'uid': target_id, 'username': username, 'changes': changes,
                   'before': before, 'password_reset': credentials is not None, '_credentials': credentials,
                   '_expected': expected, '_requester': uid}
        return target, payload, reason.strip()

    def apply(self, payload, reviewer_id):
        with transaction(self.store) as db:
            actor = self.highest(db, reviewer_id)
            self.highest(db, payload['_requester'])
            action, uid, changes = payload['action'], payload['uid'], payload['changes']
            now = time.time()
            if action == 'create':
                if rows(db, 'staff_account_name', (payload['username'],)):
                    raise ValueError('이미 존재하는 관리자 아이디입니다.')
                pwd_hash, salt = payload['_credentials']
                execute(db, 'staff_account_insert', (payload['username'], pwd_hash, salt, changes['role'], changes['name'], now, now))
                uid = rows(db, 'staff_account_name', (payload['username'],))[0]['id']
            else:
                found = rows(db, 'staff_account_get', (uid,))
                if not found or self.stamp(found[0]) != payload['_expected']:
                    raise ValueError('대상 계정이 변경되었습니다. 새 요청을 작성하세요.')
                row = found[0]
                self.protect(db, row, changes, action)
                if action == 'delete':
                    if not admin_auth.delete_admin_user(db, uid):
                        raise ValueError('계정을 삭제할 수 없습니다.')
                else:
                    new = {**row, **changes}
                    pwd_hash, salt = payload['_credentials'] or (row['password_hash'], row['salt'])
                    execute(db, 'staff_account_update', (new['name'], new['role'], new['active'], pwd_hash, salt, now, uid))
                    if payload['_credentials'] or 'role' in changes or 'active' in changes:
                        execute(db, 'staff_account_sessions', (uid,))
            admin_auth.record_audit(db, username=actor['username'], role=actor['role'],
                action='USER_' + action.upper(), action_name='승인된 관리자 계정 변경', target='user:' + str(uid),
                details=project(payload))
        return {'user_id': uid, 'action': action}
