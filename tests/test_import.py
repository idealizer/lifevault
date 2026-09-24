import json

import pytest

from app.pipeline.import_mail import ImportError, parse_mail_file


def test_csv_uses_the_expected_fields():
    raw = (
        "sender,recipient,senddate,subject,message\n"
        "billing@news.example,ada@example.com,2024-03-01,Your subscription,Renews 2025-03-01 for 12 months\n"
    ).encode()
    records = parse_mail_file("mail.csv", raw)
    assert records[0]["sender"] == "billing@news.example"
    assert records[0]["recipient"] == "ada@example.com"
    assert records[0]["senddate"].startswith("2024-03-01")
    assert "12 months" in records[0]["message"]


def test_json_accepts_aliases_and_a_messages_list():
    payload = {
        "messages": [
            {
                "from": "bank@example.com",
                "to": "ada@example.com",
                "date": "01.02.2023",
                "subject": "Kontoauszug",
                "body": "Period 01.01.2023 to 31.01.2023",
            }
        ]
    }
    records = parse_mail_file("export.json", json.dumps(payload).encode())
    assert records[0]["sender"] == "bank@example.com"
    assert records[0]["subject"] == "Kontoauszug"
    assert "31.01.2023" in records[0]["message"]


def test_empty_file_is_rejected():
    with pytest.raises(ImportError):
        parse_mail_file("empty.csv", b"sender,recipient,senddate,subject,message\n")
