from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
from pathlib import Path

PASSWORD_ROUNDS = 600_000
SESSION_SECONDS = 12 * 60 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
_DUMMY_HASH = hashlib.pbkdf2_hmac(
    "sha256", b"invalid-password", b"invalid-user-salt", PASSWORD_ROUNDS
)


class AccountError(ValueError):
    pass


class OperatorAccounts:
    def __init__(self, path: Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operator_users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    display_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin', 'operator')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operator_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES operator_users(id),
                    csrf_token TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS operator_sessions_expiry
                    ON operator_sessions(expires_at);
                CREATE TABLE IF NOT EXISTS operator_login_attempts (
                    username TEXT PRIMARY KEY,
                    failures INTEGER NOT NULL,
                    locked_until REAL NOT NULL
                );
            """)

    @staticmethod
    def _normalize_username(username):
        return username.strip().lower()

    @staticmethod
    def validate_password(password):
        if not 12 <= len(password) <= 256:
            raise AccountError("La contraseña debe tener entre 12 y 256 caracteres.")

    @staticmethod
    def validate_details(username, display_name):
        normalized = OperatorAccounts._normalize_username(username)
        name = display_name.strip()
        if not USERNAME_PATTERN.fullmatch(normalized):
            raise AccountError(
                "El usuario debe tener entre 3 y 32 caracteres: letras, números, punto, guion o guion bajo."
            )
        if not name or len(name) > 80:
            raise AccountError("El nombre debe tener entre 1 y 80 caracteres.")
        return normalized, name

    @staticmethod
    def _hash_password(password, salt=None):
        salt = salt or secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, PASSWORD_ROUNDS
        )
        return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"

    @staticmethod
    def _verify_password(password, encoded):
        try:
            algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
            if algorithm != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
            )
            return hmac.compare_digest(actual.hex(), digest_hex)
        except (ValueError, TypeError):
            return False

    def has_users(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT 1 FROM operator_users LIMIT 1").fetchone() is not None

    def create_initial_admin(self, username, display_name, password):
        normalized, name = self.validate_details(username, display_name)
        self.validate_password(password)
        encoded = self._hash_password(password)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM operator_users LIMIT 1").fetchone():
                raise AccountError("La cuenta inicial ya fue creada. Iniciá sesión.")
            cursor = db.execute(
                """INSERT INTO operator_users(username,display_name,password_hash,role,created_at)
                   VALUES(?,?,?,'admin',?)""",
                (normalized, name, encoded, self.clock()),
            )
            return cursor.lastrowid

    def create_operator(self, username, display_name, password):
        normalized, name = self.validate_details(username, display_name)
        self.validate_password(password)
        encoded = self._hash_password(password)
        try:
            with sqlite3.connect(self.path, timeout=10) as db:
                cursor = db.execute(
                    """INSERT INTO operator_users(username,display_name,password_hash,role,created_at)
                       VALUES(?,?,?,'operator',?)""",
                    (normalized, name, encoded, self.clock()),
                )
                return cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise AccountError("Ese nombre de usuario ya existe.") from error

    def authenticate(self, username, password):
        normalized = self._normalize_username(username)
        with sqlite3.connect(self.path, timeout=10) as db:
            row = db.execute(
                "SELECT * FROM operator_users WHERE username=? COLLATE NOCASE",
                (normalized,),
            ).fetchone()
            attempt = db.execute(
                "SELECT failures,locked_until FROM operator_login_attempts WHERE username=?",
                (normalized,),
            ).fetchone()
            locked = bool(attempt and attempt[1] > self.clock())
        password_too_long = len(password) > 256
        password_to_check = password[:256]
        encoded = row[3] if row else None
        if locked:
            self._verify_password(password_to_check, encoded or self._dummy_encoded())
            return None
        valid = self._verify_password(password_to_check, encoded or self._dummy_encoded())
        valid = valid and not password_too_long
        if not row or not valid or not row[5]:
            with sqlite3.connect(self.path, timeout=10) as db:
                failures = (attempt[0] if attempt and attempt[1] == 0 else 0) + 1
                locked_until = self.clock() + 15 * 60 if failures >= 5 else 0
                db.execute(
                    """INSERT INTO operator_login_attempts(username,failures,locked_until)
                       VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET
                       failures=excluded.failures,locked_until=excluded.locked_until""",
                    (normalized[:32], failures, locked_until),
                )
            return None
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("DELETE FROM operator_login_attempts WHERE username=?", (normalized,))
        return {"id": row[0], "username": row[1], "display_name": row[2], "role": row[4]}

    @staticmethod
    def _dummy_encoded():
        return f"pbkdf2_sha256${PASSWORD_ROUNDS}${bytes(16).hex()}${_DUMMY_HASH.hex()}"

    def create_session(self, user_id):
        token = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        now = self.clock()
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("DELETE FROM operator_sessions WHERE expires_at<=?", (now,))
            db.execute(
                """INSERT INTO operator_sessions(token_hash,user_id,csrf_token,created_at,expires_at)
                   VALUES(?,?,?,?,?)""",
                (hashlib.sha256(token.encode()).hexdigest(), user_id, csrf_token,
                 now, now + SESSION_SECONDS),
            )
        return token, csrf_token

    def get_session(self, token):
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with sqlite3.connect(self.path, timeout=10) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT u.id,u.username,u.display_name,u.role,s.csrf_token
                   FROM operator_sessions s JOIN operator_users u ON u.id=s.user_id
                   WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
                (token_hash, self.clock()),
            ).fetchone()
        return dict(row) if row else None

    def revoke_session(self, token):
        if token:
            with sqlite3.connect(self.path, timeout=10) as db:
                db.execute(
                    "DELETE FROM operator_sessions WHERE token_hash=?",
                    (hashlib.sha256(token.encode()).hexdigest(),),
                )

    def list_users(self):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                """SELECT id,username,display_name,role,active,created_at
                   FROM operator_users ORDER BY created_at,id"""
            )]
