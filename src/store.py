"""
Local campaign store (SQLite).

Meta's API has no scheduling and no notion of "campaign" or "variant" for
organic posts, so this store keeps:
- scheduled_posts: the publishing queue
- post_labels: campaign / variant / hypothesis attached to a published post
- insight_snapshots: insights captured over time, used for winner scoring
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

POST_KINDS = ("image", "carousel", "reel", "story")
BUSY_TIMEOUT_S = 5.0

# Migration 1: the schema from before migrations existed. IF NOT EXISTS lets a
# pre-migration database (user_version=0) upgrade without touching its data.
SCHEMA = """
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT NOT NULL,
    payload      TEXT NOT NULL,
    publish_at   TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    attempts     INTEGER NOT NULL DEFAULT 0,
    media_id     TEXT,
    permalink    TEXT,
    error        TEXT,
    campaign     TEXT,
    variant      TEXT,
    hypothesis   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sched_due ON scheduled_posts(status, publish_at);

CREATE TABLE IF NOT EXISTS post_labels (
    media_id     TEXT PRIMARY KEY,
    campaign     TEXT,
    variant      TEXT,
    hypothesis   TEXT,
    kind         TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS insight_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id           TEXT NOT NULL,
    media_product_type TEXT,
    media_type         TEXT,
    posted_at          TEXT,
    captured_at        TEXT NOT NULL,
    age_hours          REAL,
    metrics            TEXT NOT NULL,
    caption            TEXT,
    permalink          TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_media ON insight_snapshots(media_id, captured_at);
"""

# Append-only: MIGRATIONS[i] takes the database from user_version i to i+1.
# Never edit a released entry; add a new one.
MIGRATIONS: List[str] = [SCHEMA]


class SchemaVersionError(RuntimeError):
    """The database was written by newer code than this one."""


def _statements(script: str) -> Iterator[str]:
    """Split a SQL script into statements (trigger bodies and strings stay whole)."""
    buf = ""
    for part in script.split(";"):
        buf += part + ";"
        if sqlite3.complete_statement(buf):
            if buf.strip(" \t\r\n;"):
                yield buf
            buf = ""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


_ISO_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[T ](?P<time>\d{2}:\d{2}(?::\d{2})?)"
    r"(?:[.,](?P<frac>\d+))?"
    r"(?P<tz>Z|[+-]\d{2}(?::?\d{2})?)?)?$",
    re.IGNORECASE,
)


def parse_iso(value: str) -> datetime:
    """Parse ISO 8601 as given (naive stays naive).

    Normalises what datetime.fromisoformat rejects before Python 3.11: Z,
    Meta's +0000 offsets, +HH offsets and fractions that aren't 3 or 6 digits.
    """
    v = value.strip()
    m = _ISO_RE.match(v)
    if m and m.group("time"):
        out = f"{m.group('date')}T{m.group('time')}"
        if m.group("frac"):
            out += "." + m.group("frac")[:6].ljust(6, "0")
        tz = m.group("tz")
        if tz:
            if tz.upper() == "Z":
                tz = "+00:00"
            else:
                digits = tz[1:].replace(":", "")
                tz = f"{tz[0]}{digits[:2]}:{digits[2:4] or '00'}"
            out += tz
        v = out
    return datetime.fromisoformat(v)


def parse_dt(value: str) -> datetime:
    """Parse ISO 8601 to an aware UTC datetime (naive = UTC)."""
    dt = parse_iso(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class CampaignStore:
    """SQLite store shared by several processes (API, worker, MCP server).

    Connections: a file database gets one connection per thread
    (threading.local), so no connection is ever used by two threads. Every
    sqlite3.connect(":memory:") is a new empty database, so ":memory:" keeps a
    single connection and serialises all access to it with a lock instead.
    Every connection uses WAL (file only), a busy timeout and foreign keys.
    """

    def __init__(self, path: str):
        self.path = path
        self._memory = path == ":memory:"
        self._local = threading.local()
        self._conns: List[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._lock = threading.RLock() if self._memory else nullcontext()
        if not self._memory:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._shared = self._connect() if self._memory else None
        try:
            self._migrate()
        except BaseException:
            self.close()  # don't leave the file locked behind a failed open
            raise

    def _connect(self) -> sqlite3.Connection:
        # check_same_thread=False only so close() can close other threads'
        # connections; each file connection is still used by one thread.
        conn = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_S, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        if not self._memory:
            conn.execute("PRAGMA journal_mode=WAL")
        with self._conns_lock:
            self._conns.append(conn)
        return conn

    @property
    def _conn(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # ponytail: connections of finished threads stay open until close();
            # fine for thread pools, prune dead threads if threads get unbounded.
            conn = self._local.conn = self._connect()
        return conn

    @_conn.setter
    def _conn(self, conn: sqlite3.Connection) -> None:  # tests swap in wrappers
        if self._memory:
            self._shared = conn
        else:
            self._local.conn = conn

    def _migrate(self) -> None:
        """Run every migration above PRAGMA user_version, one transaction each.

        BEGIN IMMEDIATE + re-reading the version inside the transaction means
        two processes opening the same file at once never apply one twice.
        """
        c = self._conn
        while True:
            c.execute("BEGIN IMMEDIATE")
            try:
                version = c.execute("PRAGMA user_version").fetchone()[0]
                if version > len(MIGRATIONS):
                    raise SchemaVersionError(
                        f"{self.path} has schema version {version}, this code knows up to"
                        f" {len(MIGRATIONS)}: update the code before opening it"
                    )
                if version == len(MIGRATIONS):
                    c.rollback()
                    return
                for stmt in _statements(MIGRATIONS[version]):
                    c.execute(stmt)
                c.execute(f"PRAGMA user_version={version + 1}")
                c.commit()
            except BaseException:
                c.rollback()
                raise

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """This thread's connection; commit on success, rollback on error."""
        with self._lock:
            conn = self._conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def close(self) -> None:
        """Close every connection this store opened, from any thread."""
        with self._conns_lock:
            conns, self._conns = self._conns, []
        for conn in conns:
            conn.close()

    # ------------------------------------------------------------------
    # Schedule
    # ------------------------------------------------------------------
    def schedule(
        self,
        kind: str,
        payload: Dict[str, Any],
        publish_at: datetime,
        campaign: Optional[str] = None,
        variant: Optional[str] = None,
        hypothesis: Optional[str] = None,
    ) -> Dict[str, Any]:
        if kind not in POST_KINDS:
            raise ValueError(f"kind must be one of {POST_KINDS}")
        now = to_iso(utcnow())
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO scheduled_posts (kind, payload, publish_at, campaign, variant,"
                " hypothesis, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (kind, json.dumps(payload), to_iso(publish_at), campaign, variant,
                 hypothesis, now, now),
            )
        return self.get_scheduled(cur.lastrowid)

    def get_scheduled(self, post_id: int) -> Dict[str, Any]:
        with self._tx() as c:
            row = c.execute("SELECT * FROM scheduled_posts WHERE id=?", (post_id,)).fetchone()
        if not row:
            raise KeyError(f"No scheduled post with id {post_id}")
        return _row_to_sched(row)

    def list_scheduled(
        self, status: Optional[str] = None, campaign: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        q, args = "SELECT * FROM scheduled_posts WHERE 1=1", []
        if status:
            q += " AND status=?"
            args.append(status)
        if campaign:
            q += " AND campaign=?"
            args.append(campaign)
        q += " ORDER BY publish_at LIMIT ?"
        args.append(limit)
        with self._tx() as c:
            rows = c.execute(q, args).fetchall()
        return [_row_to_sched(r) for r in rows]

    def cancel(self, post_id: int) -> Dict[str, Any]:
        post = self.get_scheduled(post_id)
        if post["status"] not in ("pending", "failed"):
            raise ValueError(f"Post {post_id} is {post['status']}; only pending/failed can be cancelled")
        with self._tx() as c:
            cur = c.execute(
                "UPDATE scheduled_posts SET status='cancelled', updated_at=?"
                " WHERE id=? AND status IN ('pending','failed')",
                (to_iso(utcnow()), post_id),
            )
        if cur.rowcount != 1:  # claimed by the scheduler in the meantime
            raise ValueError(f"Post {post_id} changed state; it can no longer be cancelled")
        return self.get_scheduled(post_id)

    def reschedule(self, post_id: int, publish_at: datetime) -> Dict[str, Any]:
        post = self.get_scheduled(post_id)
        if post["status"] not in ("pending", "failed", "cancelled"):
            raise ValueError(f"Post {post_id} is {post['status']} and can't be rescheduled")
        with self._tx() as c:
            cur = c.execute(
                "UPDATE scheduled_posts SET publish_at=?, status='pending', error=NULL,"
                " attempts=0, updated_at=? WHERE id=?"
                " AND status IN ('pending','failed','cancelled')",
                (to_iso(publish_at), to_iso(utcnow()), post_id),
            )
        if cur.rowcount != 1:
            raise ValueError(f"Post {post_id} changed state; it can no longer be rescheduled")
        return self.get_scheduled(post_id)

    def claim_due(self, now: Optional[datetime] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Atomically move due 'pending' posts to 'publishing' and return them."""
        now_iso = to_iso(now or utcnow())
        with self._tx() as c:
            rows = c.execute(
                "SELECT id FROM scheduled_posts WHERE status='pending' AND publish_at<=?"
                " ORDER BY publish_at LIMIT ?",
                (now_iso, limit),
            ).fetchall()
            ids = []
            for r in rows:
                cur = c.execute(
                    "UPDATE scheduled_posts SET status='publishing', attempts=attempts+1,"
                    " updated_at=? WHERE id=? AND status='pending'",
                    (now_iso, r["id"]),
                )
                # Another process (daemon vs MCP server) may have claimed it
                # between the SELECT and this UPDATE: only keep what we won.
                if cur.rowcount == 1:
                    ids.append(r["id"])
        return [self.get_scheduled(pid) for pid in ids]

    def mark_published(self, post_id: int, media_id: str, permalink: Optional[str]) -> None:
        post = self.get_scheduled(post_id)
        with self._tx() as c:
            c.execute(
                "UPDATE scheduled_posts SET status='published', media_id=?, permalink=?,"
                " error=NULL, updated_at=? WHERE id=?",
                (media_id, permalink, to_iso(utcnow()), post_id),
            )
        self.label_post(
            media_id, post["campaign"], post["variant"], post["hypothesis"], post["kind"]
        )

    def mark_failed(
        self,
        post_id: int,
        error: str,
        retry_in_minutes: Optional[int],
        count_attempt: bool = True,
    ) -> None:
        """Failed attempt: go back to pending with a delay, or stay failed.

        count_attempt=False gives the attempt back (rate limit / quota: the
        post itself is fine, it just has to wait).
        """
        now = utcnow()
        refund = 0 if count_attempt else 1
        with self._tx() as c:
            if retry_in_minutes is not None:
                c.execute(
                    "UPDATE scheduled_posts SET status='pending', error=?, publish_at=?,"
                    " attempts=MAX(attempts-?, 0), updated_at=? WHERE id=?",
                    (error, to_iso(now + timedelta(minutes=retry_in_minutes)),
                     refund, to_iso(now), post_id),
                )
            else:
                c.execute(
                    "UPDATE scheduled_posts SET status='failed', error=?, updated_at=?"
                    " WHERE id=?",
                    (error, to_iso(now), post_id),
                )

    def touch(self, post_id: int) -> None:
        """Heartbeat for a post being published (see recover_stuck)."""
        with self._tx() as c:
            c.execute(
                "UPDATE scheduled_posts SET updated_at=? WHERE id=? AND status='publishing'",
                (to_iso(utcnow()), post_id),
            )

    def recover_stuck(self, older_than_minutes: int = 30) -> int:
        """Posts left in 'publishing' by a crashed process are marked failed.

        A live publish refreshes updated_at every minute (campaign heartbeat),
        so only abandoned claims get here. If the crash happened after Meta
        published, retrying could post twice, so they need a human look.
        """
        cutoff = to_iso(utcnow() - timedelta(minutes=older_than_minutes))
        with self._tx() as c:
            cur = c.execute(
                "UPDATE scheduled_posts SET status='failed', error='Interrupted while"
                " publishing - check Instagram before retrying', updated_at=?"
                " WHERE status='publishing' AND updated_at<?",
                (to_iso(utcnow()), cutoff),
            )
        return cur.rowcount

    # ------------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------------
    def label_post(
        self,
        media_id: str,
        campaign: Optional[str] = None,
        variant: Optional[str] = None,
        hypothesis: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._tx() as c:
            c.execute(
                "INSERT INTO post_labels (media_id, campaign, variant, hypothesis, kind,"
                " created_at) VALUES (?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE SET"
                " campaign=COALESCE(excluded.campaign, campaign),"
                " variant=COALESCE(excluded.variant, variant),"
                " hypothesis=COALESCE(excluded.hypothesis, hypothesis),"
                " kind=COALESCE(excluded.kind, kind)",
                (media_id, campaign, variant, hypothesis, kind, to_iso(utcnow())),
            )
        return self.get_label(media_id) or {}

    def get_label(self, media_id: str) -> Optional[Dict[str, Any]]:
        with self._tx() as c:
            row = c.execute("SELECT * FROM post_labels WHERE media_id=?", (media_id,)).fetchone()
        return dict(row) if row else None

    def labels(self, campaign: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        q, args = "SELECT * FROM post_labels", []
        if campaign:
            q += " WHERE campaign=?"
            args.append(campaign)
        with self._tx() as c:
            rows = c.execute(q, args).fetchall()
        return {r["media_id"]: dict(r) for r in rows}

    # ------------------------------------------------------------------
    # Insight snapshots
    # ------------------------------------------------------------------
    def add_snapshot(
        self,
        media_id: str,
        metrics: Dict[str, Any],
        media_product_type: Optional[str],
        media_type: Optional[str],
        posted_at: Optional[str],
        caption: Optional[str] = None,
        permalink: Optional[str] = None,
        captured_at: Optional[datetime] = None,
    ) -> None:
        captured = captured_at or utcnow()
        age = None
        posted_iso = None
        if posted_at:
            posted = parse_dt(posted_at)
            posted_iso = to_iso(posted)
            age = round((captured - posted).total_seconds() / 3600, 2)
        with self._tx() as c:
            c.execute(
                "INSERT INTO insight_snapshots (media_id, media_product_type, media_type,"
                " posted_at, captured_at, age_hours, metrics, caption, permalink)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (media_id, media_product_type, media_type, posted_iso, to_iso(captured),
                 age, json.dumps(metrics), (caption or "")[:500], permalink),
            )

    def snapshot_history(self) -> Dict[str, List[Dict[str, Any]]]:
        """All snapshots grouped by media_id, oldest first."""
        out: Dict[str, List[Dict[str, Any]]] = {}
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM insight_snapshots ORDER BY media_id, captured_at"
            ).fetchall()
        for r in rows:
            d = dict(r)
            d["metrics"] = json.loads(d["metrics"])
            out.setdefault(d["media_id"], []).append(d)
        return out

    def latest_snapshots(self) -> List[Dict[str, Any]]:
        """Most recent snapshot per media, newest posts first."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT s.* FROM insight_snapshots s JOIN (SELECT media_id, MAX(id) AS mid"
                " FROM insight_snapshots GROUP BY media_id) m ON s.id = m.mid"
                " ORDER BY s.posted_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metrics"] = json.loads(d["metrics"])
            out.append(d)
        return out


def _row_to_sched(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d
