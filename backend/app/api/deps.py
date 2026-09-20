"""Shared FastAPI dependencies: the authenticated patient."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.models.db import get_db
from app.models.entities import User
from app.services import auth_service

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=401, detail="Not authenticated.", headers={"WWW-Authenticate": "Bearer"}
        )
    user_id = auth_service.decode_token(creds.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=401, detail="Invalid or expired token.", headers={"WWW-Authenticate": "Bearer"}
        )
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Account no longer exists.")
    return user
