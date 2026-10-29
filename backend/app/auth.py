from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import User


def current_user(db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).order_by(User.id).limit(1))
    if not user:
        user = User(email="local", password_hash="")
        db.add(user)
        db.commit()
    return user
