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
- account_snapshots: one account row per owner-local day (followers, reach, views)
- graph_requests: Graph API request times, the hourly budget shared by all processes
- render_jobs: the render queue (src/studio/render.py, worker render loop)
- ad_spend_ledger: ad money reserved, released and reported (src/ads/budget.py)
- ad_entities: campaigns, ad sets, creatives and ads the studio created on Meta (092)
- ad_tests / ads_audit: paid A/B tests and the append-only log of money actions (094)
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timedelta, timezone
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

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

# Migration 7: worker data jobs (026). post_labels.deleted_at: Instagram says the post is
# gone; its snapshots stay so analytics still count it (GOAL.md §3.4). graph_requests: one
# row (unix time) per Graph request, so worker, API and MCP server share one hourly cap.
DATA_JOBS_SCHEMA = """
CREATE TABLE account_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    date                TEXT NOT NULL UNIQUE
        CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    followers           INTEGER,
    reach               INTEGER,
    views               INTEGER,
    reach_followers     INTEGER,
    reach_non_followers INTEGER,
    raw                 TEXT NOT NULL,
    captured_at         TEXT NOT NULL
);
ALTER TABLE post_labels ADD COLUMN deleted_at TEXT;
CREATE TABLE graph_requests (at REAL NOT NULL);
CREATE INDEX idx_graph_requests_at ON graph_requests(at);
"""

# Migration 8: the render queue (034). One job per idempotency key (default: asset id +
# recipe hash); heartbeat_at lets a restarted worker re-queue jobs a crash left running.
# assets.poster_path: the poster frame next to the thumbnail.
RENDER_SCHEMA = """
CREATE TABLE render_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id        INTEGER NOT NULL REFERENCES assets(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    state           TEXT NOT NULL DEFAULT 'queued'
        CHECK (state IN ('queued','running','done','failed')),
    progress        REAL NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 1),
    attempts        INTEGER NOT NULL DEFAULT 0,
    failure         TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    render_ms       INTEGER,
    heartbeat_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX idx_render_jobs_state ON render_jobs(state, id);
ALTER TABLE assets ADD COLUMN poster_path TEXT;
"""

# Migration 9: trend research (051). watchlist values are normalised (lowercase, no #/@).
# sources.role: clip (material for a video) | reference (research only, never published);
# external_id: the provider's post id, so a second research run updates stats in place.
# hashtag_searches: last lookup per tag, for Meta's 30 unique hashtags per rolling 7 days.
RESEARCH_SCHEMA = """
CREATE TABLE watchlist (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL CHECK (kind IN ('hashtag','account')),
    value      TEXT NOT NULL,
    note       TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (kind, value)
);
ALTER TABLE sources ADD COLUMN role TEXT NOT NULL DEFAULT 'clip'
    CHECK (role IN ('clip','reference'));
ALTER TABLE sources ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX idx_sources_external ON sources(provider, external_id)
    WHERE external_id IS NOT NULL;
CREATE TABLE hashtag_searches (
    tag         TEXT PRIMARY KEY,
    searched_at TEXT NOT NULL
);
"""

# Migration 10: owner inspirations (051b), Reel links pasted from the phone with a note.
# url is the canonical https://www.instagram.com/(reel|p)/<code>/ form, one row per post.
INSPIRATIONS_SCHEMA = """
CREATE TABLE inspirations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    url        TEXT NOT NULL UNIQUE,
    note       TEXT,
    status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','used','dismissed')),
    created_at TEXT NOT NULL,
    used_at    TEXT
);
"""

# Migration 11: the reaction reel (071). One long owner recording; pieces are cut from it
# in order (cursor_s = where the next one starts). silences: [[start_s, end_s], ...] found
# once at upload. One reel is active at a time (the partial unique index).
REACTION_REEL_SCHEMA = """
CREATE TABLE reaction_reels (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL,
    duration_s  REAL NOT NULL,
    has_audio   INTEGER NOT NULL DEFAULT 1,
    silences    TEXT NOT NULL DEFAULT '[]',
    cursor_s    REAL NOT NULL DEFAULT 0,
    pieces_used INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_reaction_reels_active ON reaction_reels(active) WHERE active = 1;
CREATE TABLE reaction_pieces (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    reel_id    INTEGER NOT NULL REFERENCES reaction_reels(id),
    start_s    REAL NOT NULL,
    end_s      REAL NOT NULL,
    asset_id   INTEGER REFERENCES assets(id),
    created_at TEXT NOT NULL
);
"""

# Migration 12: what happens in each video (110). description: 2-3 plain sentences (the
# agent's, or an automatic one); timeline: JSON [{t, d, e}] written at render time.
ASSET_TIMELINE_SCHEMA = """
ALTER TABLE assets ADD COLUMN description TEXT;
ALTER TABLE assets ADD COLUMN timeline TEXT;
"""

# Migration 13: DM picks (113). Accounts the owner pins (username normalised: lowercase, no
# @; ig_user_id filled once seen in a conversation) and the Reels they sent the brand
# account by DM, one row per message. Nothing else from the DMs is ever stored.
DM_PICKS_SCHEMA = """
CREATE TABLE pinned_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL UNIQUE,
    ig_user_id  TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE dm_picks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id        TEXT NOT NULL UNIQUE,
    pinned_account_id INTEGER REFERENCES pinned_accounts(id) ON DELETE SET NULL,
    sender_username   TEXT NOT NULL,
    reel_url          TEXT NOT NULL,
    reel_media_id     TEXT,
    sender_note       TEXT,
    received_at       TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'new' CHECK (status IN
        ('new','downloaded','in_production','posted','skipped')),
    skip_reason       TEXT,
    source_id         INTEGER REFERENCES sources(id),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX idx_dm_picks_status ON dm_picks(status, received_at);
"""

# Migration 14: the daily-learn agent's structured analysis of a day (083):
# {best: [{media_id, why}], worst: [...], experiments: [{hypothesis, variable, variants}]}.
DAILY_ANALYSIS_SCHEMA = """
ALTER TABLE daily_reports ADD COLUMN analysis TEXT NOT NULL DEFAULT '{}';
"""

# Migration 15: experiments (086). One tag dimension (`variable`), 2-4 variant values; ideas
# join one through ideas.experiment = 'exp:<id>:<variant>' (older free-text values stay as
# they are and are no experiment). report_date: the daily report that proposed it;
# ends_on (owner-local) and opened_at are set when it opens. result: per-variant numbers.
EXPERIMENTS_SCHEMA = """
CREATE TABLE experiments (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis         TEXT NOT NULL,
    variable           TEXT NOT NULL,
    variants           TEXT NOT NULL,
    target_per_variant INTEGER NOT NULL DEFAULT 5 CHECK (target_per_variant >= 1),
    ends_on            TEXT
        CHECK (ends_on IS NULL OR ends_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status             TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN
        ('proposed','open','finished','abandoned')),
    result             TEXT,
    learning_id        INTEGER REFERENCES learnings(id),
    report_date        TEXT,
    opened_at          TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX idx_experiments_status ON experiments(status);
"""

# Migration 16: trial Reels (088). trial = 1: published as a trial Reel (shown to
# non-followers first). Instagram has no field for it, so the label is the only record;
# scoring keeps trial posts in their own group.
TRIAL_SCHEMA = """
ALTER TABLE post_labels ADD COLUMN trial INTEGER NOT NULL DEFAULT 0;
"""

# Migration 17: permission requests (065). The owner asks a creator to reuse a clip as is;
# the agent never contacts anyone. At most one open (`requested`) request per source.
# sources.ads_allowed: the licence or the creator in writing allows paid ads (rights.py).
PERMISSIONS_SCHEMA = """
CREATE TABLE permission_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    INTEGER NOT NULL REFERENCES sources(id),
    creator      TEXT NOT NULL,
    channel      TEXT NOT NULL CHECK (channel IN ('dm','email','other')),
    status       TEXT NOT NULL DEFAULT 'requested' CHECK (status IN
        ('requested','granted','denied')),
    requested_at TEXT NOT NULL,
    answered_at  TEXT,
    proof_note   TEXT,
    ads_allowed  INTEGER NOT NULL DEFAULT 0 CHECK (ads_allowed IN (0, 1)),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_permission_open ON permission_requests(source_id)
    WHERE status = 'requested';
ALTER TABLE sources ADD COLUMN ads_allowed INTEGER;
"""

# Migration 18: the ad spend ledger (091, src/ads/budget.py). Amounts are Decimal strings
# in `currency`. `authorized` reserves money before a spend, `released` (one per
# authorization) frees it, `reported` is spend Meta reports (095). Rows are never updated;
# created_at is always store.to_iso() (budget.py compares it as text for the daily cap).
AD_SPEND_SCHEMA = """
CREATE TABLE ad_spend_ledger (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL CHECK (kind IN ('authorized','reported','released')),
    amount           TEXT NOT NULL,
    currency         TEXT NOT NULL,
    test_id          INTEGER,
    ad_entity_id     TEXT,
    authorization_id INTEGER REFERENCES ad_spend_ledger(id),
    reason           TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    CHECK (kind <> 'released' OR authorization_id IS NOT NULL)
);
CREATE UNIQUE INDEX idx_spend_released ON ad_spend_ledger(authorization_id)
    WHERE kind = 'released';
"""

# Migration 19: what the studio created on Meta (092, src/ads/promote.py). Money columns are
# Decimal strings in the account currency; meta_id is Meta's id. A ledger row can spread an
# ad set's lifetime budget over its days for the daily cap (daily_amount per owner-local
# day, through daily_until, YYYY-MM-DD).
AD_ENTITIES_SCHEMA = """
CREATE TABLE ad_entities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL CHECK (kind IN ('campaign','adset','ad','creative')),
    meta_id         TEXT NOT NULL UNIQUE,
    parent_id       INTEGER REFERENCES ad_entities(id),
    test_id         INTEGER,
    asset_id        INTEGER REFERENCES assets(id),
    media_id        TEXT,
    status          TEXT NOT NULL,
    lifetime_budget TEXT,
    spend_cap       TEXT,
    end_time        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
ALTER TABLE ad_spend_ledger ADD COLUMN daily_amount TEXT;
ALTER TABLE ad_spend_ledger ADD COLUMN daily_until TEXT;
"""

# Migration 20: paid A/B tests (094, src/ads/tests.py). spec = abtest.TestSpec fields,
# needed = abtest.budget_needed + the rates it used; money columns are Decimal strings.
# ads_audit is append-only (triggers): every propose, approve, activate, cancel, kill, unkill.
AD_TESTS_SCHEMA = """
CREATE TABLE ad_tests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis      TEXT NOT NULL,
    variable        TEXT NOT NULL CHECK (variable IN ('creative','audience','placement')),
    variants        TEXT NOT NULL,
    spec            TEXT NOT NULL,
    baseline_rate   REAL NOT NULL,
    min_lift        REAL NOT NULL,
    needed          TEXT NOT NULL,
    budget_total    TEXT,
    currency        TEXT NOT NULL,
    end_date        TEXT,
    status          TEXT NOT NULL DEFAULT 'proposed'
                    CHECK (status IN ('proposed','approved','running','finished','cancelled')),
    underpowered_ok INTEGER NOT NULL DEFAULT 0,
    reason          TEXT,
    proposed_by     TEXT NOT NULL CHECK (proposed_by IN ('owner','agent')),
    approved_at     TEXT,
    finished_at     TEXT,
    result          TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE INDEX idx_ad_entities_test ON ad_entities(test_id);
CREATE TABLE ads_audit (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    actor   TEXT NOT NULL CHECK (actor IN ('owner','agent','system')),
    action  TEXT NOT NULL,
    test_id INTEGER REFERENCES ad_tests(id),
    detail  TEXT NOT NULL
);
CREATE TRIGGER ads_audit_no_update BEFORE UPDATE ON ads_audit
BEGIN SELECT RAISE(ABORT, 'ads_audit is append-only'); END;
CREATE TRIGGER ads_audit_no_delete BEFORE DELETE ON ads_audit
BEGIN SELECT RAISE(ABORT, 'ads_audit is append-only'); END;
"""

# Migration 21: the Trending page (134). sources.reaction: the owner's like / dislike of a
# reference. work_orders: references the owner sends the agent to make (inspired: an
# original video on the same idea; react: a commentary remix), with the owner's own
# instruction; idea_id / asset_id link what the agent made from it. Own table, not
# inspirations: other statuses, and one Reel may get several orders over time.
TRENDING_SCHEMA = """
ALTER TABLE sources ADD COLUMN reaction TEXT CHECK (reaction IN ('like','dislike'));
ALTER TABLE sources ADD COLUMN reacted_at TEXT;
CREATE TABLE work_orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   INTEGER NOT NULL REFERENCES sources(id),
    mode        TEXT NOT NULL CHECK (mode IN ('inspired','react')),
    instruction TEXT,
    status      TEXT NOT NULL DEFAULT 'new' CHECK (status IN
        ('new','in_production','in_feed','skipped')),
    skip_reason TEXT,
    idea_id     INTEGER REFERENCES ideas(id),
    asset_id    INTEGER REFERENCES assets(id),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_work_orders_open ON work_orders(source_id)
    WHERE status IN ('new','in_production');
CREATE INDEX idx_work_orders_idea ON work_orders(idea_id);
"""

# Migration 22: DM picks become work orders (136). The table is rebuilt (new CHECKs):
# source_id may be null (a DM order reaches its Reel through pick_id), mode `owner` (follow
# the owner's free-text instruction), statuses needs_instruction / scheduled (was `new`) /
# analysed, own_reel (the Reel is one of ours), blocked_reason (why it waits), analysis,
# scheduled_at (the at-once run's debounce). One open order per Trending Reel; a DM Reel
# may be sent twice. Every existing pick gets its order.
DM_ORDERS_SCHEMA = """
CREATE TABLE work_orders_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id      INTEGER REFERENCES sources(id),
    pick_id        INTEGER UNIQUE REFERENCES dm_picks(id),
    mode           TEXT NOT NULL CHECK (mode IN ('inspired','react','owner')),
    instruction    TEXT,
    own_reel       INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN
        ('needs_instruction','scheduled','in_production','in_feed','analysed','skipped')),
    skip_reason    TEXT,
    blocked_reason TEXT,
    analysis       TEXT,
    scheduled_at   TEXT,
    idea_id        INTEGER REFERENCES ideas(id),
    asset_id       INTEGER REFERENCES assets(id),
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    CHECK (source_id IS NOT NULL OR pick_id IS NOT NULL)
);
INSERT INTO work_orders_new (id, source_id, mode, instruction, status, skip_reason,
    scheduled_at, idea_id, asset_id, created_at, updated_at)
SELECT id, source_id, mode, instruction,
    CASE status WHEN 'new' THEN 'scheduled' ELSE status END, skip_reason,
    CASE status WHEN 'new' THEN created_at END, idea_id, asset_id, created_at, updated_at
FROM work_orders;
DROP TABLE work_orders;
ALTER TABLE work_orders_new RENAME TO work_orders;
CREATE UNIQUE INDEX idx_work_orders_open ON work_orders(source_id)
    WHERE pick_id IS NULL AND status IN ('needs_instruction','scheduled','in_production');
CREATE INDEX idx_work_orders_idea ON work_orders(idea_id);
CREATE INDEX idx_work_orders_status ON work_orders(status, scheduled_at);
INSERT INTO work_orders (pick_id, mode, instruction, status, skip_reason, scheduled_at,
    idea_id, created_at, updated_at)
SELECT p.id, 'owner', p.sender_note,
    CASE WHEN p.status = 'skipped' THEN 'skipped'
         WHEN p.status = 'posted' THEN 'in_feed'
         WHEN p.status = 'in_production' THEN 'in_production'
         WHEN p.sender_note IS NULL THEN 'needs_instruction' ELSE 'scheduled' END,
    CASE WHEN p.status = 'skipped' THEN p.skip_reason END,
    CASE WHEN p.status IN ('new','downloaded') AND p.sender_note IS NOT NULL
         THEN p.created_at END,
    (SELECT MAX(i.id) FROM ideas i WHERE i.source_id = p.source_id
     AND p.status IN ('in_production','posted')),
    p.created_at, p.updated_at
FROM dm_picks p ORDER BY p.id;
"""

# Append-only: MIGRATIONS[i] takes the database from user_version i to i+1.
# Never edit a released entry; add a new one.
MIGRATIONS: List[str] = [SCHEMA, STUDIO_SCHEMA, LEARNING_SCHEMA, AUDIENCE_SCHEMA,
                         ASSET_LINK_SCHEMA, WORKER_STATE_SCHEMA, DATA_JOBS_SCHEMA,
                         RENDER_SCHEMA, RESEARCH_SCHEMA, INSPIRATIONS_SCHEMA,
                         REACTION_REEL_SCHEMA, ASSET_TIMELINE_SCHEMA, DM_PICKS_SCHEMA,
                         DAILY_ANALYSIS_SCHEMA, EXPERIMENTS_SCHEMA, TRIAL_SCHEMA,
                         PERMISSIONS_SCHEMA, AD_SPEND_SCHEMA, AD_ENTITIES_SCHEMA,
                         AD_TESTS_SCHEMA, TRENDING_SCHEMA, DM_ORDERS_SCHEMA]

SOURCE_FIELDS = ("provider", "url", "author", "stats", "rights_basis", "rights_note",
                 "audio_rights", "local_path", "downloaded_at", "downloader_version",
                 "role", "external_id")
WATCH_KINDS = ("hashtag", "account")
# Hashtags may hold any letter or digit; usernames are Instagram's letters, digits, . and _.
# Both end up inside Graph request parameters, so nothing else gets in.
_WATCH_VALUE = {"hashtag": re.compile(r"\w{1,100}"),
                "account": re.compile(r"[a-z0-9._]{1,30}")}
INSPIRATION_STATUSES = ("new", "used", "dismissed")
INSPIRATION_NOTE_MAX = 200
_INSPIRATION_URL = re.compile(
    r"https://(?:www\.)?instagram\.com/(reel|p)/([A-Za-z0-9_-]+)/?(?:[?#].*)?")
IDEA_FIELDS = ("track", "pillar", "hook", "hook_type", "script", "source_id", "citations",
               "hypothesis", "strategy", "experiment", "batch_date")
ASSET_FIELDS = ("idea_id", "parent_asset_id", "file_path", "preview_path", "thumbnail_path",
                "caption", "audio_name", "recipe", "duration", "batch_date", "status",
                "verdict", "qc", "self_score", "self_score_reason", "best_before",
                "poster_path", "description", "timeline")
RENDER_JOB_FIELDS = ("state", "progress", "attempts", "failure", "started_at", "finished_at",
                     "render_ms", "heartbeat_at")
FEEDBACK_FIELDS = ("text", "reason_codes", "video_time_s", "wants_changes")
LEARNING_FIELDS = ("statement", "kind", "scope", "evidence", "confidence", "origin", "status")
EXPERIMENT_FIELDS = ("hypothesis", "variable", "variants", "target_per_variant", "ends_on",
                     "status", "result", "learning_id", "report_date", "opened_at")
JSON_FIELDS = ("stats", "citations", "recipe", "qc", "reason_codes", "scope", "evidence",
               "facts", "usage", "silences", "timeline", "analysis", "variants", "result",
               "spec", "needed", "detail", "change_request", "work_order")
# Timestamp columns _insert() fills with "now"; tables not listed get created_at.
_INSERT_STAMPS = {
    "assets": ("created_at", "updated_at"),
    "feedback": ("created_at", "updated_at"),
    "learnings": ("created_at", "updated_at"),
    "agent_runs": ("started_at",),
    "render_jobs": ("created_at", "updated_at"),
    "dm_picks": ("created_at", "updated_at"),
    "experiments": ("created_at", "updated_at"),
    "permission_requests": ("created_at", "updated_at"),
    "ad_entities": ("created_at", "updated_at"),
    "ad_tests": ("created_at", "updated_at"),
    "ads_audit": ("at",),
    "work_orders": ("created_at", "updated_at"),
}
ACCOUNT_SNAPSHOT_FIELDS = ("followers", "reach", "views", "reach_followers",
                           "reach_non_followers")
AGENT_RUN_END_STATUSES = ("succeeded", "failed", "cancelled")
# New assets start here; every later status move goes through studio.assets.transition().
# `needs_reaction` stays in the lifecycle but nothing enters it any more (072: a remix
# takes its reaction piece from the reel at render time).
ASSET_INITIAL_STATUSES = ("rendering",)
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
    close() (from any thread) waits for each connection's running transaction, and every
    later use raises sqlite3.ProgrammingError: closing a connection under another thread's
    query crashes SQLite.
    """

    def __init__(self, path: str):
        self.path = path
        self._memory = path == ":memory:"
        self._local = threading.local()
        self._conns: Dict[sqlite3.Connection, threading.RLock] = {}  # conn -> in-use lock
        self._conns_lock = threading.Lock()
        self._closed = False
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
            if self._closed:
                conn.close()
                raise sqlite3.ProgrammingError("the store is closed")
            self._conns[conn] = threading.RLock()
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
            with self._conns.get(conn, nullcontext()):  # tests' wrapper conns aren't listed
                if self._closed:
                    raise sqlite3.ProgrammingError("the store is closed")
                try:
                    yield conn
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

    @contextmanager
    def immediate(self) -> Iterator[sqlite3.Connection]:
        """_tx() that takes the write lock up front (BEGIN IMMEDIATE): a read-check-write
        no other connection can interleave with (the ad budget guard, 091)."""
        with self._tx() as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def close(self) -> None:
        """Close every connection this store opened, from any thread, each once its running
        transaction ends."""
        with self._conns_lock:
            self._closed = True
            conns, self._conns = self._conns, {}
        for conn, in_use in conns.items():
            with self._lock, in_use:
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
            asset_id=post["asset_id"], trial=bool(post["payload"].get("trial_graduation")),
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
        trial: bool = False,
    ) -> Dict[str, Any]:
        with self._tx() as c:
            c.execute(
                "INSERT INTO post_labels (media_id, campaign, variant, hypothesis, kind,"
                " asset_id, trial, created_at) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(media_id) DO UPDATE"
                " SET campaign=COALESCE(excluded.campaign, campaign),"
                " variant=COALESCE(excluded.variant, variant),"
                " hypothesis=COALESCE(excluded.hypothesis, hypothesis),"
                " kind=COALESCE(excluded.kind, kind),"
                " asset_id=COALESCE(excluded.asset_id, asset_id),"
                " trial=MAX(trial, excluded.trial)",  # once a trial, always a trial
                (media_id, campaign, variant, hypothesis, kind, asset_id, int(trial),
                 to_iso(utcnow())),
            )
        return self.get_label(media_id) or {}

    def get_label(self, media_id: str) -> Optional[Dict[str, Any]]:
        with self._tx() as c:
            row = c.execute("SELECT * FROM post_labels WHERE media_id=?", (media_id,)).fetchone()
        return dict(row) if row else None

    def mark_deleted(self, media_id: str, at: datetime) -> None:
        """Instagram reports the post gone: stop snapshotting it, keep its snapshots."""
        with self._tx() as c:
            c.execute(
                "INSERT INTO post_labels (media_id, created_at, deleted_at) VALUES (?,?,?)"
                " ON CONFLICT(media_id) DO UPDATE SET deleted_at=COALESCE(deleted_at,"
                " excluded.deleted_at)",
                (media_id, to_iso(utcnow()), to_iso(at)),
            )

    def labels(self, campaign: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        """Labels by media id, each with `duration_s`: the studio asset's video length
        (None for posts made outside the studio), used by scoring's watch ratio."""
        q = ("SELECT post_labels.*, assets.duration AS duration_s FROM post_labels"
             " LEFT JOIN assets ON assets.id = post_labels.asset_id")
        args: List[Any] = []
        if campaign:
            q += " WHERE post_labels.campaign=?"
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

    def snapshot_times(self, posted_since: datetime) -> Dict[str, Dict[str, Any]]:
        """Feed/Reel posts (not Stories, not deleted) posted since `posted_since`:
        {media_id: {posted_at, media_product_type, media_type, times: [captured_at...]}}."""
        out: Dict[str, Dict[str, Any]] = {}
        with self._tx() as c:
            rows = c.execute(
                "SELECT media_id, posted_at, media_product_type, media_type, captured_at"
                " FROM insight_snapshots WHERE posted_at >= ?"
                " AND COALESCE(media_product_type, '') != 'STORY' AND media_id NOT IN"
                " (SELECT media_id FROM post_labels WHERE deleted_at IS NOT NULL)",
                (to_iso(posted_since),),
            ).fetchall()
        for r in rows:
            d = out.setdefault(r["media_id"], {**dict(r), "times": []})
            d["times"].append(r["captured_at"])
        return out

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

    def media_snapshots(self, media_id: str) -> List[Dict[str, Any]]:
        """One post's snapshots, oldest first (indexed on media_id, captured_at)."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM insight_snapshots WHERE media_id=? ORDER BY captured_at, id",
                (media_id,),
            ).fetchall()
        return [{**dict(r), "metrics": json.loads(r["metrics"])} for r in rows]

    def snapshots_near_age(
        self, media_ids: Sequence[str], age_hours: float, min_age_hours: float
    ) -> Dict[str, Dict[str, Any]]:
        """Per media: the snapshot aged >= min_age_hours whose age is closest to age_hours
        (ties: the earliest captured). One query on the (media_id, captured_at) index."""
        if not media_ids:
            return {}
        marks = ",".join("?" * len(media_ids))
        with self._tx() as c:
            rows = c.execute(
                "SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY media_id"
                " ORDER BY ABS(age_hours - ?), captured_at, id) AS rn FROM insight_snapshots"
                f" WHERE media_id IN ({marks}) AND age_hours >= ?) WHERE rn = 1",
                (age_hours, *media_ids, min_age_hours),
            ).fetchall()
        out = {}
        for r in rows:
            d = {k: r[k] for k in r.keys() if k != "rn"}
            d["metrics"] = json.loads(d["metrics"])
            out[d["media_id"]] = d
        return out

    def latest_snapshots(self) -> List[Dict[str, Any]]:
        """Most recent snapshot per media, newest posts first, with the label's `trial`
        (0/1; scoring.group_of reads it)."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT s.*, COALESCE(l.trial, 0) AS trial FROM insight_snapshots s"
                " JOIN (SELECT media_id, MAX(id) AS mid FROM insight_snapshots"
                " GROUP BY media_id) m ON s.id = m.mid"
                " LEFT JOIN post_labels l ON l.media_id = s.media_id"
                " ORDER BY s.posted_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["metrics"] = json.loads(d["metrics"])
            out.append(d)
        return out

    # ------------------------------------------------------------------
    # Snapshot thinning (step 097)
    # ------------------------------------------------------------------
    def thin_snapshots(self, posted_before: datetime, keep_ages: Sequence[float]) -> int:
        """Per post posted before `posted_before`, keep the latest snapshot (MAX id, as
        latest_snapshots) and, for each age in keep_ages, the one nearest to it plus the
        nearest at or past it (what snapshots_near_age picks under a min age; same
        tie-break); delete the rest. Returns the number deleted."""
        with self._tx() as c:
            rows = c.execute(
                "SELECT id, media_id, age_hours, captured_at FROM insight_snapshots"
                " WHERE posted_at < ? AND age_hours IS NOT NULL ORDER BY media_id",
                (to_iso(posted_before),),
            ).fetchall()
            drop: List[int] = []
            for _, group in groupby(rows, key=lambda r: r["media_id"]):
                snaps = list(group)
                keep = {max(r["id"] for r in snaps)}
                for age in keep_ages:
                    ranked = sorted(snaps, key=lambda r: (abs(r["age_hours"] - age),
                                                          r["captured_at"], r["id"]))
                    past = next((r for r in ranked if r["age_hours"] >= age), ranked[0])
                    keep.update((ranked[0]["id"], past["id"]))
                drop += [r["id"] for r in snaps if r["id"] not in keep]
            c.executemany("DELETE FROM insight_snapshots WHERE id=?", [(i,) for i in drop])
        return len(drop)

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

    def patch_source_stats(self, source_id: int, patch: Dict[str, Any]) -> None:
        """Merge `patch` into the source's stats key by key (JSON merge patch)."""
        with self._tx() as c:
            if c.execute("UPDATE sources SET stats=json_patch(stats, ?) WHERE id=?",
                         (json.dumps(patch), source_id)).rowcount != 1:
                raise KeyError(f"No source with id {source_id}")

    def list_sources(
        self, rights_basis: Optional[str] = None, provider: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        return self._select("SELECT * FROM sources",
                            {"rights_basis": rights_basis, "provider": provider}, "id", limit)

    def upsert_reference_source(self, provider: str, external_id: str, *, url: Optional[str],
                                author: Optional[str], stats: Dict[str, Any]
                                ) -> Tuple[Dict[str, Any], bool]:
        """(source row, created). A new post is stored as a reference with rights unknown;
        a known one (same provider + external_id, any role) gets url and stats refreshed
        (stats merged key by key) and keeps an author it already has."""
        with self._tx() as c:  # write first: two processes can't both insert the same post
            cur = c.execute(
                "INSERT INTO sources (provider, external_id, url, author, stats, role,"
                " rights_basis, created_at) VALUES (?,?,?,?,?,'reference','unknown',?)"
                " ON CONFLICT(provider, external_id) WHERE external_id IS NOT NULL DO NOTHING",
                (provider, external_id, url, author, json.dumps(stats), to_iso(utcnow())))
            created = cur.rowcount == 1
            source_id = cur.lastrowid if created else c.execute(
                "UPDATE sources SET url=COALESCE(?, url), author=COALESCE(?, author),"
                " stats=json_patch(stats, ?) WHERE provider=? AND external_id=? RETURNING id",
                (url, author, json.dumps(stats), provider, external_id)).fetchone()[0]
        return self.get_source(source_id), created

    # ------------------------------------------------------------------
    # Research: watchlist and the hashtag budget
    # ------------------------------------------------------------------
    def add_watch(self, kind: str, value: str, note: Optional[str] = None) -> Dict[str, Any]:
        """Add a hashtag or account (normalised: lowercase, no #/@). Adding one that is
        already listed returns it, with the note replaced when one is given."""
        if kind not in WATCH_KINDS:
            raise ValueError(f"kind must be one of {', '.join(WATCH_KINDS)}")
        value = (value or "").strip().lstrip("#@").lower()
        if not _WATCH_VALUE[kind].fullmatch(value):
            raise ValueError(f"not a valid {kind}: {value!r}")
        with self._tx() as c:
            c.execute("INSERT INTO watchlist (kind, value, note, created_at) VALUES (?,?,?,?)"
                      " ON CONFLICT(kind, value) DO UPDATE SET"
                      " note=COALESCE(excluded.note, note)",
                      (kind, value, note, to_iso(utcnow())))
            row = c.execute("SELECT * FROM watchlist WHERE kind=? AND value=?",
                            (kind, value)).fetchone()
        return dict(row)

    def list_watchlist(self, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._select("SELECT * FROM watchlist", {"kind": kind}, "kind, value", 10_000)

    def remove_watch(self, watch_id: int) -> Dict[str, Any]:
        """Delete one entry and return it; KeyError when there is none."""
        row = self._get("watchlist", watch_id)
        with self._tx() as c:
            c.execute("DELETE FROM watchlist WHERE id=?", (watch_id,))
        return row

    def take_hashtag_search(self, tag: str, now: datetime, limit: int,
                            window: timedelta) -> bool:
        """Record a lookup of `tag` and return True if it fits: the tag was looked up within
        `window` (a repeat is free) or fewer than `limit` unique tags were. One write
        transaction, so concurrent processes never overshoot."""
        since = to_iso(now - window)
        # ponytail: a repeat moves the tag's time forward, so it counts longer (the safe side).
        with self._tx() as c:
            return c.execute(
                "INSERT INTO hashtag_searches (tag, searched_at) SELECT ?, ? WHERE"
                " EXISTS(SELECT 1 FROM hashtag_searches WHERE tag=? AND searched_at>?)"
                " OR (SELECT COUNT(*) FROM hashtag_searches WHERE searched_at>?) < ?"
                " ON CONFLICT(tag) DO UPDATE SET searched_at=excluded.searched_at",
                (tag, to_iso(now), tag, since, since, limit)).rowcount == 1

    # ------------------------------------------------------------------
    # Inspirations: Reel links the owner pastes with a note (051b)
    # ------------------------------------------------------------------
    def add_inspiration(self, url: str, note: Optional[str] = None) -> Dict[str, Any]:
        """Store a Reel or post link in its canonical form (query dropped). A link already
        stored returns the existing row unchanged."""
        m = _INSPIRATION_URL.fullmatch((url or "").strip())
        if not m:
            raise ValueError("paste an Instagram Reel or post link:"
                             " https://www.instagram.com/reel/<code>/ or /p/<code>/")
        note = (note or "").strip() or None
        if note and len(note) > INSPIRATION_NOTE_MAX:
            raise ValueError(f"the note is at most {INSPIRATION_NOTE_MAX} characters")
        url = f"https://www.instagram.com/{m[1]}/{m[2]}/"
        with self._tx() as c:
            c.execute("INSERT INTO inspirations (url, note, created_at) VALUES (?,?,?)"
                      " ON CONFLICT(url) DO NOTHING", (url, note, to_iso(utcnow())))
            row = c.execute("SELECT * FROM inspirations WHERE url=?", (url,)).fetchone()
        return dict(row)

    def list_inspirations(self, status: Optional[str] = None,
                          limit: int = 100) -> List[Dict[str, Any]]:
        """Newest first; all statuses when `status` is None."""
        return self._select("SELECT * FROM inspirations", {"status": status}, "id DESC", limit)

    def set_inspiration_status(self, inspiration_id: int, status: str) -> Dict[str, Any]:
        """used stamps used_at; any other status clears it. KeyError when there is none."""
        if status not in INSPIRATION_STATUSES:
            raise ValueError(f"status must be one of {', '.join(INSPIRATION_STATUSES)}")
        with self._tx() as c:
            c.execute("UPDATE inspirations SET status=?, used_at=? WHERE id=?",
                      (status, to_iso(utcnow()) if status == "used" else None, inspiration_id))
        return self._get("inspirations", inspiration_id)

    def delete_inspiration(self, inspiration_id: int) -> Dict[str, Any]:
        """Delete one and return it; KeyError when there is none."""
        row = self._get("inspirations", inspiration_id)
        with self._tx() as c:
            c.execute("DELETE FROM inspirations WHERE id=?", (inspiration_id,))
        return row

    # ------------------------------------------------------------------
    # Reaction reel (service rules: src/studio/reactions.py)
    # ------------------------------------------------------------------
    def add_reaction_reel(self, suffix: str, duration_s: float, has_audio: bool,
                          silences: List[List[float]]) -> Dict[str, Any]:
        """A new inactive reel; its path is `reactions/<id>/reel<suffix>`."""
        with self._tx() as c:
            cur = c.execute("INSERT INTO reaction_reels (path, duration_s, has_audio, silences,"
                            " created_at) VALUES ('', ?, ?, ?, ?)",
                            (duration_s, int(has_audio), json.dumps(silences),
                             to_iso(utcnow())))
            c.execute("UPDATE reaction_reels SET path=? WHERE id=?",
                      (f"reactions/{cur.lastrowid}/reel{suffix}", cur.lastrowid))
        return self._get("reaction_reels", cur.lastrowid)

    def get_reaction_reel(self, reel_id: int) -> Dict[str, Any]:
        return self._get("reaction_reels", reel_id)

    def list_reaction_reels(self) -> List[Dict[str, Any]]:
        return self._select("SELECT * FROM reaction_reels", {}, "id DESC", 1000)

    def active_reaction_reel(self) -> Optional[Dict[str, Any]]:
        rows = self._select("SELECT * FROM reaction_reels", {"active": 1}, "id", 1)
        return rows[0] if rows else None

    def activate_reaction_reel(self, reel_id: int) -> Dict[str, Any]:
        """Make this reel the only active one; KeyError when there is none."""
        self._get("reaction_reels", reel_id)
        with self._tx() as c:
            c.execute("UPDATE reaction_reels SET active=0 WHERE active=1 AND id<>?", (reel_id,))
            c.execute("UPDATE reaction_reels SET active=1 WHERE id=?", (reel_id,))
        return self._get("reaction_reels", reel_id)

    def delete_reaction_reel(self, reel_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM reaction_pieces WHERE reel_id=?", (reel_id,))
            c.execute("DELETE FROM reaction_reels WHERE id=?", (reel_id,))

    def reset_reaction_cursor(self, reel_id: int) -> Dict[str, Any]:
        with self._tx() as c:
            c.execute("UPDATE reaction_reels SET cursor_s=0, pieces_used=0 WHERE id=?",
                      (reel_id,))
        return self._get("reaction_reels", reel_id)

    def claim_reaction_piece(self, reel_id: int, cursor_s: float, start_s: float, end_s: float,
                             pieces_used: int, asset_id: Optional[int] = None
                             ) -> Optional[Dict[str, Any]]:
        """Record piece [start_s, end_s), move the cursor to end_s and set pieces_used, only
        if the reel is still active with its cursor at `cursor_s` (compare-and-set: of two
        concurrent callers one wins, the other gets None and reads again). One write
        transaction."""
        with self._tx() as c:
            if c.execute("UPDATE reaction_reels SET cursor_s=?, pieces_used=?"
                         " WHERE id=? AND active=1 AND cursor_s=?",
                         (end_s, pieces_used, reel_id, cursor_s)).rowcount != 1:
                return None
            cur = c.execute("INSERT INTO reaction_pieces (reel_id, start_s, end_s, asset_id,"
                            " created_at) VALUES (?,?,?,?,?)",
                            (reel_id, start_s, end_s, asset_id, to_iso(utcnow())))
        return self._get("reaction_pieces", cur.lastrowid)

    def get_reaction_piece(self, piece_id: int) -> Dict[str, Any]:
        return self._get("reaction_pieces", piece_id)

    def set_reaction_piece_asset(self, piece_id: int, asset_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE reaction_pieces SET asset_id=? WHERE id=?", (asset_id, piece_id))

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
        Rows carry their idea's track, strategy (explore/exploit) and experiment, its source's
        rights_basis (None: no source) and dm_pick_sender (the pinned account that sent the
        source by DM, else None) for the inbox, and change_request: on a revised video, the
        owner's newest change request on the version it replaces {text, reason_codes}, and
        work_order: the owner's work order (Trending or DM) its idea was made for {id, mode,
        instruction, permalink, source (dm | trend)} (every version of that idea), else None."""
        return self._select(
            "SELECT a.*, i.track, i.strategy, i.experiment, s.rights_basis,"
            " (SELECT d.sender_username FROM dm_picks d WHERE d.source_id = i.source_id"
            "  ORDER BY d.id LIMIT 1) AS dm_pick_sender,"
            " (SELECT json_object('text', f.text, 'reason_codes', json(f.reason_codes))"
            "  FROM feedback f WHERE f.asset_id = a.parent_asset_id AND f.wants_changes = 1"
            "  ORDER BY f.id DESC LIMIT 1) AS change_request,"
            " (SELECT json_object('id', w.id, 'mode', w.mode, 'instruction', w.instruction,"
            "  'permalink', COALESCE(ws.url, wp.reel_url),"
            "  'source', CASE WHEN w.pick_id IS NULL THEN 'trend' ELSE 'dm' END)"
            "  FROM work_orders w"
            "  LEFT JOIN sources ws ON ws.id = w.source_id"
            "  LEFT JOIN dm_picks wp ON wp.id = w.pick_id"
            "  WHERE w.idea_id = a.idea_id ORDER BY w.id DESC LIMIT 1) AS work_order"
            " FROM assets a JOIN ideas i ON i.id = a.idea_id"
            " LEFT JOIN sources s ON s.id = i.source_id",
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

    def save_daily_analysis(self, report_date: Any, summary: str,
                            analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Set the agent's summary and analysis of a day whose report row (the facts) exists;
        KeyError otherwise. The facts are kept."""
        day = _sql_value(report_date)
        with self._tx() as c:
            if c.execute("UPDATE daily_reports SET summary=?, analysis=? WHERE report_date=?",
                         (summary, json.dumps(analysis), day)).rowcount != 1:
                raise KeyError(f"No daily report for {day}")
        return self.get_daily_report(day)

    def get_daily_report(self, report_date: Any) -> Optional[Dict[str, Any]]:
        rows = self._select("SELECT * FROM daily_reports",
                            {"report_date": _sql_value(report_date)}, "id", 1)
        return rows[0] if rows else None

    def latest_daily_report(self) -> Optional[Dict[str, Any]]:
        """The newest report with a summary (a quiet day's facts-only row is passed over)."""
        rows = self._select("SELECT * FROM daily_reports WHERE summary IS NOT NULL", {},
                            "report_date DESC", 1)
        return rows[0] if rows else None

    # ------------------------------------------------------------------
    # Experiments (service rules: src/learning/experiments.py)
    # ------------------------------------------------------------------
    def add_experiment(self, hypothesis: str, variable: str, variants: Sequence[str],
                       **fields: Any) -> Dict[str, Any]:
        return self._insert("experiments", EXPERIMENT_FIELDS,
                            {"hypothesis": hypothesis, "variable": variable,
                             "variants": list(variants), **fields})

    def get_experiment(self, experiment_id: int) -> Dict[str, Any]:
        return self._get("experiments", experiment_id)

    def list_experiments(self, status: Optional[str] = None,
                         limit: int = 100) -> List[Dict[str, Any]]:
        return self._select("SELECT * FROM experiments", {"status": status}, "id DESC", limit)

    def update_experiment(self, experiment_id: int, **fields: Any) -> Dict[str, Any]:
        return self._update("experiments", EXPERIMENT_FIELDS, experiment_id, fields)

    def open_experiment(self, experiment_id: int, cap: int, *, target_per_variant: int,
                        ends_on: date) -> bool:
        """proposed -> open in one statement, only while fewer than `cap` are open."""
        with self._tx() as c:
            return c.execute(
                "UPDATE experiments SET status='open', target_per_variant=?, ends_on=?,"
                " opened_at=?, updated_at=? WHERE id=? AND status='proposed'"
                " AND (SELECT COUNT(*) FROM experiments WHERE status='open') < ?",
                (target_per_variant, ends_on.isoformat(), to_iso(utcnow()), to_iso(utcnow()),
                 experiment_id, cap)).rowcount == 1

    def delete_proposed_experiments(self, report_date: str) -> int:
        with self._tx() as c:
            return c.execute("DELETE FROM experiments WHERE status='proposed'"
                             " AND report_date=?", (report_date,)).rowcount

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

    def save_account_snapshot(self, day: date, raw: Mapping[str, Any], **values: Any) -> None:
        """Insert or replace the account row of one owner-local date. `values`: followers,
        reach, views, reach_followers, reach_non_followers (None when Meta gave none)."""
        row = {k: values.get(k) for k in ACCOUNT_SNAPSHOT_FIELDS}
        with self._tx() as c:
            c.execute(
                f"INSERT INTO account_snapshots (date, {', '.join(row)}, raw, captured_at)"
                f" VALUES ({','.join('?' * (len(row) + 3))}) ON CONFLICT(date) DO UPDATE SET "
                + ", ".join(f"{k}=excluded.{k}" for k in (*row, "raw", "captured_at")),
                (_sql_value(day), *row.values(), json.dumps(raw), to_iso(utcnow())),
            )

    def account_snapshots(self) -> List[Dict[str, Any]]:
        with self._tx() as c:
            rows = c.execute("SELECT * FROM account_snapshots ORDER BY date").fetchall()
        return [{**dict(r), "raw": json.loads(r["raw"])} for r in rows]

    # ------------------------------------------------------------------
    # Shared Graph request budget
    # ------------------------------------------------------------------
    def take_request_slot(self, now: float, period: float, cap: int) -> float:
        """Count one Graph request (unix time `now`) if fewer than `cap` happened in the last
        `period` s: 0.0. Otherwise nothing is counted and the result is the seconds until
        the oldest one leaves the window. One write transaction, so concurrent processes
        never overshoot the cap."""
        with self._tx() as c:
            c.execute("DELETE FROM graph_requests WHERE at <= ?", (now - period,))
            if c.execute("INSERT INTO graph_requests (at) SELECT ? WHERE"
                         " (SELECT COUNT(*) FROM graph_requests) < ?", (now, cap)).rowcount:
                return 0.0
            oldest = c.execute("SELECT MIN(at) FROM graph_requests").fetchone()[0]
        return oldest + period - now

    def graph_requests_since(self, since: float) -> int:
        with self._tx() as c:
            return c.execute("SELECT COUNT(*) FROM graph_requests WHERE at > ?",
                             (since,)).fetchone()[0]

    # ------------------------------------------------------------------
    # Render queue (service rules: src/studio/render.py)
    # ------------------------------------------------------------------
    def add_render_job(self, asset_id: int, key: str) -> Dict[str, Any]:
        """A queued job for `key`, or the job that already has this key (any state)."""
        now = to_iso(utcnow())
        with self._tx() as c:
            c.execute("INSERT INTO render_jobs (asset_id, idempotency_key, created_at, updated_at)"
                      " VALUES (?,?,?,?) ON CONFLICT(idempotency_key) DO NOTHING",
                      (asset_id, key, now, now))
            row = c.execute("SELECT * FROM render_jobs WHERE idempotency_key=?",
                            (key,)).fetchone()
        return _decode(row)

    def get_render_job(self, job_id: int) -> Dict[str, Any]:
        return self._get("render_jobs", job_id)

    def update_render_job(self, job_id: int, **fields: Any) -> Dict[str, Any]:
        return self._update("render_jobs", RENDER_JOB_FIELDS, job_id, fields)

    def list_render_jobs(self, state: Optional[str] = None, asset_id: Optional[int] = None,
                         limit: int = 100) -> List[Dict[str, Any]]:
        """Newest first."""
        return self._select("SELECT * FROM render_jobs", {"state": state, "asset_id": asset_id},
                            "id DESC", limit)

    def claim_render_jobs(self, limit: int, stale_before: datetime) -> List[Dict[str, Any]]:
        """Re-queue running jobs whose heartbeat is older than `stale_before` (a crashed
        worker's), then move up to `limit` queued jobs, oldest first, to running (attempts + 1).
        One write transaction, so two workers never claim the same job."""
        if limit <= 0:
            return []
        now = to_iso(utcnow())
        with self._tx() as c:
            c.execute("UPDATE render_jobs SET state='queued', updated_at=?"
                      " WHERE state='running' AND heartbeat_at < ?", (now, to_iso(stale_before)))
            rows = c.execute(
                "UPDATE render_jobs SET state='running', attempts=attempts+1, progress=0,"
                " started_at=?, heartbeat_at=?, updated_at=? WHERE id IN"
                " (SELECT id FROM render_jobs WHERE state='queued' ORDER BY id LIMIT ?)"
                " RETURNING *", (now, now, now, limit)).fetchall()
        return sorted((_decode(r) for r in rows), key=lambda j: j["id"])

    def touch_render_jobs(self, job_ids: Sequence[int]) -> None:
        """Heartbeat for jobs still rendering."""
        if job_ids:
            with self._tx() as c:
                c.execute(f"UPDATE render_jobs SET heartbeat_at=? WHERE state='running'"
                          f" AND id IN ({','.join('?' * len(job_ids))})",
                          [to_iso(utcnow()), *job_ids])

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
