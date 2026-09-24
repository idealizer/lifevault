from app.categories import CATEGORY_KEYS
from app.pipeline.estate_actions import ESTATE_ACTIONS, actions_for, parse_proposals


def test_every_class_has_estate_actions():
    assert set(ESTATE_ACTIONS) == CATEGORY_KEYS
    for options in ESTATE_ACTIONS.values():
        assert len(options) >= 3


def test_parse_keeps_only_listed_actions():
    allowed = {4: actions_for("domains_hosting")}
    text = """```json
    {"proposals":[
      {"id":4,"action":"Renew the domain so it does not expire","reason":"The offer is a renewal."},
      {"id":4,"action":"Hack the registrar","reason":"no"},
      {"id":9,"action":"Renew the domain so it does not expire","reason":"unknown asset"}
    ]}
    ```"""
    chosen = parse_proposals(text, allowed)
    assert list(chosen) == [4]
    assert chosen[4][0] == "Renew the domain so it does not expire"
