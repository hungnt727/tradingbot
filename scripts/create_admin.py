"""Bootstrap the first admin account for the Web Control Panel (Phase 6).

Interactive: prompts for username + password via getpass (no plaintext in shell
history). Idempotent: refuses to overwrite an existing username.

    python scripts/create_admin.py
"""
import getpass
import sys

from sqlalchemy import select

from app_db.models.user import User
from web.services.auth_service import AuthService


class UserExistsError(Exception):
    """Raised when creating a user whose username already exists."""


def create_admin_user(session_factory, username: str, password: str, is_admin: bool = True) -> User:
    with session_factory() as db:
        if db.scalar(select(User).where(User.username == username)) is not None:
            raise UserExistsError(f"User '{username}' already exists.")
        user = User(
            username=username,
            password_hash=AuthService.hash_password(password),
            is_admin=is_admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def main() -> None:
    username = input("Admin username: ").strip()
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.")
        sys.exit(1)

    from app_db.session import SessionLocal

    try:
        user = create_admin_user(SessionLocal, username, password)
    except UserExistsError as e:
        print(str(e))
        sys.exit(1)
    print(f"Admin '{user.username}' created (id={user.id}).")


if __name__ == "__main__":
    main()
