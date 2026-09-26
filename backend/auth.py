"""Email verification, revocable sessions and administrator account management."""
from hashlib import sha256
import hmac
import json
import secrets
import uuid
from typing import Literal
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from . import config, db, mail_service
from .tenancy import LEGACY_OWNER, as_user, require_user

router = APIRouter(prefix='/api')
passwords = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))
COOKIE = 'studio_session'


def digest(value):
    return sha256(value.encode()).hexdigest()


def email_key(value):
    return str(value).strip().lower()


def public_user(row):
    return {k:row[k] for k in ('id','email','display_name','role','status','email_verified','created_at','last_login_at')}


def active_ids():
    with db.system_connection() as c:
        return [r['id'] for r in c.execute("SELECT id FROM app_users WHERE status='active' ORDER BY created_at")]


def cleanup():
    with db.system_connection() as c:
        c.execute('DELETE FROM auth_sessions WHERE expires_at<=now()')
        c.execute('DELETE FROM auth_codes WHERE expires_at<=now()')
        c.execute('DELETE FROM auth_limits WHERE reset_at<=now()')


def is_active(ident):
    with db.system_connection() as c:
        return bool(c.execute("SELECT 1 FROM app_users WHERE id=%s AND status='active'",(ident,)).fetchone())


def user_for_token(token):
    if not token or len(token)>128:return None
    with db.system_connection() as c:
        row = c.execute("""SELECT u.* FROM auth_sessions s JOIN app_users u ON u.id=s.user_id
            WHERE s.token_hash=%s AND s.expires_at>now() AND u.status='active'""",(digest(token),)).fetchone()
    return public_user(row) if row else None


def initialize():
    # Existing content is reserved for an offline-authorized administrator, never the first sign-up.
    with db.system_connection() as c:
        db.lock(c,'bootstrap')
        c.execute("INSERT INTO app_users(id,display_name,role,status) VALUES (%s,'管理员','admin','pending_setup') ON CONFLICT DO NOTHING",(LEGACY_OWNER,))
        owner = c.execute('SELECT status FROM app_users WHERE id=%s',(LEGACY_OWNER,)).fetchone()
        if owner['status']=='pending_setup':
            path = config.DATA/'admin-setup.txt'
            if not path.exists():
                token = secrets.token_urlsafe(36)
                path.write_text(token,encoding='utf-8');path.chmod(0o600)
            c.execute("INSERT INTO server_settings VALUES ('bootstrap_hash',%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(digest(path.read_text(encoding='utf-8')),))
    with as_user(LEGACY_OWNER):db.init_user()


def limited(key, maximum, seconds):
    """Atomic PostgreSQL rate limits, shared by requests and process restarts."""
    with db.system_connection() as c:
        row = c.execute("""INSERT INTO auth_limits(key,hits,reset_at) VALUES (%s,1,now()+%s::interval)
          ON CONFLICT(key) DO UPDATE SET
          hits=CASE WHEN auth_limits.reset_at<=now() THEN 1 ELSE auth_limits.hits+1 END,
          reset_at=CASE WHEN auth_limits.reset_at<=now() THEN excluded.reset_at ELSE auth_limits.reset_at END
          RETURNING hits""", (digest(key),f'{seconds} seconds')).fetchone()
    if row['hits']>maximum:raise HTTPException(429,'操作过于频繁，请稍后再试。')


def peer(request):
    return request.client.host if request.client else 'unknown'


def registration_open():
    with db.system_connection() as c:
        row = c.execute("SELECT value FROM server_settings WHERE key='registration_open'").fetchone()
    return not row or row['value']=='true'


def session(response, ident):
    token = secrets.token_urlsafe(36)
    with db.system_connection() as c:
        c.execute('DELETE FROM auth_sessions WHERE expires_at<=now()')
        c.execute("INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES (%s,%s,now()+interval '7 days')",(digest(token),ident))
        c.execute('UPDATE app_users SET last_login_at=now() WHERE id=%s',(ident,))
        row = c.execute('SELECT * FROM app_users WHERE id=%s',(ident,)).fetchone()
    response.set_cookie(COOKIE,token,httponly=True,secure=config.COOKIE_SECURE,samesite='strict',max_age=604800,path='/')
    return public_user(row)


class Credentials(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1,max_length=128)


class Signup(Credentials):
    display_name: str = Field(min_length=1,max_length=60)


class Verify(BaseModel):
    email: EmailStr = Field(max_length=254)
    code: str = Field(pattern=r'^\d{6}$')


class EmailRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


class Reset(Verify):
    password: str = Field(min_length=1,max_length=128)


class Setup(Signup):
    setup_token: str = Field(min_length=32,max_length=128)

    @field_validator('setup_token', mode='before')
    @classmethod
    def normalize_setup_token(cls, value):
        return value.lstrip('\ufeff').strip() if isinstance(value,str) else value


def validation_message(error):
    """Explain auth form errors without returning submitted credentials or validator context."""
    field=error['loc'][-1] if error.get('loc') else ''
    labels={'email':'邮箱','password':'密码','display_name':'昵称','code':'邮箱验证码',
            'current_password':'当前密码','new_password':'新密码'}
    if field=='setup_token':
        return '初始化凭证不完整，请复制服务器 data/admin-setup.txt 中的完整内容，或使用“从凭证文件导入”；这里不是登录密码。'
    if field=='email':return '请输入有效的邮箱地址。'
    if field=='code':return '请输入邮件中的 6 位数字验证码。'
    label=labels.get(field,'此项')
    kind=error['type'];context=error.get('ctx') or {}
    if kind=='missing' or (kind=='string_too_short' and context.get('min_length')==1):return f'请填写{label}。'
    if kind=='string_too_short':return f'{label}至少需要 {context["min_length"]} 个字符。'
    if kind=='string_too_long':return f'{label}不能超过 {context["max_length"]} 个字符。'
    return f'{label}格式不正确，请检查后重试。'


def verify_password(encoded, password):
    try:return passwords.verify(encoded or DUMMY_HASH,password)
    except (VerificationError,InvalidHashError):return False


@router.get('/auth/status')
def status():
    with db.system_connection() as c:
        setup = c.execute('SELECT status FROM app_users WHERE id=%s',(LEGACY_OWNER,)).fetchone()
    return {'setup_required':bool(setup and setup['status']=='pending_setup'),
        'registration_open':registration_open(),'mail_ready':mail_service.public()['ready']}


@router.get('/auth/me')
def me(request: Request):
    return {'user':user_for_token(request.cookies.get(COOKIE))}


@router.post('/auth/setup')
def setup(body: Setup, request: Request, response: Response):
    limited('setup:'+peer(request),10,900)
    error = None
    with db.system_connection() as c:
        db.lock(c,'bootstrap')
        owner = c.execute('SELECT * FROM app_users WHERE id=%s FOR UPDATE',(LEGACY_OWNER,)).fetchone()
        token = c.execute("SELECT value FROM server_settings WHERE key='bootstrap_hash'").fetchone()
        if not owner or owner['status']!='pending_setup' or not token or not hmac.compare_digest(token['value'],digest(body.setup_token)):
            error = '初始化凭证不匹配或已使用。请从服务器 data/admin-setup.txt 导入完整凭证；如果管理员已创建，请刷新页面后登录。'
        elif c.execute('SELECT 1 FROM app_users WHERE email=%s',(email_key(body.email),)).fetchone():
            error = '该邮箱不能用于初始化。'
        else:
            c.execute("UPDATE app_users SET email=%s,password_hash=%s,display_name=%s,status='active' WHERE id=%s",
                      (email_key(body.email),passwords.hash(body.password),body.display_name,LEGACY_OWNER))
            c.execute("DELETE FROM server_settings WHERE key='bootstrap_hash'")
            c.execute("INSERT INTO admin_events(actor_id,target_id,action) VALUES (%s,%s,'bootstrap')",(LEGACY_OWNER,LEGACY_OWNER))
    if error:raise HTTPException(400,error)
    (config.DATA/'admin-setup.txt').unlink(missing_ok=True)
    return {'user':session(response,LEGACY_OWNER)}


def issue_code(email, purpose, payload):
    code = f'{secrets.randbelow(1_000_000):06d}'
    # Server-held key prevents database-only brute force of six-digit codes.
    salt = secrets.token_urlsafe(24)
    hashed = salt+':'+code_proof(salt,code)
    with db.system_connection() as c:
        c.execute("""INSERT INTO auth_codes(email,purpose,code_hash,payload,expires_at) VALUES (%s,%s,%s,%s,now()+interval '10 minutes')
          ON CONFLICT(email,purpose) DO UPDATE SET code_hash=excluded.code_hash,payload=excluded.payload,
          attempts=0,expires_at=excluded.expires_at,created_at=now()""",(email,purpose,hashed,db.dump(payload)))
    try:mail_service.send_code(email,code,purpose)
    except Exception:
        with db.system_connection() as c:
            c.execute('DELETE FROM auth_codes WHERE email=%s AND purpose=%s AND code_hash=%s',(email,purpose,hashed))
        raise


@router.post('/auth/register')
def register(body: Signup, request: Request):
    limited('register:'+peer(request),10,3600)
    if not registration_open():raise HTTPException(403,'管理员暂时关闭了注册。')
    if status()['setup_required']:raise HTTPException(403,'请先完成管理员初始化。')
    if not mail_service.public()['ready']:raise HTTPException(503,'邮件服务尚未配置，请联系管理员。')
    email = email_key(body.email)
    limited('code:'+email+':register',1,60)
    with db.system_connection() as c:
        exists = c.execute('SELECT 1 FROM app_users WHERE email=%s',(email,)).fetchone()
    if not exists:
        issue_code(email,'register',{'password_hash':passwords.hash(body.password),'display_name':body.display_name})
    return {'message':'若邮箱可用于注册，验证码已发送，请检查收件箱和垃圾邮件。'}


def consume(c,email,purpose,code):
    row = c.execute('SELECT *,expires_at>now() AS valid FROM auth_codes WHERE email=%s AND purpose=%s FOR UPDATE',(email,purpose)).fetchone()
    if not row or not row['valid'] or row['attempts']>=5:return None
    salt,expected = row['code_hash'].split(':',1)
    if not hmac.compare_digest(expected,code_proof(salt,code)):
        c.execute('UPDATE auth_codes SET attempts=attempts+1 WHERE email=%s AND purpose=%s',(email,purpose))
        return None
    c.execute('DELETE FROM auth_codes WHERE email=%s AND purpose=%s',(email,purpose))
    return json.loads(row['payload'])


def code_proof(salt,code):
    from . import server_secrets
    server_secrets.cipher()
    return hmac.new((config.DATA/'server-secret.key').read_bytes(),(salt+code).encode(),'sha256').hexdigest()


@router.post('/auth/verify')
def verify(body: Verify, request: Request, response: Response):
    limited('verify:'+peer(request),30,900)
    if not registration_open():raise HTTPException(403,'管理员暂时关闭了注册。')
    ident = None
    with db.system_connection() as c:
        payload = consume(c,email_key(body.email),'register',body.code)
        if payload:
            ident = 'user-'+uuid.uuid4().hex
            inserted = c.execute("""INSERT INTO app_users(id,email,display_name,password_hash,role,status,email_verified)
                VALUES (%s,%s,%s,%s,'user','active',true) ON CONFLICT(email) DO NOTHING""",
                (ident,email_key(body.email),payload['display_name'],payload['password_hash'])).rowcount
            if not inserted:ident=None
            else:
                c.execute("SELECT set_config('studio.user_id',%s,true)",(ident,))
                with as_user(ident):db.init_user(c)
    if not ident:raise HTTPException(400,'验证码无效、已过期或已使用，请重新申请。')
    return {'user':session(response,ident)}


@router.post('/auth/login')
def login(body: Credentials, request: Request, response: Response):
    limited('login-ip:'+peer(request),30,900)
    limited('login-email:'+email_key(body.email),15,900)
    with db.system_connection() as c:
        row = c.execute('SELECT * FROM app_users WHERE email=%s',(email_key(body.email),)).fetchone()
    good = verify_password(row['password_hash'] if row else None,body.password)
    if not good or not row or row['status']!='active':raise HTTPException(401,'邮箱或密码不正确，或账号已停用。')
    return {'user':session(response,row['id'])}


@router.post('/auth/logout')
def logout(request: Request,response: Response):
    with db.system_connection() as c:
        c.execute('DELETE FROM auth_sessions WHERE token_hash=%s',(digest(request.cookies.get(COOKIE,'')),))
    response.delete_cookie(COOKIE,path='/')
    return {'ok':True}


@router.post('/auth/forgot')
def forgot(body: EmailRequest,request: Request):
    limited('forgot:'+peer(request),10,3600)
    if not mail_service.public()['ready']:raise HTTPException(503,'邮件服务尚未配置，请联系管理员。')
    limited('code:'+email_key(body.email)+':reset',1,60)
    with db.system_connection() as c:
        row=c.execute("SELECT id FROM app_users WHERE email=%s AND status='active'",(email_key(body.email),)).fetchone()
    if row:issue_code(email_key(body.email),'reset',{'user_id':row['id']})
    return {'message':'若账号存在且可用，重置验证码已发送。'}


@router.post('/auth/reset')
def reset(body: Reset, request: Request):
    limited('reset:'+peer(request),30,900)
    ident=None
    encoded=passwords.hash(body.password)
    with db.system_connection() as c:
        payload=consume(c,email_key(body.email),'reset',body.code)
        if payload:
            ident=payload['user_id']
            c.execute('UPDATE app_users SET password_hash=%s,email_verified=true WHERE id=%s',(encoded,ident))
            c.execute('DELETE FROM auth_sessions WHERE user_id=%s',(ident,))
    if not ident:raise HTTPException(400,'验证码无效、已过期或已使用。')
    return {'message':'密码已重置，请使用新密码登录。'}


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=1,max_length=128)


@router.post('/auth/password')
def change_password(body:PasswordChange,request:Request,response:Response):
    ident=require_user();limited('password:'+ident,10,900)
    with db.system_connection() as c:
        row=c.execute('SELECT password_hash FROM app_users WHERE id=%s FOR UPDATE',(ident,)).fetchone()
        if not verify_password(row['password_hash'],body.current_password):raise HTTPException(400,'当前密码不正确。')
        c.execute('UPDATE app_users SET password_hash=%s WHERE id=%s',(passwords.hash(body.new_password),ident))
        c.execute('DELETE FROM auth_sessions WHERE user_id=%s',(ident,))
    response.delete_cookie(COOKIE,path='/')
    return {'message':'密码已更新，请重新登录。'}


def admin():
    with db.system_connection() as c:
        row=c.execute("SELECT * FROM app_users WHERE id=%s AND status='active' AND role='admin'",(require_user(),)).fetchone()
    if not row:raise HTTPException(403,'需要管理员权限。')
    return row


@router.get('/admin/users')
def users(page:int=1,query:str=''):
    admin();page=max(1,min(page,100000));query=query[:100]
    with db.system_connection() as c:
        pattern='%'+query+'%'
        total=c.execute("SELECT count(*) FROM app_users WHERE status!='pending_setup' AND (email ILIKE %s OR display_name ILIKE %s)",(pattern,pattern)).fetchone()[0]
        rows=c.execute("SELECT * FROM app_users WHERE status!='pending_setup' AND (email ILIKE %s OR display_name ILIKE %s) ORDER BY created_at DESC LIMIT 30 OFFSET %s",(pattern,pattern,(page-1)*30)).fetchall()
    return {'items':[public_user(r) for r in rows],'total':total,'page':page}


class UserChange(BaseModel):
    role: Literal['admin','user']
    status: Literal['active','disabled']


@router.put('/admin/users/{ident}')
def update_user(ident:str,body:UserChange):
    actor=admin()
    if ident==actor['id'] and (body.role!='admin' or body.status!='active'):raise HTTPException(400,'不能在这里停用自己或移除自己的管理员权限。')
    with db.system_connection() as c:
        db.lock(c,'admin-users')
        row=c.execute('SELECT * FROM app_users WHERE id=%s FOR UPDATE',(ident,)).fetchone()
        if not row or row['status']=='pending_setup':raise HTTPException(404,'用户不存在。')
        if row['role']=='admin' and row['status']=='active' and (body.role!='admin' or body.status!='active'):
            if c.execute("SELECT count(*) FROM app_users WHERE role='admin' AND status='active'").fetchone()[0]<=1:
                raise HTTPException(400,'至少保留一位有效管理员。')
        c.execute('UPDATE app_users SET role=%s,status=%s WHERE id=%s',(body.role,body.status,ident))
        c.execute('DELETE FROM auth_sessions WHERE user_id=%s',(ident,))
        c.execute('INSERT INTO admin_events(actor_id,target_id,action) VALUES (%s,%s,%s)',(actor['id'],ident,'user:'+body.role+':'+body.status))
    return {'ok':True}


@router.get('/admin/settings')
def admin_settings():
    admin();return {'registration_open':registration_open(),'smtp':mail_service.public()}


class RegistrationSetting(BaseModel):
    enabled: bool


@router.put('/admin/registration')
def registration(body:RegistrationSetting):
    actor=admin()
    with db.system_connection() as c:
        c.execute("INSERT INTO server_settings VALUES ('registration_open',%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('true' if body.enabled else 'false',))
        c.execute('INSERT INTO admin_events(actor_id,action) VALUES (%s,%s)',(actor['id'],'registration:'+str(body.enabled)))
    return {'registration_open':body.enabled}


@router.put('/admin/smtp')
def smtp_save(body:mail_service.MailSettings):
    actor=admin();result=mail_service.save(body)
    with db.system_connection() as c:c.execute("INSERT INTO admin_events(actor_id,action) VALUES (%s,'smtp:update')",(actor['id'],))
    return result


@router.post('/admin/smtp/test')
def smtp_test():
    actor=admin();limited('smtp-test:'+actor['id'],3,300)
    mail_service.send_code(actor['email'],f'{secrets.randbelow(1_000_000):06d}','register')
    return {'message':'测试邮件已发送至当前管理员邮箱。'}


@router.get('/admin/events')
def events():
    admin()
    with db.system_connection() as c:return [dict(r) for r in c.execute('SELECT e.*,u.email AS actor_email FROM admin_events e LEFT JOIN app_users u ON u.id=e.actor_id ORDER BY e.id DESC LIMIT 100')]
