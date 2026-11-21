import hashlib
import hmac
import secrets
from datetime import timedelta
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession
from .db import User, Session, get_db, now

SESSION_DAYS = 14

def make_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return salt, digest

def check_password(password, salt, expected):
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1).hex()
    return hmac.compare_digest(digest, expected)

def new_session(db:DbSession, user:User):
    raw = secrets.token_urlsafe(48)
    db.add(Session(token_hash=hashlib.sha256(raw.encode()).hexdigest(), user_id=user.id, expires_at=now()+timedelta(days=SESSION_DAYS)))
    db.commit()
    return raw

def current_user(authorization:str|None=Header(None),db:DbSession=Depends(get_db)):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Sign in to continue')
    hashed = hashlib.sha256(authorization[7:].encode()).hexdigest()
    row = db.get(Session, hashed)
    if not row or row.expires_at.replace(tzinfo=row.expires_at.tzinfo or now().tzinfo) <= now():
        raise HTTPException(401, 'Session expired. Please sign in again.')
    user=db.get(User,row.user_id)
    if not user:
        raise HTTPException(401,'Account unavailable')
    return user

def revoke_session(db, authorization):
    if authorization and authorization.startswith('Bearer '):
        row=db.get(Session,hashlib.sha256(authorization[7:].encode()).hexdigest())
        if row: db.delete(row); db.commit()

def must_owner(db,event,user):
    if event.owner_id!=user.id: raise HTTPException(403,'Only the event owner can do this')

def must_member(db,event,user):
    from .db import Member
    if event.owner_id==user.id: return 'owner'
    found=db.scalar(select(Member).where(Member.event_id==event.id,Member.user_id==user.id))
    if not found: raise HTTPException(403,'You are not an approved photographer for this event')
    return 'photographer'
