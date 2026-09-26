import json
import smtplib
import ssl
from email.message import EmailMessage
from pydantic import BaseModel, Field, EmailStr
from typing import Literal
from . import db, server_secrets


class MailSettings(BaseModel):
    host: str = Field(default='', max_length=253, pattern=r'^[a-zA-Z0-9.\-]*$')
    port: int = Field(default=465, ge=1, le=65535)
    security: Literal['ssl','starttls'] = 'ssl'
    username: str = Field(default='', max_length=254)
    password: str = Field(default='', max_length=1024)
    sender: EmailStr
    sender_name: str = Field(default='知序创作平台', max_length=60, pattern=r'^[^\r\n]*$')


def settings():
    with db.system_connection() as c:
        row = c.execute("SELECT value FROM server_settings WHERE key='smtp'").fetchone()
    return json.loads(row['value']) if row else {}


def public():
    value = settings()
    return {**{k:v for k,v in value.items() if k != 'password'}, 'password_configured':bool(value.get('password')), 'ready':bool(value.get('host') and value.get('sender'))}


def save(body):
    previous = settings()
    value = body.model_dump()
    if body.password:
        value['password'] = server_secrets.encrypt(body.password)
    else:
        if previous.get('password') and any(value.get(k)!=previous.get(k) for k in ('host','username','port','security')):
            raise ValueError('更换邮件服务器或账号时，请重新填写 SMTP 密码。')
        value['password'] = previous.get('password','')
    with db.system_connection() as c:
        c.execute("INSERT INTO server_settings VALUES ('smtp',%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (db.dump(value),))
    return public()


def send_code(recipient, code, purpose):
    value = settings()
    if not value.get('host'):
        raise ValueError('邮件服务尚未配置，请联系管理员。')
    message = EmailMessage()
    message['Subject'] = '知序 · '+('注册验证' if purpose=='register' else '重置密码')
    from email.utils import formataddr
    message['From'] = formataddr((value.get('sender_name','知序'),value['sender']))
    message['To'] = recipient
    message.set_content(f'你的验证码是：{code}\n\n10 分钟内有效，请勿向他人透露。若非本人操作，请忽略此邮件。')
    try:
        context = ssl.create_default_context()
        cls = smtplib.SMTP_SSL if value['security']=='ssl' else smtplib.SMTP
        kwargs = {'context':context} if value['security']=='ssl' else {}
        with cls(value['host'], value['port'], timeout=15, **kwargs) as smtp:
            if value['security']=='starttls':
                smtp.ehlo();smtp.starttls(context=context);smtp.ehlo()
            if value.get('username'):
                smtp.login(value['username'],server_secrets.decrypt(value.get('password','')))
            smtp.send_message(message)
    except (OSError,smtplib.SMTPException):
        raise ValueError('邮件发送失败，请管理员检查 SMTP 配置后重试。') from None
