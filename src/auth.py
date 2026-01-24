import os
from fastapi import Depends, HTTPException, Header

# Configuration
SECRET_TOKEN = os.getenv("AUTH_SECRET", "change-me-in-prod")

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
    """
    if is_dev_mode():
        return "dev-user"
        
    if token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid authentication credentials")
    return "admin-user"
