import json

import httpx
import pytest
import respx

from src.ads.client import AdsClient, usage_wait_s
from src.config import InstagramMCPSettings
from src.instagram_client import InstagramAPIError, NotConfigured, RateLimitExceeded

from .conftest import API

ACT = f"{API}/act_42"


@pytest.fixture
def ads_settings(settings):
    return settings.model_copy(update={"meta_ad_account_id": "42"})


@pytest.fixture
async def ads(ads_settings):
    c = AdsClient(ads_settings, http_client=httpx.AsyncClient())
    yield c
    await c.close()


@pytest.fixture
def mock():
    """Every route of this suite, and every request made, must be a GET (read only)."""
    with respx.mock as router:
        yield router
    assert all("<Method eq 'GET'>" in repr(r.pattern) for r in router.routes)
    assert all(call.request.method == "GET" for call in router.calls)


def _paged(rows, after=None):
    body = {"data": rows}
    if after:
        body["paging"] = {"cursors": {"after": after}, "next": f"{ACT}/x?after={after}"}
    return body


@pytest.mark.parametrize("method,edge", [
    ("list_campaigns", "campaigns"), ("list_ad_sets", "adsets"), ("list_ads", "ads"),
])
async def test_lists_follow_cursor_paging(ads, mock, method, edge):
    route = mock.get(f"{ACT}/{edge}").mock(side_effect=[
        httpx.Response(200, json=_paged([{"id": "1"}], after="C1")),
        httpx.Response(200, json=_paged([{"id": "2"}])),
    ])
    rows = await getattr(ads, method)()
    assert [r["id"] for r in rows] == ["1", "2"]
    first, second = (c.request for c in route.calls)
    assert "effective_status" in first.url.params["fields"]
    assert "after" not in first.url.params and second.url.params["after"] == "C1"
    for req in (first, second):
        assert req.headers["Authorization"] == "Bearer test_token"
        assert "access_token" not in str(req.url)


async def test_ad_accounts_need_no_account_id(settings, mock):
    mock.get(f"{API}/me/adaccounts").respond(json=_paged([{"id": "act_42"}]))
    async with AdsClient(settings, http_client=httpx.AsyncClient()) as c:
        assert await c.list_ad_accounts() == [{"id": "act_42"}]
        with pytest.raises(NotConfigured):
            await c.list_campaigns()


async def test_insights_with_date_range(ads, mock):
    route = mock.get(f"{API}/77/insights").respond(json=_paged([{"spend": "1.50"}]))
    rows = await ads.get_insights("77", since="2026-11-01", until="2026-11-07", level="ad")
    assert rows == [{"spend": "1.50"}]
    params = route.calls.last.request.url.params
    assert json.loads(params["time_range"]) == {"since": "2026-11-01", "until": "2026-11-07"}
    assert params["level"] == "ad" and "date_preset" not in params


async def test_insights_preset_on_account_and_bad_args(ads, mock):
    route = mock.get(f"{ACT}/insights").respond(json=_paged([]))
    await ads.get_insights(date_preset="last_7d")
    assert route.calls.last.request.url.params["date_preset"] == "last_7d"
    for kwargs in ({"date_preset": "lifetime"}, {"since": "2026-11-01"},
                   {"since": "2026-11-07", "until": "2026-11-01"}, {"level": "page"}):
        with pytest.raises(ValueError):
            await ads.get_insights(**kwargs)
    with pytest.raises(ValueError):
        await ads.get_insights("../me")
    assert route.call_count == 1


async def test_error_body_maps_to_api_error(ads, mock):
    mock.get(f"{ACT}/ads").respond(400, json={"error": {
        "message": "Unsupported get request", "code": 100, "error_subcode": 33}})
    with pytest.raises(InstagramAPIError) as e:
        await ads.list_ads()
    assert not isinstance(e.value, RateLimitExceeded)
    assert (e.value.error_code, e.value.error_subcode) == (100, 33)


@pytest.mark.parametrize("code,subcode", [(17, 2446079), (613, 1487742), (80004, 2446079),
                                          (80000, 2446079), (4, 1504022)])
async def test_rate_limit_codes(ads, mock, code, subcode):
    mock.get(f"{ACT}/campaigns").respond(400, json={"error": {
        "message": "too many calls", "code": code, "error_subcode": subcode}})
    with pytest.raises(RateLimitExceeded):
        await ads.list_campaigns()


async def test_usage_headers_block_next_call(ads, mock):
    buc = {"42": [{"type": "ads_management", "call_count": 100, "total_cputime": 20,
                   "total_time": 20, "estimated_time_to_regain_access": 5}]}
    route = mock.get(f"{ACT}/campaigns").respond(
        json=_paged([{"id": "1"}]), headers={"x-business-use-case-usage": json.dumps(buc)})
    assert await ads.list_campaigns() == [{"id": "1"}]  # this answer is still good
    with pytest.raises(RateLimitExceeded, match="5 min"):
        await ads.list_campaigns()
    assert route.call_count == 1  # the blocked call never reached Meta


def test_usage_wait_reads_both_headers():
    h = httpx.Headers({"x-ad-account-usage": json.dumps(
        {"acc_id_util_pct": 100, "reset_time_duration": 300})})
    assert usage_wait_s(h) == 300
    assert usage_wait_s(httpx.Headers({"x-ad-account-usage": '{"acc_id_util_pct": 9.6}'})) == 0
    assert usage_wait_s(httpx.Headers({"x-business-use-case-usage": "not json"})) == 0
    assert usage_wait_s(httpx.Headers()) == 0


@pytest.mark.parametrize("token", [None, "", "your_long_lived_access_token"])
def test_not_configured_without_token(settings, token):
    with pytest.raises(NotConfigured, match="ads_not_configured"):
        AdsClient(settings.model_copy(update={"instagram_access_token": token}))


@pytest.mark.parametrize("raw,want", [("42", "42"), ("act_42", "42"), ("", None), (None, None)])
def test_ad_account_id_setting(raw, want):
    assert InstagramMCPSettings(_env_file=None, meta_ad_account_id=raw).meta_ad_account_id == want


@pytest.mark.parametrize("raw", ["12a", "4 2", "act_x", "٤٢"])
def test_ad_account_id_setting_rejects_non_digits(raw):
    with pytest.raises(ValueError):
        InstagramMCPSettings(_env_file=None, meta_ad_account_id=raw)


def test_client_has_no_write_method():
    """Read only: no code path in the ads client names another HTTP verb."""
    import inspect

    from src.ads import client

    src = inspect.getsource(client)
    assert all(verb not in src for verb in ('"POST"', '"DELETE"', ".post(", ".delete("))
