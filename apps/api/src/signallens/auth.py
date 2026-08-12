"""单用户认证：密码哈希、初始账号和可撤销会话。"""

import base64
import binascii
import hashlib
import logging
import os
import secrets
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import AdminUser, AuthSession, PluginApiKey, utc_now
from .settings import get_settings

LOGGER = logging.getLogger("signallens.auth")
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    """使用带随机盐的 scrypt 派生并编码密码哈希。"""

    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=64,
    )
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """校验密码；损坏或未知格式一律视为不匹配。"""

    try:
        algorithm, n, r, p, salt_text, expected_text = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_text),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=64,
        )
        expected = base64.b64decode(expected_text)
    except (binascii.Error, ValueError, TypeError):
        return False
    return secrets.compare_digest(actual, expected)


def token_hash(token: str) -> str:
    """只在数据库中保存会话令牌的 SHA-256 摘要。"""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_plugin_key(session: Session) -> tuple[str, PluginApiKey]:
    """生成新的插件 Key；单用户阶段始终替换此前的 Key。"""

    raw_key = f"sk-sl-{secrets.token_urlsafe(32)}"
    record = session.get(PluginApiKey, "default")
    if record is None:
        record = PluginApiKey(id="default", key_hash="", key_prefix="")
        session.add(record)
    record.key_hash = token_hash(raw_key)
    record.key_prefix = raw_key[:14]
    record.created_at = utc_now()
    record.last_used_at = None
    return raw_key, record


def load_plugin_key(session: Session, raw_key: str) -> PluginApiKey | None:
    """校验插件 Key，并记录最近一次成功提交时间。"""

    if not raw_key.startswith("sk-sl-"):
        return None
    record = session.scalar(
        select(PluginApiKey).where(PluginApiKey.key_hash == token_hash(raw_key))
    )
    if record is not None:
        record.last_used_at = utc_now()
    return record


def create_session(session: Session, user: AdminUser) -> tuple[str, AuthSession]:
    """签发随机 Bearer 令牌并保存可撤销的服务端会话。"""

    raw_token = secrets.token_urlsafe(32)
    record = AuthSession(
        user_id=user.id,
        token_hash=token_hash(raw_token),
        expires_at=utc_now() + timedelta(days=get_settings().session_days),
    )
    session.add(record)
    return raw_token, record


def load_session(session: Session, raw_token: str) -> tuple[AdminUser, AuthSession] | None:
    """读取有效会话；过期记录会在本次校验中删除。"""

    record = session.scalar(
        select(AuthSession).where(AuthSession.token_hash == token_hash(raw_token))
    )
    if record is None:
        return None
    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=utc_now().tzinfo)
    if expires_at <= utc_now():
        session.delete(record)
        session.commit()
        return None
    user = session.get(AdminUser, record.user_id)
    return (user, record) if user else None


def revoke_user_sessions(session: Session, user_id: str) -> None:
    """撤销指定账号的全部 Web 会话，不影响独立插件 Key。"""

    session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))


def ensure_initial_admin() -> None:
    """首次启动创建 admin，并把一次性随机密码写入受忽略的数据文件。"""

    initial_password: str | None = None
    with SessionLocal.begin() as session:
        user = session.scalar(select(AdminUser).where(AdminUser.username == "admin"))
        if user is None:
            initial_password = secrets.token_urlsafe(18)
            # 先确保凭据能安全落盘，再提交账户；避免文件写入失败后无法登录。
            _write_bootstrap_password(initial_password)
            session.add(
                AdminUser(
                    username="admin",
                    password_hash=hash_password(initial_password),
                    must_change_password=True,
                )
            )


def remove_bootstrap_password_file() -> None:
    """首次改密后删除已失效的初始密码文件。"""

    path = Path(get_settings().bootstrap_password_file)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        LOGGER.warning("初始密码已失效，但无法删除文件：%s", path)


def _write_bootstrap_password(password: str) -> None:
    """原子写入初始凭据，并在支持的平台限制为当前用户可读写。"""

    path = Path(get_settings().bootstrap_password_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        "SignalLens 初始管理员凭据\n"
        "username=admin\n"
        f"password={password}\n"
        "首次登录后请立即修改密码。\n",
        encoding="utf-8",
    )
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        LOGGER.warning("当前平台无法限制初始密码文件权限：%s", temporary)
    temporary.replace(path)
    LOGGER.warning("已创建初始 admin，密码文件：%s", path.resolve())
