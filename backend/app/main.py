import os, secrets, logging, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from pwdlib import PasswordHash
from .db import Base, engine, SessionLocal
from .models import User, Perfume, Profile, Usage, Feedback
from .security import encrypt_secret, decrypt_secret
from .ai import generate, get_catalog
import httpx

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
app=FastAPI(title='Sillage AI API',docs_url=None,redoc_url=None)
_rate_buckets={}
_catalog_cache={}
@app.middleware('http')
async def api_rate_limit(request:Request,call_next):
    if request.url.path.startswith('/api/') and request.method=='POST':
        ip=request.client.host if request.client else 'unknown'; now=time.monotonic(); bucket=_rate_buckets.setdefault(ip,[]); bucket[:]=[t for t in bucket if now-t<60]
        maximum=8 if request.url.path=='/api/recommendations' else 30
        if len(bucket)>=maximum: return JSONResponse(status_code=429,content={'detail':'Too many requests. Please wait and try again.'})
        bucket.append(now)
    return await call_next(request)
DATA_DIR=Path(os.getenv('APP_DATA_DIR','/app/data'))
UPLOAD_DIR=DATA_DIR/'uploads'
UPLOAD_DIR.mkdir(parents=True,exist_ok=True)
app.mount('/uploads',StaticFiles(directory=str(UPLOAD_DIR)),name='uploads')
password_hash=PasswordHash.recommended()
COOKIE=os.getenv('SESSION_COOKIE','sillage_session')

@app.on_event('startup')
def startup(): Base.metadata.create_all(engine)

@app.get('/health')
def health(): return {'status':'ok'}

def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

def current_user(request: Request, db: Session=Depends(get_db)) -> User:
    sid=request.cookies.get(COOKIE)
    if not sid: raise HTTPException(401,'Sign in required')
    uid=request.cookies.get('sillage_uid')
    try: user=db.get(User,int(uid or ''))
    except ValueError: user=None
    if not user or not secrets.compare_digest(sid, request.cookies.get('sillage_csrf','')): raise HTTPException(401,'Sign in required')
    return user

def csrf(request: Request):
    if request.method not in ('GET','HEAD','OPTIONS'):
        expected=request.cookies.get('sillage_csrf','')
        supplied=request.headers.get('X-CSRF-Token','')
        origin=request.headers.get('origin')
        if not expected or not secrets.compare_digest(expected,supplied): raise HTTPException(403,'CSRF validation failed')
        if origin:
            host=request.headers.get('x-forwarded-host') or request.headers.get('host','')
            scheme=request.headers.get('x-forwarded-proto') or request.url.scheme
            expected=f'{scheme}://{host}'.rstrip('/')
            if not secrets.compare_digest(origin.rstrip('/'),expected): raise HTTPException(403,'Origin rejected')

class Register(BaseModel): email: EmailStr; password: str=Field(min_length=8,max_length=200)
class Login(BaseModel): email: EmailStr; password: str
class PerfumeIn(BaseModel):
    name: str=Field(min_length=1,max_length=160); brand: str=Field(default='',max_length=160); family: str=Field(default='',max_length=100)
    notes: list[str]=Field(default_factory=list,max_length=30); longevity: int=Field(default=3,ge=1,le=5); projection: int=Field(default=3,ge=1,le=5); season: list[str]=Field(default_factory=list,max_length=8)
class PrefsIn(BaseModel): preferences: dict
class SettingsIn(BaseModel):
    mode: str=Field(default='free',pattern='^(free|economy|smart)$')
    model: str=Field(default='openrouter/free',max_length=200); fallback_model: str=Field(default='',max_length=200)
    max_request_tokens: int=Field(default=5000,ge=256,le=32000); max_output_tokens: int=Field(default=700,ge=32,le=4096)
    temperature: float=Field(default=.5,ge=0,le=2); monthly_budget_usd: float=Field(default=2.5,ge=0,le=10000); total_budget_usd: float=Field(default=2.5,ge=0,le=10000)
    request_cost_ceiling_usd: float|None=Field(default=None,ge=0); cache_enabled: bool=True
class RecommendContext(BaseModel):
    model_config=ConfigDict(extra='forbid')
    occasion: str=Field(default='',max_length=80); weather: str=Field(default='',max_length=80)
    temperature: float|None=Field(default=None,ge=-80,le=70); humidity: float|None=Field(default=None,ge=0,le=100)
    location: str=Field(default='',max_length=120); refresh: bool=False
class RecommendIn(BaseModel):
    feature: str=Field(default='daily',pattern='^(daily|layering|travel|other)$')
    context: RecommendContext=Field(default_factory=RecommendContext)
    candidate_ids: list[int]|None=Field(default=None,max_length=50)
class FeedbackIn(BaseModel): perfume_id: int; score: int=Field(ge=-1,le=1); note: str=Field(default='',max_length=500)

@app.get('/api/auth/status')
def auth_status(request:Request,db:Session=Depends(get_db)):
    user=None
    try: user=current_user(request,db)
    except HTTPException: pass
    return {'configured':db.scalar(select(func.count(User.id)))>0,'authenticated':bool(user),'email':user.email if user else None}

@app.get('/api/auth/csrf')
def csrf_token(response:Response):
    token=secrets.token_urlsafe(32)
    response.set_cookie('sillage_csrf',token,httponly=False,samesite='lax',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=60*60*24)
    return {'ok':True}

@app.post('/api/auth/register',dependencies=[Depends(csrf)])
def register(data:Register,response:Response,db:Session=Depends(get_db)):
    if db.scalar(select(func.count(User.id))): raise HTTPException(403,'Registration is closed. Ask an administrator to create accounts.')
    user=User(email=data.email.lower(),password_hash=password_hash.hash(data.password),is_admin=True)
    db.add(user); db.flush(); db.add(Profile(user_id=user.id,preferences={},settings={})); db.commit()
    set_session(response,user)
    return {'email':user.email}

def set_session(response,user):
    token=secrets.token_urlsafe(32)
    response.set_cookie(COOKIE,token,httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=60*60*24*14)
    response.set_cookie('sillage_uid',str(user.id),httponly=True,samesite='lax',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=60*60*24*14)
    response.set_cookie('sillage_csrf',token,httponly=False,samesite='lax',secure=os.getenv('COOKIE_SECURE','false').lower()=='true',max_age=60*60*24*14)

@app.post('/api/auth/login',dependencies=[Depends(csrf)])
def login(data:Login,response:Response,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not password_hash.verify(data.password,user.password_hash): raise HTTPException(401,'Invalid email or password')
    set_session(response,user); return {'email':user.email}

@app.post('/api/auth/logout',dependencies=[Depends(csrf)])
def logout(response:Response):
    for name in (COOKIE,'sillage_uid','sillage_csrf'): response.delete_cookie(name)
    return {'ok':True}

@app.get('/api/me')
def me(user:User=Depends(current_user)): return {'id':user.id,'email':user.email,'is_admin':user.is_admin}

@app.get('/api/collection')
def collection(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.scalars(select(Perfume).where(Perfume.user_id==user.id).order_by(Perfume.name)).all()
    return [serialize_perfume(p) for p in rows]

@app.get('/api/catalog/search')
async def catalog_search(q:str=Query(min_length=2,max_length=80),user:User=Depends(current_user)):
    query=' '.join(q.split())
    cache_key=query.casefold()
    cached=_catalog_cache.get(cache_key)
    if cached and time.monotonic()-cached[0]<300: return cached[1]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0,connect=2.0)) as client:
            response=await client.get(f"{os.getenv('PERFUMAPI_URL','http://perfumapi:9000')}/perfumes/search/{quote(query,safe='')}",params={'limit':8})
            response.raise_for_status()
            rows=response.json()
        if not isinstance(rows,list): raise ValueError('Invalid catalog response')
        result=[]
        for row in rows[:8]:
            if not isinstance(row,dict) or not row.get('name'): continue
            notes=[]
            for field in ('notes_top','notes_middle','notes_base'):
                value=row.get(field) or []
                if isinstance(value,list): notes.extend(str(item)[:80] for item in value[:10] if item)
            result.append({'name':str(row['name'])[:160],'brand':str(row.get('brand') or '')[:160],
                'notes':notes[:30],'longevity':str(row.get('longevity') or ''),
                'sillage':str(row.get('sillage') or ''),'image_url':row.get('image_url') if isinstance(row.get('image_url'),str) else None})
        _catalog_cache[cache_key]=(time.monotonic(),result)
        return result
    except (httpx.HTTPError,ValueError):
        raise HTTPException(503,'Fragrance catalog is unavailable right now. You can still add the fragrance manually.')

def serialize_perfume(p):
    return {'id':p.id,'name':p.name,'brand':p.brand,'family':p.family,'notes':p.notes or [],'longevity':p.longevity,'projection':p.projection,'season':p.season or [],'image_path':p.image_path,'feedback_score':p.feedback_score}

@app.post('/api/collection',dependencies=[Depends(csrf)])
def add_perfume(data:PerfumeIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=Perfume(user_id=user.id,**data.model_dump()); db.add(p); user.preference_revision+=1; db.commit(); db.refresh(p); return serialize_perfume(p)

@app.put('/api/collection/{perfume_id}',dependencies=[Depends(csrf)])
def update_perfume(perfume_id:int,data:PerfumeIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    for k,v in data.model_dump().items(): setattr(p,k,v)
    user.preference_revision+=1; db.commit(); return serialize_perfume(p)

@app.delete('/api/collection/{perfume_id}',dependencies=[Depends(csrf)])
def delete_perfume(perfume_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    db.delete(p); user.preference_revision+=1; db.commit(); return {'ok':True}

@app.post('/api/preferences',dependencies=[Depends(csrf)])
def save_prefs(data:PrefsIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    profile=db.get(Profile,user.id); profile.preferences=data.preferences; user.preference_revision+=1; db.commit(); return {'ok':True}

@app.get('/api/preferences')
def get_prefs(user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.get(Profile,user.id); return p.preferences or {}

@app.get('/api/settings')
def get_settings(user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.get(Profile,user.id); s=dict(p.settings or {})
    s.pop('api_key',None); s['has_api_key']=bool(p.api_key_encrypted or os.getenv('OPENROUTER_API_KEY')); s.setdefault('mode',os.getenv('AI_MODE','free')); s.setdefault('model',os.getenv('OPENROUTER_MODEL','openrouter/free')); s.setdefault('fallback_model',os.getenv('OPENROUTER_FALLBACK_MODEL','')); s.setdefault('total_budget_usd',float(os.getenv('AI_TOTAL_BUDGET_USD','2.50'))); s.setdefault('monthly_budget_usd',float(os.getenv('AI_MONTHLY_BUDGET_USD','2.50'))); s.setdefault('max_output_tokens',int(os.getenv('AI_MAX_OUTPUT_TOKENS','700'))); s.setdefault('max_request_tokens',5000); s.setdefault('temperature',.5); s.setdefault('cache_enabled',True)
    return s

@app.put('/api/settings',dependencies=[Depends(csrf)])
def save_settings(data:SettingsIn,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.get(Profile,user.id)
    p.settings=data.model_dump()
    key=request.headers.get('x-openrouter-api-key')
    if key is not None:
        if not key.strip(): p.api_key_encrypted=None
        else:
            try: p.api_key_encrypted=encrypt_secret(key.strip())
            except RuntimeError as exc: raise HTTPException(503,str(exc))
    db.commit(); return {'ok':True,'has_api_key':bool(p.api_key_encrypted or os.getenv('OPENROUTER_API_KEY'))}

@app.get('/api/models')
async def models(user:User=Depends(current_user)):
    try:
        rows=await get_catalog(force=True)
        compatible=[]
        for m in rows:
            arch=m.get('architecture') or {}
            if m.get('id')=='openrouter/free' or ('text' in (arch.get('input_modalities') or []) and 'text' in (arch.get('output_modalities') or [])):
                compatible.append({'id':m.get('id'),'name':m.get('name'),'context_length':m.get('context_length'),'pricing':m.get('pricing',{}),'architecture':arch,'top_provider':m.get('top_provider',{}),'supported_parameters':m.get('supported_parameters',[])})
        return compatible
    except Exception as exc: raise HTTPException(502,'Could not fetch OpenRouter model catalog') from exc

@app.post('/api/recommendations',dependencies=[Depends(csrf)])
async def recommendations(data:RecommendIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return await generate(db,user,data.feature,data.context.model_dump(),data.candidate_ids)

@app.post('/api/feedback',dependencies=[Depends(csrf)])
def feedback(data:FeedbackIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==data.perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    db.add(Feedback(user_id=user.id,**data.model_dump())); p.feedback_score=max(-1,min(1,(p.feedback_score*.7+data.score*.3))); user.preference_revision+=1; db.commit(); return {'ok':True}

@app.get('/api/usage')
def usage(user:User=Depends(current_user),db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc); day=now.replace(hour=0,minute=0,second=0,microsecond=0); month=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    rows=db.scalars(select(Usage).where(Usage.user_id==user.id).order_by(Usage.created_at.desc()).limit(100)).all()
    all_count=db.scalar(select(func.count(Usage.id)).where(Usage.user_id==user.id)) or 0
    total=float(db.scalar(select(func.coalesce(func.sum(Usage.actual_cost),0)).where(Usage.user_id==user.id)) or 0)
    estimates=float(db.scalar(select(func.coalesce(func.sum(Usage.estimated_cost),0)).where(Usage.user_id==user.id,Usage.actual_cost.is_(None))) or 0)
    s=db.get(Profile,user.id).settings or {}; limit=float(s.get('total_budget_usd',os.getenv('AI_TOTAL_BUDGET_USD','2.50')))
    in_tok=db.scalar(select(func.coalesce(func.sum(Usage.input_tokens),0)).where(Usage.user_id==user.id)) or 0
    out_tok=db.scalar(select(func.coalesce(func.sum(Usage.output_tokens),0)).where(Usage.user_id==user.id)) or 0
    hits=db.scalar(select(func.count(Usage.id)).where(Usage.user_id==user.id,Usage.cache_hit.is_(True))) or 0
    breakdown={}
    for r in rows: breakdown[r.model]=breakdown.get(r.model,0)+1
    feature={}
    for r in rows: feature[r.feature]=feature.get(r.feature,0)+1
    return {'today_requests':db.scalar(select(func.count(Usage.id)).where(Usage.user_id==user.id,Usage.created_at>=day)) or 0,'month_requests':db.scalar(select(func.count(Usage.id)).where(Usage.user_id==user.id,Usage.created_at>=month)) or 0,'total_requests':all_count,'input_tokens':int(in_tok),'output_tokens':int(out_tok),'estimated_spending_usd':round(estimates,6),'provider_confirmed_spending_usd':round(total,6),'budget_remaining_usd':round(max(0,limit-total-estimates),4),'cache_hit_rate':round(hits/max(1,all_count),3),'model_breakdown':breakdown,'feature_breakdown':feature,'warning':(total+estimates)>=limit*.8,'recent':[{'feature':r.feature,'model':r.model,'input_tokens':r.input_tokens,'output_tokens':r.output_tokens,'estimated_cost_usd':r.estimated_cost,'actual_cost_usd':r.actual_cost,'cache_hit':r.cache_hit,'created_at':r.created_at.isoformat()} for r in rows]}

@app.post('/api/collection/{perfume_id}/image',dependencies=[Depends(csrf)])
async def upload_image(perfume_id:int,file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    if file.content_type not in ('image/jpeg','image/png','image/webp'): raise HTTPException(415,'Use JPEG, PNG or WebP')
    data=await file.read(5*1024*1024+1)
    if len(data)>5*1024*1024: raise HTTPException(413,'Image is larger than 5 MB')
    suffix={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[file.content_type]
    path=UPLOAD_DIR; path.mkdir(parents=True,exist_ok=True); name=f'{user.id}-{perfume_id}-{secrets.token_hex(8)}.{suffix}'; (path/name).write_bytes(data)
    p.image_path='/uploads/'+name; db.commit(); return {'image_path':p.image_path}
