"""Step 147: an owner change request starts the light run at once, like a work order
(src/agent/schedule.py order_run): debounce, once per new request, cap, lock, one run."""

from datetime import timedelta

import pytest

from src import store as store_mod
from src.agent import runner, schedule
from src.studio import work_orders
from src.studio.assets import transition
from src.studio.feedback import add_comment

from .test_agent_packet import _asset
from .test_dm_work_orders import T0, Clock, Starts, _dm_order, cfg


@pytest.fixture
def clock(monkeypatch):
    c = Clock()  # every stamp (feedback, runs, orders) and the lock's age on one clock
    for mod in (work_orders, store_mod, runner):
        monkeypatch.setattr(mod, "utcnow", c)
    return c


def _ask(store, text="plus court"):
    return add_comment(store, _asset(store), text=text, wants_changes=True)["asset"]["id"]


def _run(store, minutes, s=None, f=None):
    f = f or Starts()
    return schedule.order_run(store, s or cfg(), T0 + timedelta(minutes=minutes),
                              start=f.start, check=f.check)


def test_a_change_request_starts_the_run_after_the_debounce(store, clock):
    f = Starts()
    _ask(store)
    assert _run(store, 2, f=f) is None and f.runs == []  # debounce
    assert _run(store, 3, f=f) == "daily-revise" and f.runs == ["daily-revise"]
    assert _run(store, 30, f=f) is None and len(f.runs) == 1  # handled once
    clock.set(40)
    _ask(store, "la voix plus lente")  # a new request: one more run
    assert _run(store, 43, f=f) == "daily-revise" and len(f.runs) == 2


def test_a_request_older_than_the_last_revise_run_wakes_nothing(store, clock):
    _ask(store)  # read by the run below and left waiting (e.g. needs a missing capability)
    clock.set(5)
    run = store.start_agent_run("daily-revise")
    store.finish_agent_run(run["id"], "succeeded")
    f = Starts()
    assert _run(store, 60, f=f) is None and f.checks == 0


def test_comments_that_wake_nothing(store, clock):
    aid = _asset(store)
    add_comment(store, aid, text="joli")  # no change asked
    transition(store, _ask(store), "archived", actor="system")  # its new version replaced it
    assert _run(store, 60) is None


def test_cap_and_lock(store, clock):
    s = cfg(max_order_runs_per_day=1)
    _ask(store)
    run = store.start_agent_run("daily-revise")  # started before the request, still running
    clock.set(1)
    _ask(store)
    assert _run(store, 10, s) is None  # one run at a time
    store.finish_agent_run(run["id"], "succeeded")
    assert _run(store, 10, s) == "daily-revise"
    clock.set(11)
    oid = _dm_order(store, "réagis")
    _ask(store)
    assert _run(store, 20, s) is None  # today's one at-once run is used
    assert "1 at-once runs are used" in work_orders.get_order(store, oid)["blocked_reason"]


def test_orders_and_requests_together_make_one_run(store, clock):
    f = Starts()
    _dm_order(store, "réagis")
    clock.set(2)
    _ask(store)
    assert _run(store, 4, f=f) is None  # the request is the newest: its debounce counts
    assert _run(store, 5, f=f) == "daily-revise"
    assert _run(store, 6, f=f) is None and f.runs == ["daily-revise"]
