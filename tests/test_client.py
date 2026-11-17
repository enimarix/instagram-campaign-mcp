import json

import httpx
import pytest
import respx

from src.instagram_client import InstagramAPIError, InvalidMedia, RateLimitExceeded

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
    with pytest.raises(InstagramAPIError, match="5 hashtags"):
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
async def test_reels_insights_ask_the_retention_metrics(client):
    route = respx.get(f"{API}/M1/insights").respond(json={"data": [
        {"name": "reels_skip_rate", "values": [{"value": 31.5}]},
        {"name": "ig_reels_video_view_total_time", "values": [{"value": 120000}]},
        {"name": "reposts", "values": [{"value": 2}]}]})
    res = await client.get_media_insights("M1", media_product_type="REELS")
    asked = route.calls.last.request.url.params["metric"].split(",")
    assert {"ig_reels_video_view_total_time", "reels_skip_rate", "reposts",
            "ig_reels_avg_watch_time"} <= set(asked)
    assert res["metrics"] == {"reels_skip_rate": 31.5, "ig_reels_video_view_total_time": 120000,
                              "reposts": 2}


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


# ---------------------------------------------------------------- regressions
@respx.mock
async def test_cached_response_is_not_mutated_by_callers(settings):
    from src.instagram_client import InstagramClient

    c = InstagramClient(settings.model_copy(update={"cache_enabled": True}),
                        http_client=httpx.AsyncClient())
    route = respx.get(f"{API}/1789").respond(json={"business_discovery": {
        "username": "rival", "media": {"data": [{"id": "R1"}]}}})
    try:
        first = await c.get_competitor_profile("rival")
        second = await c.get_competitor_profile("rival")
    finally:
        await c.close()
    assert route.call_count == 1  # second call served from cache
    assert first["recent_media"] == second["recent_media"] == [{"id": "R1"}]


@respx.mock
async def test_http_error_without_graph_error_body_raises(client):
    respx.get(f"{API}/M1").respond(500, json={})
    with pytest.raises(InstagramAPIError, match="HTTP 500"):
        await client.get_media("M1")


@respx.mock
async def test_429_with_non_json_body_is_rate_limit(client):
    respx.get(f"{API}/M1").respond(429, text="Too Many Requests")
    with pytest.raises(RateLimitExceeded):
        await client.get_media("M1")


@respx.mock
async def test_insights_raise_when_every_metric_fails(client):
    respx.get(f"{API}/BAD/insights").respond(
        400, json={"error": {"message": "Unsupported get request", "code": 100}})
    with pytest.raises(InstagramAPIError, match="Unsupported"):
        await client.get_media_insights("BAD", media_product_type="FEED")


def test_hashtag_limit_counts_hashtags_not_hash_signs():
    from src.instagram_client import caption_problem

    assert caption_problem("C# tips " + "# " * 40) is None
    assert caption_problem(" ".join(f"#t{i}" for i in range(31)))


@respx.mock
async def test_dm_uses_page_token_and_page_endpoint(client):
    respx.get(f"{API}/me/accounts").respond(json={"data": [
        {"id": "P0", "instagram_business_account": {"id": "other"}},
        {"id": "P1", "instagram_business_account": {"id": "1789"}}]})
    token = respx.get(f"{API}/P1").respond(json={"access_token": "page_tok", "id": "P1"})
    send = respx.post(f"{API}/P1/messages").respond(json={"message_id": "x"})

    await client.send_dm("IGSID", "hello")
    await client.send_dm("IGSID", "again", page_id="P1")

    assert token.call_count == 1  # page token is cached
    req = send.calls.last.request
    assert req.headers["Authorization"] == "Bearer page_tok"
    assert _body(send.calls[0]) == {"recipient": {"id": "IGSID"}, "message": {"text": "hello"}}


# ---------------------------------------------------------------- Reels from local files
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"


@pytest.fixture
def video(client, tmp_path):
    client.settings.media_root = str(tmp_path)
    (tmp_path / "2026-11-17" / "4").mkdir(parents=True)
    (tmp_path / "2026-11-17" / "4" / "final.mp4").write_bytes(b"\x00mp4" * 1000)
    return "2026-11-17/4/final.mp4"


@respx.mock
async def test_publish_local_reel_uses_resumable_upload(client, video):
    uri = f"{RUPLOAD}/v27.0/C1"  # taken from the create response, not hard-coded
    create = respx.post(f"{API}/1789/media").respond(json={"id": "C1", "uri": uri})
    upload = respx.post(uri).respond(json={"success": True, "message": "Upload successful."})
    respx.get(f"{API}/C1").mock(side_effect=[
        httpx.Response(200, json={"status_code": "IN_PROGRESS"}),
        httpx.Response(200, json={"status_code": "FINISHED"}),
    ])
    publish = respx.post(f"{API}/1789/media_publish").respond(json={"id": "M1"})
    respx.get(f"{API}/M1").respond(json={"id": "M1"})

    res = await client.publish_reel(caption="hi", thumb_offset_ms=1500, audio_name="Tune",
                                    video_path=video)

    body = _body(create.calls.last)
    assert body["upload_type"] == "resumable" and body["media_type"] == "REELS"
    assert body["thumb_offset"] == 1500 and body["audio_name"] == "Tune"
    assert "video_url" not in body
    req = upload.calls.last.request
    assert req.headers["Authorization"] == "OAuth test_token"
    assert req.headers["offset"] == "0" and req.headers["file_size"] == "4000"
    assert "transfer-encoding" not in req.headers
    assert req.content == b"\x00mp4" * 1000
    assert _body(publish.calls.last) == {"creation_id": "C1"}
    assert res["media_id"] == "M1"


@respx.mock
async def test_local_reel_processing_error_raises_meta_message(client, video):
    respx.post(f"{API}/1789/media").respond(json={"id": "C2"})
    respx.post(f"{RUPLOAD}/v25.0/C2").respond(json={"success": True})
    respx.get(f"{API}/C2").respond(json={"status_code": "ERROR", "status": "Error: 2207026"})
    publish = respx.post(f"{API}/1789/media_publish")
    with pytest.raises(InstagramAPIError, match="2207026"):
        await client.publish_reel(video_path=video)
    assert not publish.called


@respx.mock
async def test_local_reel_upload_retried_after_transient_failure(client, video):
    respx.post(f"{API}/1789/media").respond(json={"id": "C3"})
    upload = respx.post(f"{RUPLOAD}/v25.0/C3").mock(side_effect=[
        httpx.ConnectError("reset"),
        httpx.Response(500, json={"debug_info": {"retriable": True, "message": "busy"}}),
        httpx.Response(200, json={"success": True}),
    ])
    respx.get(f"{API}/C3").respond(json={"status_code": "FINISHED"})
    respx.post(f"{API}/1789/media_publish").respond(json={"id": "M3"})
    respx.get(f"{API}/M3").respond(json={"id": "M3"})
    res = await client.publish_reel(video_path=video)
    assert upload.call_count == 3
    assert res["media_id"] == "M3"


@respx.mock
async def test_local_reel_non_retriable_upload_failure(client, video):
    respx.post(f"{API}/1789/media").respond(json={"id": "C4"})
    upload = respx.post(f"{RUPLOAD}/v25.0/C4").respond(400, json={"debug_info": {
        "retriable": False, "type": "ProcessingFailedError", "message": "unauthorized"}})
    with pytest.raises(InstagramAPIError, match="unauthorized"):
        await client.publish_reel(video_path=video)
    assert upload.call_count == 1


@pytest.mark.parametrize("rel", ["../outside.mp4", "ABS", "missing.mp4", "2026-11-17", ""])
@respx.mock
async def test_local_reel_bad_path_rejected_before_network(client, video, tmp_path, rel):
    (tmp_path.parent / "outside.mp4").write_bytes(b"x")
    if rel == "ABS":
        rel = str(tmp_path / video)  # exists inside the root, but absolute
    with pytest.raises(InvalidMedia):
        await client.publish_reel(video_path=rel)
    assert not respx.calls
