import uuid

import bcrypt
from sqlalchemy import select

from app_db.models.user import User


class AuthService:
    """Password hashing + Redis-backed opaque-session lifecycle.

    Sessions: cookie carries a random uuid4; Redis maps ``session:{id} -> user_id``
    with a sliding TTL. The id is unguessable and must exist in Redis to resolve.
    """

    SESSION_PREFIX = "session:"
    DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days

    def __init__(self, redis_conn, session_factory, session_ttl: int = DEFAULT_TTL_SECONDS):
        self.redis = redis_conn
        self.session_factory = session_factory
        self.session_ttl = session_ttl

    @staticmethod
    def hash_password(plain: str) -> str:
        return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

    def _key(self, session_id: str) -> str:
        return f"{self.SESSION_PREFIX}{session_id}"

    def create_session(self, user_id: int) -> str:
        session_id = uuid.uuid4().hex
        self.redis.setex(self._key(session_id), self.session_ttl, str(user_id))
        return session_id

    def resolve_session(self, session_id: str) -> User | None:
        if not session_id:
            return None
        key = self._key(session_id)
        raw = self.redis.get(key)
        if raw is None:
            return None
        self.redis.expire(key, self.session_ttl)  # sliding renewal
        with self.session_factory() as db:
            return db.get(User, int(raw))

    def destroy_session(self, session_id: str) -> None:
        self.redis.delete(self._key(session_id))

    def authenticate(self, username: str, password: str) -> User | None:
        with self.session_factory() as db:
            user = db.scalar(select(User).where(User.username == username))
            if user is None or not self.verify_password(password, user.password_hash):
                return None
            db.expunge(user)
            return user
