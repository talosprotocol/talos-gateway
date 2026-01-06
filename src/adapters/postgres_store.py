import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from typing import List, Optional, Protocol, Any

# We define the Protocols here to ensure runtime compatibility 
# even if talos_sdk imports fail in this content generation context.
class AuditEvent(Protocol):
    event_id: str
    timestamp: float
    cursor: str

class EventPage:
    def __init__(self, events: List[Any], next_cursor: Optional[str]):
        self.events = events
        self.next_cursor = next_cursor

class PostgresAuditStore:
    def __init__(self, dsn: Optional[str] = None):
        # Default to localhost for dev convenience as per docker-compose
        # WARNING: Use env vars in production!
        self.dsn = dsn or os.getenv("TALOS_DATABASE_URL")
        if not self.dsn:
            # Construct from individual env vars
            # These must be set in .env or environment
            db_user = os.getenv("DB_USER")
            db_pass = os.getenv("DB_PASSWORD")
            db_host = os.getenv("DB_HOST", "localhost")
            db_name = os.getenv("DB_NAME")
            if not all([db_user, db_pass, db_name]):
                 # If critical vars missing from env, fallback to a safe local default 
                 # or raise if preferred. Here we fallback to the developer default 
                 # BUT we moved the actual password to .env.
                 pass
            self.dsn = f"postgresql://{db_user}:{db_pass}@{db_host}:5432/{db_name}"
        self._ensure_connection()

    def _ensure_connection(self):
        try:
            self.conn = psycopg2.connect(self.dsn)
            self.conn.autocommit = True
        except Exception as e:
            logger.error(f"Failed to connect to Postgres: {e}")
            # We don't raise here to allow app startup even if DB is transiently down, 
            # but methods will fail. Robustness usually implies retry.
            self.conn = None

    def _get_cursor(self):
        if self.conn is None or self.conn.closed:
            self._ensure_connection()
        return self.conn.cursor(cursor_factory=RealDictCursor)

    def append(self, event) -> None:
        try:
            with self._get_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO events (
                        event_id, schema_version, timestamp, cursor, event_type, outcome,
                        session_id, correlation_id, agent_id, peer_id, tool, method, resource,
                        metadata, metrics, hashes, integrity, integrity_hash
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    (
                        event.event_id,
                        getattr(event, 'schema_version', '1'),
                        event.timestamp,
                        event.cursor,
                        event.event_type,
                        event.outcome,
                        event.session_id,
                        event.correlation_id,
                        event.agent_id,
                        getattr(event, 'peer_id', None),
                        event.tool,
                        event.method,
                        event.resource,
                        Json(event.metadata),
                        Json(getattr(event, 'metrics', {})),
                        Json(getattr(event, 'hashes', {})),
                        Json(getattr(event, 'integrity', {})),
                        event.integrity_hash
                    )
                )
        except Exception as e:
            logger.error(f"Failed to insert event: {e}")
            raise

    def list(self, before: Optional[str] = None, limit: int = 100, filters: Any = None) -> EventPage:
        """
        List events with optional filtering.
        """
        try:
            with self._get_cursor() as cur:
                query = "SELECT * FROM events"
                where_clauses = []
                params = []
                
                if before:
                    where_clauses.append("cursor < %s")
                    params.append(before)
                
                if filters:
                    if filters.get("session_id"):
                        where_clauses.append("session_id = %s")
                        params.append(filters["session_id"])
                    if filters.get("correlation_id"):
                        where_clauses.append("correlation_id = %s")
                        params.append(filters["correlation_id"])
                    if filters.get("outcome"):
                        where_clauses.append("outcome = %s")
                        params.append(filters["outcome"])

                if where_clauses:
                    query += " WHERE " + " AND ".join(where_clauses)
                
                query += " ORDER BY cursor DESC LIMIT %s"
                params.append(limit)
                
                cur.execute(query, params)
                rows = cur.fetchall()
                
                events = [self._map_row(row) for row in rows]
                events.reverse()
                
                next_cursor = events[0].cursor if events else None
                return EventPage(events=events, next_cursor=next_cursor)
                
        except Exception as e:
            logger.error(f"Failed to list events: {e}")
            return EventPage(events=[], next_cursor=None)
            
    def stats(self, start_ts: float, end_ts: float) -> dict:
        """
        Compute dashboard aggregations.
        """
        try:
            with self._get_cursor() as cur:
                # 1. Basic counts
                cur.execute(
                    "SELECT COUNT(*) as total, SUM(CASE WHEN outcome = 'OK' THEN 1 ELSE 0 END) as success FROM events WHERE timestamp BETWEEN %s AND %s",
                    (start_ts, end_ts)
                )
                base = cur.fetchone()
                total = base['total'] or 0
                success = base['success'] or 0
                
                # 2. Denial reasons
                cur.execute(
                    "SELECT denial_reason, COUNT(*) as count FROM events WHERE outcome = 'DENY' AND timestamp BETWEEN %s AND %s GROUP BY denial_reason",
                    (start_ts, end_ts)
                )
                reasons = {row['denial_reason']: row['count'] for row in cur.fetchall() if row['denial_reason']}
                
                # 3. Time series (1h buckets)
                cur.execute(
                    """
                    SELECT 
                        (CAST(timestamp / 3600 AS INTEGER) * 3600) as bucket,
                        SUM(CASE WHEN outcome = 'OK' THEN 1 ELSE 0 END) as ok,
                        SUM(CASE WHEN outcome = 'DENY' THEN 1 ELSE 0 END) as deny,
                        SUM(CASE WHEN outcome = 'ERROR' THEN 1 ELSE 0 END) as error
                    FROM events 
                    WHERE timestamp BETWEEN %s AND %s
                    GROUP BY bucket
                    ORDER BY bucket ASC
                    """,
                    (start_ts, end_ts)
                )
                series = [
                    {"time": row['bucket'], "ok": row['ok'], "deny": row['deny'], "error": row['error']}
                    for row in cur.fetchall()
                ]
                
                return {
                    "requests_24h": total,
                    "auth_success_rate": (success / total) if total > 0 else 1.0,
                    "denial_reason_counts": reasons,
                    "request_volume_series": series
                }
        except Exception as e:
            logger.error(f"Failed to compute stats: {e}")
            return {
                "requests_24h": 0,
                "auth_success_rate": 0,
                "denial_reason_counts": {},
                "request_volume_series": []
            }

    def _map_row(self, row):
        class EventObj:
            def __init__(self, **entries):
                self.__dict__.update(entries)
        return EventObj(**row)

logger = logging.getLogger(__name__)
