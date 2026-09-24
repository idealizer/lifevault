from app.pipeline.merge import collapse_findings, make_merge_key, merge_finding_records


def _finding(**overrides):
    base = {
        "category": "banking",
        "provider": "UBS AG",
        "asset_kind": "current_account",
        "label": "UBS account",
        "identifiers": [{"type": "iban", "value": "CH9300762011623852957"}],
        "confidence": 0.6,
        "evidence_ids": ["1"],
        "excerpt": "statement",
        "status": "candidate",
    }
    base.update(overrides)
    base["merge_key"] = make_merge_key(base["category"], base["provider"], base["identifiers"])
    return base


def test_provider_suffix_does_not_split_the_key():
    left = make_merge_key("banking", "UBS AG", [{"type": "iban", "value": "CH93"}])
    right = make_merge_key("banking", "ubs", [{"type": "iban", "value": "ch93"}])
    assert left == right


def test_merge_keeps_confirmed_status_and_higher_confidence():
    existing = _finding(status="confirmed", confidence=0.4, label="Kept")
    incoming = _finding(
        provider="ubs",
        confidence=0.9,
        label="New",
        identifiers=[
            {"type": "iban", "value": "CH9300762011623852957"},
            {"type": "email", "value": "a@example.com"},
        ],
        evidence_ids=["2"],
    )
    merged = merge_finding_records(existing, incoming)
    assert merged["status"] == "confirmed"
    assert merged["confidence"] == 0.9
    assert merged["label"] == "New"
    assert {item["value"] for item in merged["identifiers"]} == {
        "CH9300762011623852957",
        "a@example.com",
    }
    assert merged["evidence_ids"] == ["1", "2"]


def test_dismissed_is_not_reopened_and_batch_collapses():
    existing = _finding(status="dismissed")
    merged = merge_finding_records(existing, _finding(status="candidate", confidence=0.2))
    assert merged["status"] == "dismissed"
    collapsed = collapse_findings([
        _finding(evidence_ids=["1"]),
        _finding(provider="UBS", evidence_ids=["9"], confidence=0.95),
    ])
    assert len(collapsed) == 1
    assert collapsed[0]["evidence_ids"] == ["1", "9"]
    assert collapsed[0]["confidence"] == 0.95
