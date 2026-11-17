"""
Local campaign store (SQLite).

Meta's API has no scheduling and no notion of "campaign" or "variant" for
organic posts, so this store keeps:
- scheduled_posts: the publishing queue
- post_labels: campaign / variant / hypothesis attached to a published post
- insight_snapshots: insights captured over time, used for winner scoring
- sources / ideas / assets: the studio's clips, content ideas and rendered
  candidates (GOAL.md §4.3); asset status moves live in src/studio/assets.py
- feedback / learnings / daily_reports / agent_runs: the learning loop's memory
  (GOAL.md §3.5)
- audience_hours: followers online per UTC hour, weights for the slot planner
- worker_state: the worker's key/value state (heartbeat, pause switch, last result)
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

from .taxonomy import validate, validate_many

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

# Migration 2: studio tables (GOAL.md §4.3). JSON columns hold TEXT JSON.
STUDIO_SCHEMA = """
CREATE TABLE sources (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    provider           TEXT NOT NULL,
    url                TEXT,
    author             TEXT,
    stats              TEXT NOT NULL DEFAULT '{}',
    rights_basis       TEXT NOT NULL DEFAULT 'unknown' CHECK (rights_basis IN
        ('own','licensed','public_domain','cc','permission','commentary','unknown')),
    rights_note        TEXT,
    audio_rights       TEXT,
    local_path         TEXT,
    downloaded_at      TEXT,
    downloader_version TEXT,
    created_at         TEXT NOT NULL
);
CREATE INDEX idx_sources_rights ON sources(rights_basis);

CREATE TABLE ideas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    track       TEXT NOT NULL,
    pillar      TEXT,
    hook        TEXT,
    hook_type   TEXT,
    script      TEXT,
    source_id   INTEGER REFERENCES sources(id),
    citations   TEXT NOT NULL DEFAULT '[]',
    hypothesis  TEXT,
    strategy    TEXT CHECK (strategy IN ('explore','exploit')),
    experiment  TEXT,
    batch_date  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_ideas_batch ON ideas(batch_date, track);

CREATE TABLE assets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    idea_id           INTEGER NOT NULL REFERENCES ideas(id),
    parent_asset_id   INTEGER REFERENCES assets(id),
    file_path         TEXT,
    preview_path      TEXT,
    thumbnail_path    TEXT,
    caption           TEXT,
    audio_name        TEXT,
    recipe            TEXT NOT NULL DEFAULT '{}',
    duration          REAL,
    batch_date        TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'rendering' CHECK (status IN
        ('rendering','ready','failed','needs_reaction','revision_requested','approved',
         'scheduled','publish_check','published','archived')),
    verdict           TEXT NOT NULL DEFAULT 'none' CHECK (verdict IN ('none','liked','disliked')),
    qc                TEXT,
    self_score        INTEGER CHECK (self_score IS NULL OR self_score BETWEEN 1 AND 10),
    self_score_reason TEXT,
    best_before       TEXT,
    approved_at       TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX idx_assets_batch_status ON assets(batch_date, status);
CREATE INDEX idx_assets_idea ON assets(idea_id);
"""

# Migration 3: learning-loop tables (GOAL.md §3.2, §3.5, §4.3).
#   learnings.kind:       do | dont | hypothesis
#   learnings.confidence: low | medium | high | owner (an explicit owner rule)
#   learnings.origin:     taste (owner feedback) | audience (analytics) | ads
#   learnings.status:     active | retired | contradicted
#   agent_runs.status:    running | succeeded | failed | cancelled
LEARNING_SCHEMA = """
CREATE TABLE feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id      INTEGER NOT NULL REFERENCES assets(id),
    text          TEXT,
    reason_codes  TEXT NOT NULL DEFAULT '[]',
    video_time_s  REAL CHECK (video_time_s IS NULL OR video_time_s >= 0),
    wants_changes INTEGER NOT NULL DEFAULT 0 CHECK (wants_changes IN (0,1)),
    digested_at   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_feedback_asset ON feedback(asset_id);
CREATE INDEX idx_feedback_digested ON feedback(digested_at);

CREATE TABLE learnings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    statement   TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('do','dont','hypothesis')),
    scope       TEXT NOT NULL DEFAULT '{}',
    evidence    TEXT NOT NULL DEFAULT '[]',
    confidence  TEXT NOT NULL DEFAULT 'low' CHECK (confidence IN
        ('low','medium','high','owner')),
    origin      TEXT NOT NULL CHECK (origin IN ('taste','audience','ads')),
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN
        ('active','retired','contradicted')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_learnings_status ON learnings(status);

CREATE TABLE daily_reports (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL UNIQUE
        CHECK (report_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    summary     TEXT,
    facts       TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL
);

CREATE TABLE agent_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    playbook    TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL DEFAULT 'running' CHECK (status IN
        ('running','succeeded','failed','cancelled')),
    summary     TEXT,
    usage       TEXT,
    log_path    TEXT
);
CREATE INDEX idx_agent_runs_playbook ON agent_runs(playbook, started_at);
"""

# Migration 4: followers online per UTC hour, one row per capture date and hour (022).
AUDIENCE_SCHEMA = """
CREATE TABLE audience_hours (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    date             TEXT NOT NULL
        CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    hour_utc         INTEGER NOT NULL CHECK (hour_utc BETWEEN 0 AND 23),
    followers_online INTEGER NOT NULL CHECK (followers_online >= 0),
    captured_at      TEXT NOT NULL,
    UNIQUE (date, hour_utc)
);
"""

# Migration 5: queue rows and post labels point at the studio asset they publish (019).
ASSET_LINK_SCHEMA = """
ALTER TABLE scheduled_posts ADD COLUMN asset_id INTEGER REFERENCES assets(id);
ALTER TABLE post_labels ADD COLUMN asset_id INTEGER REFERENCES assets(id);
CREATE INDEX idx_sched_asset ON scheduled_posts(asset_id);
"""

# Migration 6: the publishing worker's small state, JSON values by key (025).
WORKER_STATE_SCHEMA = """
CREATE TABLE worker_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Append-only: MIGRATIONS[i] takes the database from user_version i to i+1.
# Never edit a released entry; add a new one.
MIGRATIONS: List[str] = [SCHEMA, STUDIO_SCHEMA, LEARNING_SCHEMA, AUDIENCE_SCHEMA,
                         ASSET_LINK_SCHEMA, WORKER_STATE_SCHEMA]

SOURCE_FIELDS = ("provider", "url", "author", "stats", "rights_basis", "rights_note",
                 "audio_rights", "local_path", "downloaded_at", "downloader_version")
IDEA_FIELDS = ("track", "pillar", "hook", "hook_type", "script", "source_id", "citations",
               "hypothesis", "strategy", "experiment", "batch_date")
ASSET_FIELDS = ("idea_id", "parent_asset_id", "file_path", "preview_path", "thumbnail_path",
                "caption", "audio_name", "recipe", "duration", "batch_date", "status",
                "verdict", "qc", "self_score", "self_score_reason", "best_before")
FEEDBACK_FIELDS = ("text", "reason_codes", "video_time_s", "wants_changes")
LEARNING_FIELDS = ("statement", "kind", "scope", "evidence", "confidence", "origin", "status")
JSON_FIELDS = ("stats", "citations", "recipe", "qc", "reason_codes", "scope", "evidence",
               "facts", "usage")
# Timestamp columns _insert() fills with "now"; tables not listed get created_at.
_INSERT_STAMPS = {
    "assets": ("created_at", "updated_at"),
    "feedback": ("created_at", "updated_at"),
    "learnings": ("created_at", "updated_at"),
    "agent_runs": ("started_at",),
}
AGENT_RUN_END_STATUSES = ("succeeded", "failed", "cancelled")
# New assets start here; every later status move goes through studio.assets.transition().
ASSET_INITIAL_STATUSES = ("rendering", "needs_reaction")
_UNCHANGED = object()


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
        asset_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Queue a post. Studio assets come through studio.publish.queue_asset() only."""
        if kind not in POST_KINDS:
            raise ValueError(f"kind must be one of {POST_KINDS}")
        now = to_iso(utcnow())
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO scheduled_posts (kind, payload, publish_at, campaign, variant,"
                " hypothesis, asset_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (kind, json.dumps(payload), to_iso(publish_at), campaign, variant,
                 hypothesis, asset_id, now, now),
            )
        return self.get_scheduled(cur.lastrowid)

    def delete_pending(self, post_id: int) -> bool:
        """Remove a pending row nobody has claimed (queue_asset lost a race)."""
        with self._tx() as c:
            cur = c.execute("DELETE FROM scheduled_posts WHERE id=? AND status='pending'",
                            (post_id,))
        return cur.rowcount == 1

    def cancel_claimed(self, post_id: int, error: str) -> None:
        """The worker drops a row it claimed but must not publish."""
        with self._tx() as c:
            c.execute(
                "UPDATE scheduled_posts SET status='cancelled', error=?, updated_at=?"
                " WHERE id=? AND status='publishing'",
                (error, to_iso(utcnow()), post_id),
            )

    def unsettled_assets(self) -> List[int]:
        """Assets still `scheduled` whose latest row failed: the publish may have reached
        Instagram (crash recovered by recover_stuck), so they need a check."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT DISTINCT p.asset_id FROM scheduled_posts p"
                " JOIN assets a ON a.id = p.asset_id"
                " WHERE p.status='failed' AND a.status='scheduled'"
                " AND p.id = (SELECT MAX(id) FROM scheduled_posts WHERE asset_id = p.asset_id)"
            ).fetchall()
        return [r[0] for r in rows]

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
        if post["asset_id"] is not None and post["status"] != "pending":
            raise ValueError(f"Post {post_id} is a studio asset's: queue the asset again instead")
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

    def move_pending(self, post_id: int, publish_at: datetime, note: str) -> bool:
        """The worker moves a pending row to a new slot (late or too close; attempts kept)."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE scheduled_posts SET publish_at=?, error=?, updated_at=?"
                " WHERE id=? AND status='pending'",
                (to_iso(publish_at), note, to_iso(utcnow()), post_id),
            )
        return cur.rowcount == 1

    def queue_times(self, since: datetime) -> List[Dict[str, Any]]:
        """id/status/publish_at/updated_at of pending and in-flight rows, and of rows
        published since `since` (their updated_at is the publish time)."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT id, status, publish_at, updated_at FROM scheduled_posts"
                " WHERE status IN ('pending','publishing')"
                " OR (status='published' AND updated_at>=?)",
                (to_iso(since),),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_published(self, post_id: int, media_id: str, permalink: Optional[str]) -> None:
        post = self.get_scheduled(post_id)
        with self._tx() as c:
            c.execute(
                "UPDATE scheduled_posts SET status='published', media_id=?, permalink=?,"
                " error=NULL, updated_at=? WHERE id=?",
                (media_id, permalink, to_iso(utcnow()), post_id),
            )
        self.label_post(
            media_id, post["campaign"], post["variant"], post["hypothesis"], post["kind"],
            asset_id=post["asset_id"],
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
        asset_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        with self._tx() as c:
            c.execute(
                "INSERT INTO post_labels (media_id, campaign, variant, hypothesis, kind,"
                " asset_id, created_at) VALUES (?,?,?,?,?,?,?) ON CONFLICT(media_id) DO UPDATE"
                " SET campaign=COALESCE(excluded.campaign, campaign),"
                " variant=COALESCE(excluded.variant, variant),"
                " hypothesis=COALESCE(excluded.hypothesis, hypothesis),"
                " kind=COALESCE(excluded.kind, kind),"
                " asset_id=COALESCE(excluded.asset_id, asset_id)",
                (media_id, campaign, variant, hypothesis, kind, asset_id, to_iso(utcnow())),
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

    # ------------------------------------------------------------------
    # Studio: sources, ideas, assets
    # ------------------------------------------------------------------
    def _insert(
        self, table: str, allowed: Sequence[str], fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        row = _encode(allowed, fields)
        now = to_iso(utcnow())
        for col in _INSERT_STAMPS.get(table, ("created_at",)):
            row[col] = now
        cols = ", ".join(row)
        with self._tx() as c:
            cur = c.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(row))})",
                list(row.values()),
            )
        return self._get(table, cur.lastrowid)

    def _get(self, table: str, row_id: int) -> Dict[str, Any]:
        with self._tx() as c:
            row = c.execute(f"SELECT * FROM {table} WHERE id=?", (row_id,)).fetchone()
        if not row:
            raise KeyError(f"No {table.removesuffix('s')} with id {row_id}")
        return _decode(row)

    def _update(
        self, table: str, allowed: Sequence[str], row_id: int, fields: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Set fields and updated_at on one row; KeyError if it doesn't exist."""
        row = _encode(allowed, fields)
        if row:
            sets = ", ".join(f"{k}=?" for k in row)
            with self._tx() as c:
                cur = c.execute(f"UPDATE {table} SET {sets}, updated_at=? WHERE id=?",
                                [*row.values(), to_iso(utcnow()), row_id])
            if cur.rowcount != 1:
                raise KeyError(f"No {table.removesuffix('s')} with id {row_id}")
        return self._get(table, row_id)

    def _select(
        self, q: str, filters: Dict[str, Any], order: str, limit: int
    ) -> List[Dict[str, Any]]:
        args = [v for v in filters.values() if v is not None]
        where = " AND ".join(f"{k}=?" for k, v in filters.items() if v is not None)
        q += (f" WHERE {where}" if where else "") + f" ORDER BY {order} LIMIT ?"
        with self._tx() as c:
            rows = c.execute(q, args + [limit]).fetchall()
        return [_decode(r) for r in rows]

    def add_source(self, provider: str, **fields: Any) -> Dict[str, Any]:
        return self._insert("sources", SOURCE_FIELDS, {"provider": provider, **fields})

    def get_source(self, source_id: int) -> Dict[str, Any]:
        return self._get("sources", source_id)

    def list_sources(
        self, rights_basis: Optional[str] = None, provider: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return self._select("SELECT * FROM sources",
                            {"rights_basis": rights_basis, "provider": provider}, "id", limit)

    def add_idea(self, track: str, **fields: Any) -> Dict[str, Any]:
        """Tags are checked against brand/taxonomy.json (TaxonomyError lists valid values)."""
        validate("tracks", track)
        for col, kind in (("pillar", "pillars"), ("hook_type", "hook_types")):
            if fields.get(col) is not None:
                validate(kind, fields[col])
        fields.setdefault("batch_date", utcnow().date())
        return self._insert("ideas", IDEA_FIELDS, {"track": track, **fields})

    def get_idea(self, idea_id: int) -> Dict[str, Any]:
        return self._get("ideas", idea_id)

    def list_ideas(
        self, track: Optional[str] = None, batch_date: Optional[Any] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return self._select("SELECT * FROM ideas",
                            {"track": track, "batch_date": _sql_value(batch_date)}, "id", limit)

    def add_asset(self, idea_id: int, **fields: Any) -> Dict[str, Any]:
        status = fields.setdefault("status", "rendering")
        if status not in ASSET_INITIAL_STATUSES:
            raise ValueError(
                f"a new asset starts as one of {ASSET_INITIAL_STATUSES}, not {status!r}"
            )
        fields.setdefault("batch_date", utcnow().date())
        return self._insert("assets", ASSET_FIELDS, {"idea_id": idea_id, **fields})

    def get_asset(self, asset_id: int) -> Dict[str, Any]:
        return self._get("assets", asset_id)

    def list_assets(
        self,
        batch_date: Optional[Any] = None,
        status: Optional[str] = None,
        verdict: Optional[str] = None,
        track: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Best first: agent self_score high to low (unscored last), then id.
        Rows carry their idea's track and strategy (explore/exploit) for the inbox."""
        return self._select(
            "SELECT a.*, i.track, i.strategy FROM assets a JOIN ideas i ON i.id = a.idea_id",
            {"a.batch_date": _sql_value(batch_date), "a.status": status,
             "a.verdict": verdict, "i.track": track},
            "a.self_score IS NULL, a.self_score DESC, a.id", limit,
        )

    def update_asset(self, asset_id: int, **fields: Any) -> Dict[str, Any]:
        """Change asset fields; status only moves through studio.assets.transition()."""
        if "status" in fields:
            raise ValueError("status changes only through studio.assets.transition()")
        return self._update("assets", ASSET_FIELDS, asset_id, fields)

    def _set_asset_status(
        self, asset_id: int, from_status: str, to_status: str, approved_at: Any = _UNCHANGED
    ) -> bool:
        """Compare-and-set for transition() only: False if the status is no longer from_status."""
        sets, args = "status=?, updated_at=?", [to_status, to_iso(utcnow())]
        if approved_at is not _UNCHANGED:
            sets += ", approved_at=?"
            args.append(approved_at)
        with self._tx() as c:
            cur = c.execute(f"UPDATE assets SET {sets} WHERE id=? AND status=?",
                            [*args, asset_id, from_status])
        return cur.rowcount == 1

    # ------------------------------------------------------------------
    # Learning loop: feedback, learnings, daily reports, agent runs
    # ------------------------------------------------------------------
    # Service rules live elsewhere: wants_changes moving the asset is
    # studio/feedback.py (013); owner-confidence learnings being off-limits to
    # the agent is the learning tools' job (054).
    def add_feedback(
        self,
        asset_id: int,
        text: Optional[str] = None,
        reason_codes: Sequence[str] = (),
        video_time_s: Optional[float] = None,
        wants_changes: bool = False,
    ) -> Dict[str, Any]:
        """Owner comment on an asset; needs text or at least one reason code."""
        reason_codes = validate_many("feedback_reasons", reason_codes)
        _check_feedback(text, reason_codes)
        return self._insert("feedback", ("asset_id",) + FEEDBACK_FIELDS, {
            "asset_id": asset_id, "text": text, "reason_codes": reason_codes,
            "video_time_s": video_time_s, "wants_changes": bool(wants_changes)})

    def get_feedback(self, feedback_id: int) -> Dict[str, Any]:
        return self._get("feedback", feedback_id)

    def list_feedback(
        self, asset_id: Optional[int] = None, undigested: Optional[bool] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Oldest first. undigested=True: not yet read by the agent; False: already read."""
        return self._select("SELECT * FROM feedback", {
            "asset_id": asset_id,
            "(digested_at IS NULL)": None if undigested is None else int(undigested),
        }, "id", limit)

    def update_feedback(self, feedback_id: int, **fields: Any) -> Dict[str, Any]:
        """Edit a comment. An edited comment counts as undigested again."""
        if "reason_codes" in fields:
            fields["reason_codes"] = validate_many("feedback_reasons", fields["reason_codes"])
        if "wants_changes" in fields:
            fields["wants_changes"] = bool(fields["wants_changes"])
        if fields:
            current = self.get_feedback(feedback_id)
            _check_feedback(fields.get("text", current["text"]),
                            fields.get("reason_codes", current["reason_codes"]))
            fields["digested_at"] = None
        return self._update("feedback", FEEDBACK_FIELDS + ("digested_at",), feedback_id, fields)

    def delete_feedback(self, feedback_id: int) -> None:
        with self._tx() as c:
            cur = c.execute("DELETE FROM feedback WHERE id=?", (feedback_id,))
        if cur.rowcount != 1:
            raise KeyError(f"No feedback with id {feedback_id}")

    def mark_feedback_digested(self, ids: Sequence[int]) -> int:
        """Stamp digested_at on the given comments not yet digested; returns how many."""
        ids = list(ids)
        if not ids:
            return 0
        with self._tx() as c:
            cur = c.execute(
                f"UPDATE feedback SET digested_at=? WHERE digested_at IS NULL"
                f" AND id IN ({','.join('?' * len(ids))})",
                [to_iso(utcnow()), *ids],
            )
        return cur.rowcount

    def add_learning(
        self, statement: str, kind: str, origin: str, **fields: Any
    ) -> Dict[str, Any]:
        """Optional: scope (dict), evidence (list), confidence, status (see LEARNING_SCHEMA)."""
        return self._insert("learnings", LEARNING_FIELDS,
                            {"statement": statement, "kind": kind, "origin": origin, **fields})

    def get_learning(self, learning_id: int) -> Dict[str, Any]:
        return self._get("learnings", learning_id)

    def list_learnings(
        self, kind: Optional[str] = None, status: Optional[str] = None,
        origin: Optional[str] = None, limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Strongest first: confidence owner > high > medium > low, then newest."""
        return self._select(
            "SELECT * FROM learnings", {"kind": kind, "status": status, "origin": origin},
            "CASE confidence WHEN 'owner' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2"
            " ELSE 3 END, id DESC", limit,
        )

    def update_learning(self, learning_id: int, **fields: Any) -> Dict[str, Any]:
        return self._update("learnings", LEARNING_FIELDS, learning_id, fields)

    def save_daily_report(
        self, report_date: date, summary: Optional[str], facts: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Insert or replace the report of one owner-local date (computed by the caller)."""
        day = _sql_value(report_date)
        with self._tx() as c:
            c.execute(
                "INSERT INTO daily_reports (report_date, summary, facts, created_at)"
                " VALUES (?,?,?,?) ON CONFLICT(report_date) DO UPDATE SET"
                " summary=excluded.summary, facts=excluded.facts",
                (day, summary, json.dumps(facts), to_iso(utcnow())),
            )
        return self.get_daily_report(day)

    def get_daily_report(self, report_date: Any) -> Optional[Dict[str, Any]]:
        rows = self._select("SELECT * FROM daily_reports",
                            {"report_date": _sql_value(report_date)}, "id", 1)
        return rows[0] if rows else None

    def latest_daily_report(self) -> Optional[Dict[str, Any]]:
        rows = self._select("SELECT * FROM daily_reports", {}, "report_date DESC", 1)
        return rows[0] if rows else None

    def start_agent_run(self, playbook: str) -> Dict[str, Any]:
        return self._insert("agent_runs", ("playbook",), {"playbook": playbook})

    def finish_agent_run(
        self,
        run_id: int,
        status: str,
        summary: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
        log_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Close a running run once; usage is whatever token/cost numbers the CLI reported."""
        if status not in AGENT_RUN_END_STATUSES:
            raise ValueError(f"a run finishes as one of {AGENT_RUN_END_STATUSES}, not {status!r}")
        with self._tx() as c:
            cur = c.execute(
                "UPDATE agent_runs SET status=?, finished_at=?, summary=?, usage=?, log_path=?"
                " WHERE id=? AND status='running'",
                (status, to_iso(utcnow()), summary,
                 None if usage is None else json.dumps(usage), log_path, run_id),
            )
        if cur.rowcount != 1:
            run = self._get("agent_runs", run_id)  # KeyError if missing
            raise ValueError(f"agent run {run_id} already finished as {run['status']}")
        return self._get("agent_runs", run_id)

    def list_agent_runs(
        self, playbook: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Newest first."""
        return self._select("SELECT * FROM agent_runs", {"playbook": playbook},
                            "started_at DESC, id DESC", limit)

    def running_agent_run(self, playbook: str) -> Optional[Dict[str, Any]]:
        """The newest run of this playbook still marked running, if any (058's lock)."""
        rows = self._select("SELECT * FROM agent_runs",
                            {"playbook": playbook, "status": "running"},
                            "started_at DESC, id DESC", 1)
        return rows[0] if rows else None

    def save_online_followers(self, day: date, hours: Mapping[int, int]) -> int:
        """Insert or replace followers online per UTC hour for one date; returns rows written."""
        rows = [(_sql_value(day), int(h), int(n), to_iso(utcnow())) for h, n in hours.items()]
        with self._tx() as c:
            c.executemany(
                "INSERT INTO audience_hours (date, hour_utc, followers_online, captured_at)"
                " VALUES (?,?,?,?) ON CONFLICT(date, hour_utc) DO UPDATE SET"
                " followers_online=excluded.followers_online, captured_at=excluded.captured_at",
                rows,
            )
        return len(rows)

    def online_followers_profile(self, days: int = 28) -> Dict[int, float]:
        """Average followers online per UTC hour over the dates of the last `days` days."""
        since = (utcnow().date() - timedelta(days=days)).isoformat()
        with self._tx() as c:
            rows = c.execute(
                "SELECT hour_utc, AVG(followers_online) FROM audience_hours"
                " WHERE date > ? GROUP BY hour_utc", (since,),
            ).fetchall()
        return {h: avg for h, avg in rows}

    # ------------------------------------------------------------------
    # Worker state
    # ------------------------------------------------------------------
    def get_state(self, key: str) -> Any:
        """A worker_state value (JSON-decoded), or None when never set."""
        with self._tx() as c:
            row = c.execute("SELECT value FROM worker_state WHERE key=?", (key,)).fetchone()
        return None if row is None else json.loads(row[0])

    def set_state(self, key: str, value: Any) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO worker_state (key, value, updated_at) VALUES (?,?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                (key, json.dumps(value), to_iso(utcnow())),
            )


def _sql_value(v: Any) -> Any:
    """datetime -> ISO UTC string, date -> YYYY-MM-DD, everything else unchanged."""
    if isinstance(v, datetime):
        return to_iso(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _check_feedback(text: Optional[str], reason_codes: Sequence[str]) -> None:
    if not (text and text.strip()) and not reason_codes:
        raise ValueError("feedback needs a text or at least one reason code")


def _encode(allowed: Sequence[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(fields) - set(allowed)
    if unknown:
        raise TypeError(f"unknown field(s): {', '.join(sorted(unknown))}")
    return {k: json.dumps(v) if k in JSON_FIELDS and v is not None else _sql_value(v)
            for k, v in fields.items()}


def _decode(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for k in JSON_FIELDS:
        if d.get(k) is not None:
            d[k] = json.loads(d[k])
    return d


def _row_to_sched(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d
