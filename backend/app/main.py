import os, secrets, logging, time, asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Depends, HTTPException, Request, Response, UploadFile, File, Query
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from pwdlib import PasswordHash
from .db import Base, engine, SessionLocal
from .models import User, Perfume, Profile, Usage, Feedback, FragellaUsage
from .security import encrypt_secret, decrypt_secret
from .ai import generate, get_catalog
import httpx

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'))
app=FastAPI(title='Sillage AI API',docs_url=None,redoc_url=None)
_rate_buckets={}
_fragella_cache={}
_fragella_lock=asyncio.Lock()

def _catalog_score(value,kind):
    text=str(value or '').casefold()
    if not text: return None
    if kind=='longevity':
        if any(x in text for x in ('very weak','very short','poor')): return 1
        if any(x in text for x in ('weak','short','soft')): return 2
        if 'moderate' in text or 'average' in text: return 3
        if any(x in text for x in ('very long','excellent','eternal')): return 5
        if 'long' in text or 'good' in text: return 4
    else:
        if any(x in text for x in ('intimate','very weak','very soft')): return 1
        if any(x in text for x in ('soft','weak','light')): return 2
        if 'moderate' in text or 'average' in text: return 3
        if any(x in text for x in ('enormous','very strong','beast')): return 5
        if 'strong' in text or 'heavy' in text: return 4
    return None

def _infer_family(notes):
    groups={
        'Woody':('cedar','sandalwood','vetiver','patchouli','oud','agarwood','oakmoss','cypress','guaiac','cashmere wood'),
        'Floral':('rose','jasmine','tuberose','peony','iris','violet','ylang','lily','magnolia','orange blossom'),
        'Citrus':('bergamot','lemon','grapefruit','orange','lime','mandarin','yuzu','citron'),
        'Amber':('amber','vanilla','labdanum','benzoin','myrrh','resin','incense'),
        'Aromatic':('lavender','sage','rosemary','basil','mint','thyme','fougere'),
        'Gourmand':('chocolate','caramel','praline','coffee','cacao','honey','tonka','almond','sugar'),
        'Spicy':('pepper','clove','nutmeg','saffron','ginger','cardamom','cinnamon'),
        'Aquatic':('marine','sea water','aquatic','ozone','salt','water lily')}
    text=' '.join(str(n).casefold() for n in notes)
    ranked=sorted(((sum(text.count(term) for term in terms),name) for name,terms in groups.items()),reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] else ''
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
password_hash=PasswordHash.recommended()
COOKIE=os.getenv('SESSION_COOKIE','sillage_session')
PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL','').strip()

def _normalized_origin(value):
    try:
        parsed=urlsplit((value or '').strip())
        scheme=parsed.scheme.lower()
        if scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment:
            return None
        port=parsed.port
        if port==(443 if scheme=='https' else 80): port=None
        return scheme,parsed.hostname.rstrip('.').lower(),port
    except ValueError:
        return None

def _cookies_secure():
    configured=_normalized_origin(PUBLIC_BASE_URL)
    return os.getenv('COOKIE_SECURE','false').lower()=='true' or bool(configured and configured[0]=='https')

@app.on_event('startup')
def startup():
    if PUBLIC_BASE_URL and not _normalized_origin(PUBLIC_BASE_URL):
        raise RuntimeError('PUBLIC_BASE_URL must be an http(s) origin such as https://sillage.example.com')
    Base.metadata.create_all(engine)

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
            if PUBLIC_BASE_URL:
                expected_origin=_normalized_origin(PUBLIC_BASE_URL)
            else:
                host=(request.headers.get('x-forwarded-host') or request.headers.get('host','')).split(',')[0].strip()
                scheme=(request.headers.get('x-forwarded-proto') or request.url.scheme).split(',')[0].strip()
                expected_origin=_normalized_origin(f'{scheme}://{host}')
            if not expected_origin or _normalized_origin(origin)!=expected_origin:
                raise HTTPException(403,'Origin rejected. Check PUBLIC_BASE_URL or the proxy Host and X-Forwarded-Proto headers.')

class Register(BaseModel): email: EmailStr; password: str=Field(min_length=8,max_length=200)
class Login(BaseModel): email: EmailStr; password: str
class PerfumeIn(BaseModel):
    name: str=Field(min_length=1,max_length=160); brand: str=Field(default='',max_length=160); family: str=Field(default='',max_length=100)
    notes: list[str]=Field(default_factory=list,max_length=30); longevity: int|None=Field(default=None,ge=1,le=5); projection: int|None=Field(default=None,ge=1,le=5); season: list[str]=Field(default_factory=list,max_length=8)
    release_year: int|None=Field(default=None,ge=1000,le=2200); gender: str=Field(default='',max_length=40); concentration: str=Field(default='',max_length=80)
    secondary_family: str=Field(default='',max_length=100); character: str=Field(default='',max_length=500)
    description: str=Field(default='',max_length=2000); source_url: str=Field(default='',max_length=500); wear_times: list[str]=Field(default_factory=list,max_length=8)
    catalog_image_url: str|None=Field(default=None,max_length=1000)
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
    response.set_cookie('sillage_csrf',token,httponly=False,samesite='lax',secure=_cookies_secure(),max_age=60*60*24)
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
    response.set_cookie(COOKIE,token,httponly=True,samesite='lax',secure=_cookies_secure(),max_age=60*60*24*14)
    response.set_cookie('sillage_uid',str(user.id),httponly=True,samesite='lax',secure=_cookies_secure(),max_age=60*60*24*14)
    response.set_cookie('sillage_csrf',token,httponly=False,samesite='lax',secure=_cookies_secure(),max_age=60*60*24*14)

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

def _fragella_notes(row):
    notes=row.get('Notes') or {}
    result=[]
    if isinstance(notes,dict):
        for tier in ('Top','Middle','Base'):
            values=notes.get(tier) or notes.get(tier.lower()) or []
            if isinstance(values,list):
                result.extend((str(item.get('name') or '') if isinstance(item,dict) else str(item))[:80] for item in values)
    if not result:
        values=row.get('General Notes') or []
        if isinstance(values,list): result=[str(v)[:80] for v in values if v]
    return list(dict.fromkeys(x for x in result if x))[:30]

def _fragella_seasons(row):
    values=row.get('Season Ranking') or []
    if isinstance(values,list):
        def score(item):
            try: return float(item.get('score',item.get('value',0)))
            except (AttributeError,TypeError,ValueError): return 0
        return [str(x.get('name')) for x in sorted((x for x in values if isinstance(x,dict) and x.get('name')),key=score,reverse=True)[:4]]
    return []

def _normalize_fragella(row):
    if not isinstance(row,dict) or not row.get('Name'): return None
    notes=_fragella_notes(row)
    accords=row.get('Main Accords') or []
    family=str(accords[0] if isinstance(accords,list) and accords else '')
    longevity_label=str(row.get('Longevity') or '')
    projection_label=str(row.get('Sillage') or '')
    image_url=str(row.get('Image URL Transparent') or row.get('Image URL') or '')
    occasions=row.get('Occasion Ranking') or []
    wear_times=[]
    if isinstance(occasions,list):
        wear_times=[str(x['name']) for x in occasions if isinstance(x,dict) and x.get('name')][:4]
    return {'provider_id':str(row.get('_id') or '')[:200],
        'name':str(row['Name'])[:160],'brand':str(row.get('Brand') or '')[:160],
        'family':family[:100] or _infer_family(notes),'secondary_family':'',
        'character':('Main accords: '+', '.join(str(x) for x in accords[:6]))[:500] if isinstance(accords,list) else '',
        'notes':notes,'longevity':_catalog_score(longevity_label,'longevity'),
        'projection':_catalog_score(projection_label,'projection'),
        'longevity_label':longevity_label,'projection_label':projection_label,
        'gender':str(row.get('Gender') or '')[:40],'release_year':int(row['Year']) if str(row.get('Year','')).isdigit() else None,
        'concentration':str(row.get('OilType') or '')[:80],
        'description':'','season':_fragella_seasons(row),'wear_times':wear_times,
        'source_url':'https://api.fragella.com/','image_url':image_url}

@app.get('/api/catalog/search')
async def catalog_search(q:str=Query(min_length=2,max_length=80),user:User=Depends(current_user),db:Session=Depends(get_db)):
    query=' '.join(q.split())
    # Reuse saved collection data first. Existing fragrances cost no Fragella requests.
    perfumes=db.scalars(select(Perfume).where(Perfume.user_id==user.id).order_by(Perfume.name)).all()
    local=[p for p in perfumes if query.casefold() in f'{p.brand} {p.name}'.casefold()][:10]
    if local:
        rows=[]
        for p in local:
            item=serialize_perfume(p)
            item.update({'longevity_label':'','projection_label':'','image_url':'','in_collection':True})
            rows.append(item)
        return rows
    key=os.getenv('FRAGELLA_API_KEY','').strip()
    if not key: raise HTTPException(503,'Fragella API key is not configured on the server. You can still add the fragrance manually.')
    cache_key=query.casefold()
    cached=_fragella_cache.get(cache_key)
    if cached and time.monotonic()-cached[0]<3600: return cached[1]
    async with _fragella_lock:
        cached=_fragella_cache.get(cache_key)
        if cached and time.monotonic()-cached[0]<3600: return cached[1]
        now=datetime.now(timezone.utc); window_start=now-timedelta(days=30)
        requests_used=db.scalar(select(func.count(FragellaUsage.id)).where(FragellaUsage.requested_at>=window_start)) or 0
        if requests_used>=20:
            raise HTTPException(429,'Fragella request limit reached (20 searches per rolling 30 days). Saved fragrances and manual entry still work.')
        db.add(FragellaUsage(requested_at=now)); db.commit()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0,connect=3.0),follow_redirects=False) as client:
                response=await client.get('https://api.fragella.com/api/v1/fragrances',params={'search':query,'limit':10},headers={'x-api-key':key})
                if response.status_code==401: raise HTTPException(503,'Fragella rejected the API key. Check FRAGELLA_API_KEY on the server.')
                if response.status_code==429: raise HTTPException(429,'Fragella rate limit reached. Try again later.')
                response.raise_for_status()
                payload=response.json()
            raw=payload.get('data',[]) if isinstance(payload,dict) else payload
            if not isinstance(raw,list): raise ValueError('Unexpected Fragella response')
            result=[item for item in (_normalize_fragella(row) for row in raw[:10]) if item]
            _fragella_cache[cache_key]=(time.monotonic(),result)
            return result
        except HTTPException: raise
        except (httpx.HTTPError,ValueError,TypeError) as exc:
            logging.warning('Fragella catalog request failed type=%s',type(exc).__name__)
            raise HTTPException(503,'Fragella search is unavailable right now. You can still add the fragrance manually.')

def serialize_perfume(p):
    return {'id':p.id,'name':p.name,'brand':p.brand,'family':p.family,'secondary_family':p.secondary_family,'character':p.character,'notes':p.notes or [],'longevity':p.longevity,'projection':p.projection,'season':p.season or [],'image_path':f'/api/collection/{p.id}/image' if p.image_path else None,'feedback_score':p.feedback_score,'release_year':p.release_year,'gender':p.gender,'concentration':p.concentration,'description':p.description,'source_url':p.source_url,'wear_times':p.wear_times or []}

async def _save_fragella_image(url:str|None)->str|None:
    if not url: return None
    try:
        parts=urlsplit(url)
        if parts.scheme!='https' or parts.hostname!='cdn.fragella.com' or parts.username or parts.password or parts.port not in (None,443): return None
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0,connect=3.0),follow_redirects=False) as client:
            async with client.stream('GET',url) as response:
                response.raise_for_status()
                if int(response.headers.get('content-length','0') or 0)>5*1024*1024: return None
                mime=response.headers.get('content-type','').split(';')[0].lower()
                chunks=[]; size=0
                async for chunk in response.aiter_bytes():
                    size+=len(chunk)
                    if size>5*1024*1024: return None
                    chunks.append(chunk)
            suffix={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}.get(mime)
            if not suffix: return None
            name=secrets.token_hex(16)+'.'+suffix
            (UPLOAD_DIR/name).write_bytes(b''.join(chunks))
            return name
    except (httpx.HTTPError,ValueError,OSError):
        logging.info('Fragella bottle image unavailable')
        return None

@app.post('/api/collection',dependencies=[Depends(csrf)])
async def add_perfume(data:PerfumeIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    values=data.model_dump(); image_url=values.pop('catalog_image_url',None)
    duplicate=db.scalar(select(Perfume).where(Perfume.user_id==user.id,func.lower(Perfume.name)==data.name.casefold(),func.lower(Perfume.brand)==data.brand.casefold()))
    if duplicate: raise HTTPException(409,'This fragrance is already in your collection.')
    image_name=await _save_fragella_image(image_url)
    p=Perfume(user_id=user.id,image_path=image_name,**values); db.add(p); user.preference_revision+=1; db.commit(); db.refresh(p); return serialize_perfume(p)

@app.put('/api/collection/{perfume_id}',dependencies=[Depends(csrf)])
def update_perfume(perfume_id:int,data:PerfumeIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    for k,v in data.model_dump(exclude={'catalog_image_url'}).items(): setattr(p,k,v)
    user.preference_revision+=1; db.commit(); return serialize_perfume(p)

@app.delete('/api/collection/{perfume_id}',dependencies=[Depends(csrf)])
def delete_perfume(perfume_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    image_name=Path(p.image_path).name if p.image_path else ''
    db.delete(p); user.preference_revision+=1; db.commit()
    if image_name: (UPLOAD_DIR/image_name).unlink(missing_ok=True)
    return {'ok':True}

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

@app.get('/api/collection/{perfume_id}/image')
def collection_image(perfume_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p or not p.image_path: raise HTTPException(404,'Fragrance image not found')
    filename=Path(p.image_path).name
    path=UPLOAD_DIR/filename
    if not filename or not path.is_file(): raise HTTPException(404,'Fragrance image not found')
    return FileResponse(path,headers={'Cache-Control':'private, max-age=3600'})

@app.post('/api/collection/{perfume_id}/image',dependencies=[Depends(csrf)])
async def upload_image(perfume_id:int,file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    p=db.scalar(select(Perfume).where(Perfume.id==perfume_id,Perfume.user_id==user.id))
    if not p: raise HTTPException(404,'Fragrance not found')
    if file.content_type not in ('image/jpeg','image/png','image/webp'): raise HTTPException(415,'Use JPEG, PNG or WebP')
    data=await file.read(5*1024*1024+1)
    if len(data)>5*1024*1024: raise HTTPException(413,'Image is larger than 5 MB')
    suffix={'image/jpeg':'jpg','image/png':'png','image/webp':'webp'}[file.content_type]
    path=UPLOAD_DIR; path.mkdir(parents=True,exist_ok=True); name=f'{user.id}-{perfume_id}-{secrets.token_hex(8)}.{suffix}'; (path/name).write_bytes(data)
    previous=Path(p.image_path).name if p.image_path else ''
    p.image_path=name; db.commit()
    if previous and previous!=name: (path/previous).unlink(missing_ok=True)
    return {'image_path':f'/api/collection/{perfume_id}/image'}
