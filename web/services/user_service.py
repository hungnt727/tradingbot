"""User administration service (Phase 6 slice 0003).

Functions take a ``session_factory`` (same convention as
``scripts.create_admin.create_admin_user``) and return detached ``User``
instances. Authorization (admin-only) is enforced at the route layer via the
``require_admin`` dependency; self-delete protection lives here because it is a
data-integrity rule, not an access-control one.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app_db.models.user import User
from web.services.auth_service import AuthService


class UserExistsError(Exception):
    """Raised when creating a user whose username is already taken."""


class SelfDeleteError(Exception):
    """Raised when an admin tries to delete their own account."""


class UserNotFoundError(Exception):
    """Raised when targeting a user id that does not exist."""


def create_user(
    session_factory,
    username: str,
    password: str,
    is_admin: bool = False,
    default_telegram_chat_id: str | None = None,
) -> User:
    with session_factory() as db:
        if db.scalar(select(User).where(User.username == username)) is not None:
            raise UserExistsError(f"User '{username}' already exists.")
        user = User(
            username=username,
            password_hash=AuthService.hash_password(password),
            is_admin=is_admin,
            default_telegram_chat_id=default_telegram_chat_id or None,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError as exc:  # unique race / constraint
            db.rollback()
            raise UserExistsError(f"User '{username}' already exists.") from exc
        db.refresh(user)
        db.expunge(user)
        return user


def reset_password(session_factory, user_id: int, new_password: str) -> User:
    with session_factory() as db:
        user = db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(f"User id={user_id} not found.")
        user.password_hash = AuthService.hash_password(new_password)
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def delete_user(session_factory, user_id: int, acting_user_id: int) -> None:
    if user_id == acting_user_id:
        raise SelfDeleteError("You cannot delete your own account.")
    with session_factory() as db:
        user = db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(f"User id={user_id} not found.")
        db.delete(user)  # processes + signals cascade at the DB level
        db.commit()


def list_users(session_factory) -> list[User]:
    with session_factory() as db:
        users = list(db.scalars(select(User).order_by(User.id)))
        for u in users:
            db.expunge(u)
        return users


def set_default_chat_id(session_factory, user_id: int, chat_id: str | None) -> User:
    """Update the user's own default Telegram chat ID (used by /settings)."""
    with session_factory() as db:
        user = db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(f"User id={user_id} not found.")
        user.default_telegram_chat_id = (chat_id or "").strip() or None
        db.commit()
        db.refresh(user)
        db.expunge(user)
        return user


def change_password(session_factory, user_id: int, old_password: str, new_password: str) -> bool:
    """Change the user's password after verifying the old one.

    Returns ``False`` (without writing) when ``old_password`` is wrong.
    """
    with session_factory() as db:
        user = db.get(User, user_id)
        if user is None:
            raise UserNotFoundError(f"User id={user_id} not found.")
        if not AuthService.verify_password(old_password, user.password_hash):
            return False
        user.password_hash = AuthService.hash_password(new_password)
        db.commit()
        return True
