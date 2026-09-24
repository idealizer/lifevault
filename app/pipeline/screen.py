"""Local multilingual screening. Newsletters stay off the model unless a strong signal is present."""

from __future__ import annotations

import re

_IBAN = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")

STRONG = (
    "statement",
    "invoice",
    "account number",
    "policy number",
    "policennummer",
    "iban",
    "direct debit",
    "lastschrift",
    "premium",
    "prämie",
    "praemie",
    "prime d'assurance",
    "premio",
    "subscription",
    "abonnement",
    "abbonamento",
    "renewal",
    "verlängerung",
    "verlaengerung",
    "renouvellement",
    "rinnovo",
    "password reset",
    "passwort zurücksetzen",
    "passwort zuruecksetzen",
    "réinitialisation",
    "reinitialisation",
    "kontoauszug",
    "rechnung",
    "facture",
    "fattura",
    "estratto conto",
    "relevé",
    "releve",
    "police d'assurance",
    "police",
    "versicherung",
    "assurance",
    "assicurazione",
    "pensionskasse",
    "caisse de pension",
    "cassa pensioni",
    "vorsorge",
    "freizügigkeit",
    "freizuegigkeit",
    "säule",
    "saeule",
    "pillar",
    "hypothek",
    "hypothèque",
    "hypotheque",
    "ipoteca",
    "mortgage",
    "lebensversicherung",
    "life insurance",
    "krankenkasse",
    "stromrechnung",
    "utility bill",
    "steuererklärung",
    "steuererklaerung",
    "déclaration d'impôts",
    "declaration d'impots",
    "dichiarazione dei redditi",
    "tax return",
    "domain",
    "domaine",
    "dominio",
    "hosting",
    "wallet",
    "crypto",
    "bitcoin",
    "depot",
    "portfolio",
    "broker",
    "ubs",
    "postfinance",
    "raiffeisen",
    "swissquote",
    "zkb",
    "viac",
    "finpension",
    "truewealth",
    "revolut",
    "twint",
    "swisscom",
    "helsana",
    "swica",
    "baloise",
    "mobiliar",
    "suva",
    "estv",
    "ahv",
    "avs",
)

WEAK = (
    "welcome",
    "willkommen",
    "bienvenue",
    "benvenuto",
    "your account",
    "ihr konto",
    "votre compte",
    "il tuo conto",
    "new account",
    "neues konto",
)

NOISE = (
    "unsubscribe",
    "abmelden",
    "désinscrire",
    "desinscrire",
    "newsletter",
    "view in browser",
    "im browser anzeigen",
    "% off",
    "rabatt",
    "soldes",
)


def _has_term(text: str, term: str) -> bool:
    if " " in term or len(term) > 4:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def screen_message(from_addr: str, subject: str, snippet: str) -> bool:
    raw = f"{from_addr}\n{subject}\n{snippet}"
    text = raw.lower()
    compact = re.sub(r"\s+", "", raw).upper()
    if _IBAN.search(compact):
        return True
    if any(_has_term(text, term) for term in STRONG):
        return True
    if any(_has_term(text, term) for term in WEAK) and not any(term in text for term in NOISE):
        return True
    return False
