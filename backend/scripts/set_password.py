"""Set a user's login password by email (Phase 8 auth).

Usage (run from backend/, with the venv active and DATABASE_URL set):

    EMAIL=chris@preapprovemeapp.com PASSWORD='...' PYTHONPATH=. \
        .venv/bin/python scripts/set_password.py

Credentials are read from env vars rather than argv so they don't show up in
`ps`. Only the bcrypt hash is stored — never the plaintext.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import User
from app.services import auth as auth_service


def main() -> None:
    email = os.environ.get("EMAIL")
    password = os.environ.get("PASSWORD")
    if not email or not password:
        sys.exit("Set EMAIL and PASSWORD environment variables.")

    session = SessionLocal()
    try:
        user = session.execute(
            select(User).where(func.lower(User.email) == email.strip().lower())
        ).scalar_one_or_none()
        if user is None:
            sys.exit(f"No user found with email {email!r}.")
        user.password_hash = auth_service.hash_password(password)
        session.commit()
        print(f"Password set for user id={user.id} name={user.name} email={user.email}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
