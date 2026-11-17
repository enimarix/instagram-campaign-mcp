import json

import httpx
import pytest
import respx

from src.instagram_client import InstagramAPIError, RateLimitExceeded

from .conftest import API


def _body(call):
    return json.loads(call.request.content or b"{}")


@respx.mock
async def test_token_sent_as_header_not_query(client):
    route = respx.get(f"{API}/me").respond(json={"id": "1"})
    assert await client.validate_access_token()
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer test_token"
    assert "access_token" not in str(req.url)


@respx.mock
async def test_publish_reel_waits_for_processing_and_sends_trial_params(client):
    create = respx.post(f"{API}/1789/media").respond(json={"id": "C1"})
    respx.get(f"{API}/C1").mock(side_effect=[
        httpx.Response(200, json={"status_code": "IN_PROGRESS", "id": "C1"}),
        httpx.Response(200, json={"status_code": "IN_PROGRESS", "id": "C1"}),
        httpx.Response(200, json={"status_code": "FINISHED", "id": "C1"}),
    ])
    publish = respx.post(f"{API}/1789/media_publish").respond(json={"id": "M1"})
    respx.get(f"{API}/M1").respond(json={"id": "M1", "permalink": "https://ig/p/1",
                                          "media_product_type": "REELS"})

    res = await client.publish_reel("https://cdn/x.mp4", "hello", trial_graduation="SS_PERFORMANCE")

    body = _body(create.calls.last)
    assert body["media_type"] == "REELS"
    assert body["trial_params"] == {"graduation_strategy": "SS_PERFORMANCE"}
    assert "cover_url" not in body  # None values are dropped
    assert _body(publish.calls.last) == {"creation_id": "C1"}
    assert res == {"media_id": "M1", "container_id": "C1",
                   "permalink": "https://ig/p/1", "media_product_type": "REELS"}


@respx.mock
async def test_container_error_raises_with_meta_detail(client):
    respx.post(f"{API}/1789/media").respond(json={"id": "C9"})
    respx.get(f"{API}/C9").respond(json={"status_code": "ERROR", "status": "Error: 2207026"})
    with pytest.raises(InstagramAPIError, match="2207026"):
        await client.publish_reel("https://cdn/bad.mp4")


@respx.mock
async def test_publish_carousel_builds_children_then_parent(client):
    ids = iter(["K1", "K2", "P1"])
    create = respx.post(f"{API}/1789/media").mock(
        side_effect=lambda req: httpx.Response(200, json={"id": next(ids)}))
    for cid in ("K1", "K2", "P1"):
        respx.get(f"{API}/{cid}").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(json={"id": "M2"})
    respx.get(f"{API}/M2").respond(json={"id": "M2"})

    res = await client.publish_carousel(
        [{"image_url": "https://cdn/1.jpg", "alt_text": "chart"},
         {"video_url": "https://cdn/2.mp4"}], caption="swipe")

    bodies = [_body(c) for c in create.calls]
    assert bodies[0] == {"image_url": "https://cdn/1.jpg", "is_carousel_item": True,
                         "alt_text": "chart"}
    assert bodies[1]["media_type"] == "VIDEO" and bodies[1]["is_carousel_item"] is True
    assert bodies[2]["media_type"] == "CAROUSEL" and bodies[2]["children"] == "K1,K2"
    assert res["children"] == ["K1", "K2"]


async def test_carousel_size_is_checked(client):
    with pytest.raises(InstagramAPIError, match="2 to 10"):
        await client.publish_carousel([{"image_url": "https://cdn/1.jpg"}])


async def test_too_many_hashtags_rejected(client):
    with pytest.raises(InstagramAPIError, match="30 hashtags"):
        await client.publish_image("https://cdn/1.jpg", " ".join(f"#t{i}" for i in range(31)))


@respx.mock
async def test_story_needs_exactly_one_media(client):
    with pytest.raises(InstagramAPIError):
        await client.publish_story()
    create = respx.post(f"{API}/1789/media").respond(json={"id": "S1"})
    respx.get(f"{API}/S1").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(json={"id": "M3"})
    respx.get(f"{API}/M3").respond(json={"id": "M3"})
    await client.publish_story(image_url="https://cdn/s.jpg")
    assert _body(create.calls.last) == {"media_type": "STORIES", "image_url": "https://cdn/s.jpg"}


@respx.mock
async def test_insights_pick_reels_metrics_and_fall_back_per_metric(client):
    def handler(request):
        metric = request.url.params["metric"]
        if "," in metric:  # whole batch rejected because of one metric
            return httpx.Response(400, json={"error": {"message": "bad metric", "code": 100}})
        if metric == "ig_reels_avg_watch_time":
            return httpx.Response(400, json={"error": {"message": "not supported", "code": 100}})
        return httpx.Response(200, json={"data": [
            {"name": metric, "period": "lifetime", "values": [{"value": 10}]}]})

    respx.get(f"{API}/M1/insights").mock(side_effect=handler)
    res = await client.get_media_insights("M1", media_product_type="REELS")
    assert res["metrics"]["reach"] == 10 and res["metrics"]["saved"] == 10
    assert "follows" not in res["metrics"]  # not a Reels metric
    assert "ig_reels_avg_watch_time" in res["unavailable"]


@respx.mock
async def test_insights_total_value_shape(client):
    respx.get(f"{API}/M1/insights").respond(json={"data": [
        {"name": "reach", "total_value": {"value": 42}}]})
    res = await client.get_media_insights("M1", metrics=["reach"])
    assert res["metrics"] == {"reach": 42}


@respx.mock
async def test_rate_limit_error_code_maps_to_rate_limit_exception(client):
    respx.get(f"{API}/1789").respond(
        400, json={"error": {"message": "Application request limit reached", "code": 4}})
    with pytest.raises(RateLimitExceeded):
        await client.get_profile_info()


@respx.mock
async def test_hide_and_delete_comment(client):
    hide = respx.post(f"{API}/CM1").respond(json={"success": True})
    delete = respx.delete(f"{API}/CM1").respond(json={"success": True})
    await client.hide_comment("CM1")
    await client.delete_comment("CM1")
    assert _body(hide.calls.last) == {"hide": True}
    assert delete.called


@respx.mock
async def test_hashtag_search_two_step(client):
    respx.get(f"{API}/ig_hashtag_search").respond(json={"data": [{"id": "H1"}]})
    top = respx.get(f"{API}/H1/top_media").respond(json={"data": [{"id": "X"}]})
    res = await client.search_hashtag("#nutrition")
    assert res["posts"] == [{"id": "X"}]
    assert top.calls.last.request.url.params["user_id"] == "1789"


@respx.mock
async def test_competitor_profile_flattens_media(client):
    route = respx.get(f"{API}/1789").respond(json={"business_discovery": {
        "username": "rival", "followers_count": 5000,
        "media": {"data": [{"id": "R1", "like_count": 99}]}}})
    res = await client.get_competitor_profile("@rival")
    assert res["recent_media"][0]["id"] == "R1" and "media" not in res
    assert "business_discovery.username(rival)" in route.calls.last.request.url.params["fields"]
