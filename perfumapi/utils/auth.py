"""Protect catalog ingestion endpoints with a private service token."""
import hmac
import os
from fastapi import Header, HTTPException, Depends

async def verify_admin(authorization: str | None = Header(default=None)):
    expected=os.getenv('PERFUMAPI_ADMIN_TOKEN','')
    if not expected:
        raise HTTPException(503,'Catalog ingestion is not configured')
    scheme, _, supplied=(authorization or '').partition(' ')
    if scheme.lower()!='bearer' or not hmac.compare_digest(supplied,expected):
        raise HTTPException(401,'Invalid service credentials')
    return {'id':'sillage-backend'}

get_current_user=verify_admin
