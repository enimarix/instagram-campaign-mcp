"""create_idea guards (step 056): quotas (src/learning/quotas.py), duplicates, citations."""

from difflib import SequenceMatcher

import pytest

from src.learning.quotas import todays_quotas
from src.studio import production

DAY = "2026-11-17"
CITE = [{"url": "https://example.org/fact", "title": "Source"}]
WORDS = ["apple", "brick", "cloud", "dune", "ember", "fjord", "glyph", "harp", "igloo", "jazz",
         "kiwi", "lynx", "moss", "nymph", "onyx"]


def _new(store, settings, hook, track="motion", **kw):
    kw.setdefault("pillar", "stories")
    return production.create_idea(store, settings, track, hook=hook, batch_date=DAY, **kw)


def _fill(store, settings, n, **kw):
    for w in WORDS[:n]:
        _new(store, settings, w * 3, **kw)


def test_todays_quotas_limits_and_counts(store, settings):
    downloaded = {"local_path": "clips/a.mp4", "rights_basis": "commentary", "author": "x"}
    used = store.add_source("local_inbox", **downloaded)
    store.add_source("local_inbox", **downloaded)  # available
    store.add_source("local_inbox", local_path="clips/c.mp4")  # rights unknown
    store.add_source("local_inbox", rights_basis="own")  # not downloaded
    store.add_idea("remix", pillar="stories", source_id=used["id"], batch_date=DAY)
    store.add_idea("motion", pillar="everyday_humor", strategy="explore", batch_date=DAY)
    store.add_idea("motion", strategy="exploit", batch_date=DAY)
    store.add_idea("motion", pillar="everyday_humor", batch_date="2026-11-16")
    q = todays_quotas(store, settings, DAY)
    assert q["limits"] == {"ideas": 10, "explore": 3, "humour": 6, "informative": 6,
                           "reactions": 2}  # 1 reaction made + 1 clip left, under 3 + 2
    assert q["counts"] == {"ideas": 3, "explore": 1, "humour": 1, "informative": 2,
                           "reactions": 1}
    assert q["humour_target"] == 5 and q["clips_available"] == 1 and q["date"] == DAY


def test_batch_full(store, settings):
    settings.batch_size = 2
    _fill(store, settings, 2)  # the 2nd fills it exactly
    with pytest.raises(ValueError, match="batch full: 2/2 ideas today"):
        _new(store, settings, "Something new")


def test_explore_quota(store, settings):
    _fill(store, settings, 3, strategy="explore")  # ceil(10 x 0.3) = 3
    with pytest.raises(ValueError, match="explore quota used: 3/3; make it exploit"):
        _new(store, settings, "One more experiment", strategy="explore")
    _new(store, settings, "One more experiment", strategy="exploit")


@pytest.mark.parametrize("pillar, other, match", [
    ("everyday_humor", "stories", "humour 4/3: pick an informative pillar"),
    ("stories", "everyday_humor", "informative 4/3: pick a humour pillar"),
])
def test_humour_mix(store, settings, pillar, other, match):
    settings.batch_size = 4  # target 2, each side allowed 3
    _fill(store, settings, 3, pillar=pillar)
    with pytest.raises(ValueError, match=match):
        _new(store, settings, "Fresh take", pillar=pillar)
    _new(store, settings, "Fresh take", pillar=other)
    assert len(store.list_ideas(batch_date=DAY)) == 4


def test_reaction_cap_by_setting_and_clips(store, settings):
    settings.max_reactions_per_day, settings.reaction_margin = 1, 1
    clips = [store.add_source("local_inbox", local_path=f"c{i}.mp4", rights_basis="commentary",
                              author="x")["id"] for i in range(3)]
    _new(store, settings, "React one", "remix", source_id=clips[0])
    _new(store, settings, "React two", "remix", source_id=clips[1])  # 2/2 allowed
    with pytest.raises(ValueError, match=r"reaction quota used: 2/2 \(1 downloaded"):
        _new(store, settings, "React three", "remix", source_id=clips[2])


def test_reaction_cap_by_downloaded_clips(store, settings):
    clip = store.add_source("local_inbox", local_path="c.mp4", rights_basis="commentary",
                            author="x")
    store.add_source("local_inbox", rights_basis="commentary", author="x")  # not downloaded
    _new(store, settings, "React one", "remix", source_id=clip["id"])
    with pytest.raises(ValueError, match=r"reaction quota used: 1/1 \(0 downloaded"):
        _new(store, settings, "React two", "remix")
    _new(store, settings, "A motion idea instead")


def test_near_duplicate_of_hook_or_first_sentence(store, settings):
    old = store.add_idea("motion", hook="Octopuses have three hearts!", batch_date="2026-11-10",
                         script="Bananas are berries. Strawberries are not.")
    with pytest.raises(ValueError, match=rf"near-duplicate of idea {old['id']} \(2026-11-10\):"
                                         r" 'Octopuses have three hearts!'; change the angle"):
        _new(store, settings, "octopuses... have THREE hearts")
    with pytest.raises(ValueError, match="near-duplicate"):
        _new(store, settings, "Fruit lies", script="Bananas are berries!\nMore.")
    store.add_idea("motion", hook="Sharks are older than trees", batch_date="2026-10-17")
    _new(store, settings, "Sharks are older than trees")  # 31 days ago: out of the window


def test_duplicate_threshold_edges(store, settings):
    store.add_idea("motion", hook="Cats sleep sixteen hours a day", batch_date=DAY)
    hook = "Cats sleep twelve hours a day!"
    ratio = SequenceMatcher(None, "cats sleep sixteen hours a day",
                            "cats sleep twelve hours a day").ratio()
    settings.dedupe_threshold = ratio  # just at the threshold: refused
    with pytest.raises(ValueError, match="near-duplicate"):
        _new(store, settings, hook)
    settings.dedupe_threshold = ratio + 0.001  # just under it: allowed
    _new(store, settings, hook)


@pytest.mark.parametrize("citations, match", [
    (None, r"fact pillar 'fun_facts' needs citations: add \[\{url, title\}\]"),
    ([], "needs citations"),
    ([{"url": "ftp://example.org/x"}], "needs an http"),
    ([{"title": "no url"}], "needs an http"),
    (["https://example.org"], "needs an http"),
    ({"url": "https://example.org"}, "must be a list"),
])
def test_fact_pillar_needs_valid_citations(store, settings, citations, match):
    with pytest.raises(ValueError, match=match):
        _new(store, settings, "Honey never spoils", pillar="fun_facts", citations=citations)
    assert store.list_ideas() == []


def test_citations_ok_and_optional_elsewhere(store, settings):
    idea = _new(store, settings, "Honey never spoils", pillar="fun_facts", citations=CITE)
    assert idea["citations"] == CITE
    assert _new(store, settings, "A short story")["citations"] == []
