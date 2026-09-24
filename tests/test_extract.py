from app.pipeline.extract import normalize_finding, parse_findings


FENCED = """
Here is the result:
```json
{"findings":[{"category":"Banking","provider":"UBS AG","asset_kind":"current_account","label":"UBS account","identifiers":[{"type":"iban","value":"CH9300762011623852957"},{"type":"password","value":"secret"}],"confidence":1.4,"evidence_ids":["12"],"excerpt":"Kontoauszug"}]}
```
"""


def test_parse_fenced_json_strips_secrets_and_clamps_confidence():
    findings = parse_findings(FENCED)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["category"] == "banking"
    assert finding["confidence"] == 1.0
    assert finding["identifiers"] == [{"type": "iban", "value": "CH9300762011623852957"}]
    assert finding["evidence_ids"] == ["12"]
    assert finding["merge_key"].startswith("banking|ubs|")


def test_unknown_category_and_alias():
    finding = normalize_finding({"provider": "VIAC", "category": "pension", "confidence": "0.4"})
    assert finding["category"] == "investments_pensions"
    other = normalize_finding({"provider": "Archive", "category": "mystery"})
    assert other["category"] == "other"


def test_accepts_assets_key_and_institution_field():
    raw = '{"assets":[{"institution":"Swisscom","category":"subscriptions","asset_kind":"mobile"}]}'
    findings = parse_findings(raw)
    assert findings[0]["provider"] == "Swisscom"
    assert findings[0]["category"] == "subscriptions"


def test_invalid_and_empty_provider():
    assert parse_findings("not json") == []
    assert parse_findings('{"findings":[{"category":"banking"}]}') == []
    assert normalize_finding({"provider": "   "}) is None
