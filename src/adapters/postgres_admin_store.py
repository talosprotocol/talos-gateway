import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from typing import List, Optional, Any, Dict

logger = logging.getLogger(__name__)

class PostgresAdminStore:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or os.getenv("TALOS_DATABASE_URL")
        if not self.dsn:
            db_user = os.getenv("DB_USER")
            db_pass = os.getenv("DB_PASSWORD")
            db_host = os.getenv("DB_HOST", "localhost")
            db_name = os.getenv("DB_NAME")
            self.dsn = f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
        self._ensure_connection()

    def _ensure_connection(self):
        try:
            self.conn = psycopg2.connect(self.dsn)
            self.conn.autocommit = True
        except Exception as e:
            logger.error(f"Failed to connect to Postgres (Admin Store): {e}")
            self.conn = None

    def _get_cursor(self):
        if self.conn is None or self.conn.closed:
            self._ensure_connection()
        return self.conn.cursor(cursor_factory=RealDictCursor)

    # --- RBAC Roles ---
    def list_roles(self) -> List[Dict[str, Any]]:
        with self._get_cursor() as cur:
            cur.execute("SELECT * FROM rbac_roles ORDER BY role_id ASC")
            return [dict(row) for row in cur.fetchall()]

    def upsert_role(self, role_id: str, name: str, description: str, permissions: List[str], built_in: bool = False) -> Dict[str, Any]:
        with self._get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO rbac_roles (role_id, name, description, permissions, built_in, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (role_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    permissions = EXCLUDED.permissions,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
                """,
                (role_id, name, description, Json(permissions), built_in)
            )
            return dict(cur.fetchone())

    def delete_role(self, role_id: str) -> bool:
        with self._get_cursor() as cur:
            cur.execute("DELETE FROM rbac_roles WHERE role_id = %s AND built_in = FALSE", (role_id,))
            return cur.rowcount > 0

    # --- RBAC Bindings ---
    def list_bindings(self) -> List[Dict[str, Any]]:
        with self._get_cursor() as cur:
            cur.execute("SELECT * FROM rbac_bindings ORDER BY principal_id ASC")
            return [dict(row) for row in cur.fetchall()]

    def upsert_binding(self, principal_id: str, bindings: List[Dict[str, str]]) -> Dict[str, Any]:
        with self._get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO rbac_bindings (principal_id, bindings, updated_at)
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (principal_id) DO UPDATE SET
                    bindings = EXCLUDED.bindings,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING *
                """,
                (principal_id, Json(bindings))
            )
            return dict(cur.fetchone())

    def delete_binding(self, principal_id: str) -> bool:
        with self._get_cursor() as cur:
            cur.execute("DELETE FROM rbac_bindings WHERE principal_id = %s", (principal_id,))
            return cur.rowcount > 0

    # --- Custom Secrets ---
    def list_secrets(self) -> List[Dict[str, Any]]:
        with self._get_cursor() as cur:
            cur.execute("SELECT name, kek_id, created_at, updated_at FROM custom_secrets ORDER BY name ASC")
            return [dict(row) for row in cur.fetchall()]

    def get_secret(self, name: str) -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cur:
            cur.execute("SELECT * FROM custom_secrets WHERE name = %s", (name,))
            row = cur.fetchone()
            return dict(row) if row else None

    def upsert_secret(self, name: str, kek_id: str, ciphertext: str, iv: str, tag: str) -> Dict[str, Any]:
        with self._get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO custom_secrets (name, kek_id, ciphertext, iv, tag, updated_at)
                VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (name) DO UPDATE SET
                    kek_id = EXCLUDED.kek_id,
                    ciphertext = EXCLUDED.ciphertext,
                    iv = EXCLUDED.iv,
                    tag = EXCLUDED.tag,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING name, kek_id, created_at, updated_at
                """,
                (name, kek_id, ciphertext, iv, tag)
            )
            return dict(cur.fetchone())

    def delete_secret(self, name: str) -> bool:
        with self._get_cursor() as cur:
            cur.execute("DELETE FROM custom_secrets WHERE name = %s", (name,))
            return cur.rowcount > 0

    # --- Platform Config ---
    def get_config(self, key: str = 'current') -> Optional[Dict[str, Any]]:
        with self._get_cursor() as cur:
            cur.execute("SELECT data, version FROM platform_config WHERE config_key = %s", (key,))
            row = cur.fetchone()
            return dict(row) if row else None

    def save_config(self, data: Dict[str, Any], key: str = 'current') -> None:
        with self._get_cursor() as cur:
            cur.execute(
                """
                INSERT INTO platform_config (config_key, data, version, updated_at)
                VALUES (%s, %s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (config_key) DO UPDATE SET
                    data = EXCLUDED.data,
                    version = platform_config.version + 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (key, Json(data))
            )

    def set_metadata(self, key: str, value: Any) -> None:
        """Utility for persistent admin metadata (e.g. rotation timestamps)"""
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO platform_config (config_key, data)
                    VALUES (%s, %s)
                    ON CONFLICT (config_key) DO UPDATE SET data = EXCLUDED.data, updated_at = CURRENT_TIMESTAMP
                    """,
                    (f"metadata:{key}", Json(value))
                )
        except Exception as e:
            logger.error(f"Failed to set metadata {key}: {e}")

    def get_metadata(self, key: str, default: Any = None) -> Any:
        try:
            with self._get_cursor() as cur:
                cur.execute("SELECT data FROM platform_config WHERE config_key = %s", (f"metadata:{key}",))
                row = cur.fetchone()
                return row['data'] if row else default
        except Exception as e:
            logger.error(f"Failed to get metadata {key}: {e}")
            return default
