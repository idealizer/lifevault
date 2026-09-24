from app.pipeline.signals import signals_for_message


def test_domain_offer_becomes_a_hosting_asset():
    findings = signals_for_message(
        {
            "id": 4,
            "from_addr": "Idealizer Host <info@basler-fasnacht.ch>",
            "subject": "Domain offer: basler-fasnacht.ch",
            "snippet": "Domain: basler-fasnacht.ch",
        }
    )
    domains = [item for item in findings if item["category"] == "domains_hosting"]
    assert domains[0]["label"] == "basler-fasnacht.ch"
    assert domains[0]["identifiers"][0]["value"] == "basler-fasnacht.ch"


def test_bank_impersonation_is_a_risk():
    findings = signals_for_message(
        {
            "id": 5,
            "from_addr": "RAIFFEISEN <quickserve1997@gmail.com>",
            "subject": "Wichtig: Eine Verifizierung ist erforderlich",
            "snippet": "",
        }
    )
    assert findings[0]["category"] == "risks"
    assert "Raiffeisen" in findings[0]["label"]


def test_plain_mail_has_no_local_signal():
    assert signals_for_message({"id": 1, "from_addr": "a@example.com", "subject": "Lunch", "snippet": ""}) == []
