import os
import jwt
from fastapi import Depends, HTTPException, Header

# Configuration
# AUTH_ADMIN_SECRET is used by the dashboard to sign internal admin requests
SECRET_KEY = os.getenv("AUTH_ADMIN_SECRET") or os.getenv("AUTH_SECRET", "change-me-in-prod")

def is_dev_mode() -> bool:
    mode = os.getenv("MODE", "").lower()
    return mode == "dev" or mode == "development"

def verify_token_header(authorization: str = Header(None)) -> str:
    """
    Extract and verify Bearer token from header.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")
    return authorization.split(" ")[1]

async def require_auth(token: str = Depends(verify_token_header)):
    """
    Enforce authentication. Returns principal.
    Supports both legacy static tokens and modern signed JWTs.
    """
    if is_dev_mode():
        return "dev-user"
        
    # 1. Try modern JWT validation
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub", "admin-user")
    except jwt.PyJWTError:
        # 2. Fallback to legacy static token
        if token == SECRET_KEY:
            return "admin-user"
        
        raise HTTPException(status_code=403, detail="Invalid authentication credentials")
