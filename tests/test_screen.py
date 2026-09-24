from app.pipeline.screen import screen_message


def test_screens_statements_in_four_languages():
    assert screen_message("ubs@example.com", "Kontoauszug März", "")
    assert screen_message("billing@example.com", "Your invoice is ready", "")
    assert screen_message("mail@example.fr", "Facture d'assurance", "")
    assert screen_message("banca@example.it", "Estratto conto", "")


def test_screens_iban_and_account_welcome():
    assert screen_message("", "Hello", "CH93 0076 2011 6238 5295 7")
    assert screen_message("ubs@example.com", "Willkommen bei UBS", "Ihr Konto ist bereit")


def test_skips_newsletters_and_empty_mail():
    assert not screen_message("news@example.com", "Weekly deals", "Unsubscribe · 20% off")
    assert not screen_message("friend@example.com", "Lunch on Thursday", "Can you make it?")
    assert not screen_message("", "", "")


def test_keeps_invoice_even_if_it_mentions_newsletter():
    assert screen_message("billing@example.com", "Rechnung", "Newsletter abmelden")
