"""Letter prose in the language of the source email."""

from __future__ import annotations

import re

LANGS = ("de", "fr", "it", "en")

_MARKERS = {
    "de": (
        " und ", " der ", " die ", " das ", " nicht ", " ihr ", " konto", " sehr geehrte",
        " mitteilung", " verstorben", " nachlass", " bitte ", " für ", " über ", " bank",
        " versicherung", " gutschrift", " saldo",
    ),
    "fr": (
        " vous ", " votre ", " nous ", " madame", " monsieur", " compte", " décès",
        " succession", " veuillez", " assurance", " merci ", " pour ", " avec ",
    ),
    "it": (
        " gentile", " conto", " decesso", " successione", " prego", " assicurazione",
        " voi ", " nostro", " vostra", " grazie", " per favore",
    ),
    "en": (
        " the ", " and ", " please ", " your ", " account", " dear ", " policy",
        " subscription", " estate", " death",
    ),
}

_ID_LABELS = {
    "en": {
        "iban": "IBAN",
        "email": "the email address",
        "account": "account number",
        "policy": "policy number",
        "reference": "reference",
        "phone": "telephone number",
        "domain": "the domain",
        "username": "the username",
    },
    "de": {
        "iban": "IBAN",
        "email": "die E-Mail-Adresse",
        "account": "die Kontonummer",
        "policy": "die Policennummer",
        "reference": "die Referenz",
        "phone": "die Telefonnummer",
        "domain": "die Domain",
        "username": "der Benutzername",
    },
    "fr": {
        "iban": "IBAN",
        "email": "l'adresse e-mail",
        "account": "le numéro de compte",
        "policy": "le numéro de police",
        "reference": "la référence",
        "phone": "le numéro de téléphone",
        "domain": "le domaine",
        "username": "le nom d'utilisateur",
    },
    "it": {
        "iban": "IBAN",
        "email": "l'indirizzo e-mail",
        "account": "il numero di conto",
        "policy": "il numero di polizza",
        "reference": "il riferimento",
        "phone": "il numero di telefono",
        "domain": "il dominio",
        "username": "il nome utente",
    },
}

# Exact catalogue step -> purpose. Unknown free text uses "custom".
_PURPOSE = {
    "Notify the bank of the death and request the balance": "bank_notify",
    "Ask for statements up to the date of death": "statements",
    "Freeze the account until the estate is ready": "freeze",
    "Move the balance to the estate account": "transfer_balance",
    "Close the account after distribution": "close_account",
    "Notify the provider of the death": "notify_death",
    "Request a valuation at the date of death": "valuation",
    "Claim a survivor or death benefit": "claim_benefit",
    "Transfer the holding to the heir named in the will": "transfer_heir",
    "Sell the holding and pay the proceeds to the estate": "sell",
    "Record the exchange or wallet in the estate inventory": "record",
    "Notify the exchange of the death": "notify_death",
    "Ask the exchange for the estate-access procedure": "access_procedure",
    "Transfer the holding to the estate if access already exists": "transfer_estate",
    "Leave the holding documented until access is found": "record",
    "Notify the insurer of the death": "notify_death",
    "File a claim on the policy": "claim_policy",
    "Ask for the policy schedule and surrender value": "policy_schedule",
    "Keep cover on estate property until it is transferred": "keep_cover",
    "Cancel cover that is no longer needed": "cancel",
    "Keep the service running for the property": "keep_service",
    "Transfer the contract to the heir or estate": "transfer_contract",
    "Settle the final bill": "final_bill",
    "End the contract": "end_contract",
    "Tell the authority that the person has died": "notify_death",
    "Include the item in the estate filing": "record",
    "File the final tax return": "tax_return",
    "Claim a refund owed to the estate": "refund",
    "Send the notice to the estate lawyer": "lawyer",
    "Notify the employer of the death": "notify_death",
    "Claim unpaid salary or expenses": "unpaid",
    "Ask about a death-in-service benefit": "claim_benefit",
    "Collect employment documents for the estate": "documents",
    "Close the business role or mandate": "close_role",
    "Cancel the subscription": "cancel",
    "Settle the final invoice": "final_bill",
    "Check whether a refund is due": "refund",
    "Transfer the subscription if the provider allows it": "transfer_contract",
    "Leave it until the paid period ends, then cancel": "cancel_later",
    "Renew the domain so it does not expire": "renew",
    "Transfer the domain to the heir or estate": "transfer_contract",
    "Update the registrant contact": "update_contact",
    "Download site or mailbox data the estate needs": "documents",
    "Cancel hosting after the content is saved": "cancel",
    "Send the document to the estate lawyer": "lawyer",
    "Keep the document in the estate file": "record",
    "Check whether a deadline applies": "deadline",
    "Reply to the sender as executor": "reply",
    "Close the matter if it is already settled": "close_matter",
    "Ask the provider to close the account": "close_account",
    "Ask the provider about a memorial or legacy contact": "memorial",
    "Download data the estate is entitled to": "documents",
    "Recover the account only if the estate already has access": "access_procedure",
    "Leave the account documented and take no login attempt": "record",
    "Do not reply to the sender": "record",
    "Record it as a likely impersonation": "record",
    "Report it to the real institution": "report",
    "Ignore it after it is noted in the file": "record",
    "Ask the estate lawyer before any response": "lawyer",
    "Review what the estate should do with it": "review",
    "Contact the provider as executor": "reply",
    "Keep it in the inventory until more evidence appears": "record",
    "Transfer it to an heir": "transfer_heir",
    "Close it": "close_account",
}


def detect_language(text: str) -> str:
    sample = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    if not sample.strip():
        return "en"
    scores = {lang: sum(sample.count(mark) for mark in marks) for lang, marks in _MARKERS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "en"
    return best


def reference_sentence(identifiers: list, lang: str) -> str:
    labels = _ID_LABELS.get(lang) or _ID_LABELS["en"]
    parts = []
    for item in identifiers or []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        key = str(item.get("type") or "reference").lower()
        label = labels.get(key) or labels["reference"]
        parts.append(f"{label} {value}")
    if not parts:
        return ""
    joined = _join(parts, lang)
    return {
        "de": f"Zur Identifikation: {joined}.",
        "fr": f"Pour l'identification : {joined}.",
        "it": f"Per l'identificazione: {joined}.",
        "en": f"For identification: {joined}.",
    }[lang]


def compose(action: str, lang: str, ctx: dict) -> dict:
    lang = lang if lang in LANGS else "en"
    purpose = _PURPOSE.get(action.strip(), "custom")
    pack = _PACKS[lang]
    request = pack["requests"].get(purpose) or pack["requests"]["custom"]
    fields = {
        "deceased": ctx.get("deceased") or _unknown(lang),
        "died": ctx.get("died") or "",
        "provider": ctx.get("provider") or _org(lang),
        "asset": ctx.get("asset") or _asset(lang),
        "action": _sentence(action),
    }
    death = pack["died"].format(**fields) if fields["died"] else ""
    intro = pack["intro"].format(**fields, death=death)
    body = request.format(**fields)
    ref = reference_sentence(ctx.get("identifiers") or [], lang)
    paragraphs = [intro, body]
    if purpose == "transfer_balance":
        account = estate_account_sentence(ctx, lang)
        if account:
            paragraphs.append(account)
    if ref:
        paragraphs.append(ref)
    paragraphs.append(pack["enclosures"])
    paragraphs.append(pack["confirm"])
    subject = pack["subjects"].get(purpose) or pack["subjects"]["custom"]
    return {
        "subject": subject.format(**fields),
        "salutation": pack["salutation"],
        "paragraphs": paragraphs,
        "closing": pack["closing"],
    }


def estate_account_sentence(ctx: dict, lang: str) -> str:
    bank = str(ctx.get("estate_bank") or "").strip()
    iban = str(ctx.get("estate_iban") or "").strip()
    swift = str(ctx.get("estate_swift") or "").strip()
    if not (bank or iban or swift):
        return ""
    parts = [part for part in (bank, f"IBAN {iban}" if iban else "", f"SWIFT {swift}" if swift else "") if part]
    detail = ", ".join(parts)
    return {
        "de": f"Bitte überweisen Sie den Betrag auf das Nachlasskonto: {detail}.",
        "fr": f"Veuillez virer le montant sur le compte de la succession : {detail}.",
        "it": f"Vi prego di versare l'importo sul conto del lascito: {detail}.",
        "en": f"Please pay the amount to the estate account: {detail}.",
    }[lang]


def _sentence(action: str) -> str:
    text = re.sub(r"\s+", " ", (action or "").strip()).rstrip(".")
    if not text:
        return "attend to this matter"
    return text[0].lower() + text[1:]


def _join(parts: list[str], lang: str) -> str:
    if len(parts) == 1:
        return parts[0]
    conj = {"de": " und ", "fr": " et ", "it": " e ", "en": " and "}[lang]
    return ", ".join(parts[:-1]) + conj + parts[-1]


def _unknown(lang: str) -> str:
    return {"de": "der verstorbenen Person", "fr": "la personne décédée", "it": "la persona defunta", "en": "the deceased"}[lang]


def _org(lang: str) -> str:
    return {"de": "Ihrer Organisation", "fr": "votre organisation", "it": "la vostra organizzazione", "en": "your organisation"}[lang]


def _asset(lang: str) -> str:
    return {"de": "der betreffenden Beziehung", "fr": "la relation concernée", "it": "il rapporto in questione", "en": "the relationship in question"}[lang]


def _pack(lang: str, salutation: str, intro: str, died: str, enclosures: str, confirm: str, closing: str, subjects: dict, requests: dict) -> dict:
    return {
        "salutation": salutation,
        "intro": intro,
        "died": died,
        "enclosures": enclosures,
        "confirm": confirm,
        "closing": closing,
        "subjects": subjects,
        "requests": requests,
    }


_EN_SUBJECTS = {
    "bank_notify": "Death of {deceased} — balance of the account",
    "statements": "Death of {deceased} — statements to the date of death",
    "freeze": "Death of {deceased} — please hold the account",
    "transfer_balance": "Death of {deceased} — payment of the balance to the estate",
    "close_account": "Death of {deceased} — closure",
    "notify_death": "Death of {deceased}",
    "valuation": "Death of {deceased} — valuation at the date of death",
    "claim_benefit": "Death of {deceased} — claim",
    "transfer_heir": "Death of {deceased} — transfer to the heir",
    "sell": "Death of {deceased} — realisation of the holding",
    "record": "Death of {deceased} — estate file",
    "access_procedure": "Death of {deceased} — access for the estate",
    "transfer_estate": "Death of {deceased} — transfer to the estate",
    "claim_policy": "Death of {deceased} — claim under the policy",
    "policy_schedule": "Death of {deceased} — policy schedule and surrender value",
    "keep_cover": "Death of {deceased} — please maintain the cover",
    "cancel": "Death of {deceased} — please end the contract",
    "keep_service": "Death of {deceased} — please keep the service running",
    "transfer_contract": "Death of {deceased} — transfer of the contract",
    "final_bill": "Death of {deceased} — final invoice",
    "end_contract": "Death of {deceased} — end of the contract",
    "tax_return": "Death of {deceased} — final return",
    "refund": "Death of {deceased} — amount due to the estate",
    "lawyer": "Death of {deceased} — correspondence for the estate",
    "unpaid": "Death of {deceased} — amounts still due",
    "documents": "Death of {deceased} — documents for the estate",
    "close_role": "Death of {deceased} — end of the mandate",
    "cancel_later": "Death of {deceased} — cancellation at the end of the paid period",
    "renew": "Death of {deceased} — renewal",
    "update_contact": "Death of {deceased} — change of contact",
    "deadline": "Death of {deceased} — deadline",
    "reply": "Death of {deceased}",
    "close_matter": "Death of {deceased} — closure of the file",
    "memorial": "Death of {deceased} — memorial or legacy contact",
    "report": "Death of {deceased} — report of a suspicious message",
    "review": "Death of {deceased}",
    "custom": "Death of {deceased}",
}

_EN_REQUESTS = {
    "bank_notify": "I am writing to inform you of the death and to ask for the balance of {asset} with {provider} as at the date of death, together with any interest accrued to that date.",
    "statements": "Please send the statements for {asset} with {provider} covering the period up to and including the date of death, so the estate can complete its accounts.",
    "freeze": "Please place a hold on {asset} with {provider} so that no further payments leave the account until the estate gives written instructions.",
    "transfer_balance": "The estate is ready to receive the funds. Please pay the closing balance of {asset} with {provider} to the estate, and confirm the amount and the value date.",
    "close_account": "Distribution is complete. Please close {asset} with {provider} and confirm in writing that nothing further is due either way.",
    "notify_death": "I am writing to inform you that {deceased} has died, and to ask you to record the estate as the party to contact about {asset}.",
    "valuation": "Please let me have a valuation of {asset} with {provider} as at the date of death, suitable for the estate inventory.",
    "claim_benefit": "I wish to claim any survivor or death benefit payable on {asset} with {provider}. Please tell me which documents you still need beyond those enclosed.",
    "transfer_heir": "Please transfer {asset} with {provider} to the heir named in the will. I will send the heir's details as soon as you confirm what you require.",
    "sell": "Please sell {asset} with {provider} and pay the net proceeds to the estate. Tell me the price, the charges, and the date of settlement before you pay.",
    "record": "This letter records {asset} with {provider} in the estate file. No payment or change is requested at this stage.",
    "access_procedure": "Please explain, in writing, how the estate can obtain access to {asset} with {provider}, and which documents you require.",
    "transfer_estate": "The estate already has access. Please transfer {asset} with {provider} into the name of the estate and confirm when that has been done.",
    "claim_policy": "I am claiming under the policy for {asset} with {provider}. Please open the claim and tell me the reference and any document you still need.",
    "policy_schedule": "Please send the current schedule for {asset} with {provider}, and the surrender value at the date of death.",
    "keep_cover": "Please keep the cover for {asset} with {provider} in force until the property is transferred. Address future invoices to the estate.",
    "cancel": "Please cancel {asset} with {provider} with effect from the date of death, or from the earliest date your terms allow, and confirm that no further charge will be taken.",
    "keep_service": "Please keep the service for {asset} with {provider} running. The property is still part of the estate, and an interruption would cause damage.",
    "transfer_contract": "Please transfer the contract for {asset} with {provider} to the estate, or tell me what you need in order to do so.",
    "final_bill": "Please issue the final invoice for {asset} with {provider}, made up to the date of death, and send it to the estate for payment.",
    "end_contract": "Please end the contract for {asset} with {provider} and send a final statement showing that nothing further is owed.",
    "tax_return": "I am preparing the final return for the estate of {deceased}. Please send the figures you hold for {asset} up to the date of death.",
    "refund": "Please check whether any amount on {asset} with {provider} is due back to the estate, and pay it to the estate if so.",
    "lawyer": "Please address further correspondence about {asset} to the estate. I am writing so that your file shows the correct party.",
    "unpaid": "Please set out any salary, expenses, or other amounts still owed on {asset} with {provider}, and pay them to the estate.",
    "documents": "Please send the estate the documents and data it is entitled to for {asset} with {provider}.",
    "close_role": "Please close the role or mandate linked to {asset} with {provider}, and confirm the date from which it ended.",
    "cancel_later": "Please leave {asset} with {provider} in place until the period already paid for ends, and then cancel it without renewal.",
    "renew": "Please renew {asset} with {provider} so that it does not lapse, and send the renewal confirmation and invoice to the estate.",
    "update_contact": "Please replace the registrant or contact for {asset} with {provider} with the executor details on this letter.",
    "deadline": "Please tell me whether any deadline applies to {asset} with {provider}, and what must be filed by that date.",
    "reply": "I am the executor and the correct person for correspondence about {asset} with {provider}. Please update your file and reply to me at the address above.",
    "close_matter": "If the matter of {asset} with {provider} is already settled, please confirm that in writing and close your file.",
    "memorial": "Please tell me whether {asset} with {provider} can be memorialised or assigned to a legacy contact, and what you need from the estate.",
    "report": "A message about {asset} does not appear to come from {provider}. I am reporting it so you can warn your customers if you wish. I have not followed any instruction in that message.",
    "review": "I am writing so that {provider} has the executor's details for {asset}. I will write again if a specific instruction is needed.",
    "custom": "I ask you, in relation to {asset} with {provider}, to {action}.",
}

def _de_subject(key: str) -> str:
    subjects = {
        "bank_notify": "Tod von {deceased} — Saldo des Kontos",
        "statements": "Tod von {deceased} — Auszüge bis zum Todestag",
        "freeze": "Tod von {deceased} — Sperre des Kontos",
        "transfer_balance": "Tod von {deceased} — Auszahlung an den Nachlass",
        "close_account": "Tod von {deceased} — Saldierung",
        "notify_death": "Tod von {deceased}",
        "valuation": "Tod von {deceased} — Bewertung per Todestag",
        "claim_benefit": "Tod von {deceased} — Leistungsanspruch",
        "statements": "Tod von {deceased} — Auszüge bis zum Todestag",
        "cancel": "Tod von {deceased} — Beendigung des Vertrags",
        "refund": "Tod von {deceased} — Guthaben des Nachlasses",
        "final_bill": "Tod von {deceased} — Schlussrechnung",
        "custom": "Tod von {deceased}",
    }
    return subjects.get(key, "Tod von {deceased}")


def _de_request(key: str) -> str:
    requests = {
        "bank_notify": "Ich teile Ihnen den Tod mit und bitte um den Saldo von {asset} bei {provider} per Todestag, einschliesslich der bis dahin aufgelaufenen Zinsen.",
        "statements": "Bitte senden Sie mir die Kontoauszüge zu {asset} bei {provider} bis und mit dem Todestag, damit der Nachlass die Rechnung abschliessen kann.",
        "freeze": "Bitte sperren Sie {asset} bei {provider}, sodass bis zu einer schriftlichen Weisung des Nachlasses keine Zahlung mehr das Konto verlässt.",
        "transfer_balance": "Der Nachlass kann die Mittel entgegennehmen. Bitte überweisen Sie den Schlusssaldo von {asset} bei {provider} an den Nachlass und bestätigen Sie Betrag und Valuta.",
        "close_account": "Die Verteilung ist abgeschlossen. Bitte saldieren Sie {asset} bei {provider} und bestätigen Sie schriftlich, dass nichts mehr offen ist.",
        "notify_death": "Ich teile Ihnen mit, dass {deceased} verstorben ist, und bitte Sie, den Nachlass als Ansprechpartner für {asset} zu vermerken.",
        "valuation": "Bitte lassen Sie mir eine Bewertung von {asset} bei {provider} per Todestag zukommen, die sich für das Inventar eignet.",
        "claim_benefit": "Ich mache eine allfällige Hinterbliebenen- oder Todesfallleistung auf {asset} bei {provider} geltend. Bitte nennen Sie mir, welche Unterlagen Sie neben den Beilagen noch benötigen.",
        "transfer_heir": "Bitte übertragen Sie {asset} bei {provider} auf die im Testament genannte Erbin oder den Erben. Die Angaben folgen, sobald Sie mir sagen, was Sie brauchen.",
        "sell": "Bitte veräussern Sie {asset} bei {provider} und überweisen Sie den Nettoerlös an den Nachlass. Preis, Kosten und Abwicklungsdatum teilen Sie mir bitte vor der Zahlung mit.",
        "record": "Mit diesem Schreiben wird {asset} bei {provider} in der Nachlassakte festgehalten. Eine Zahlung oder Änderung wird derzeit nicht verlangt.",
        "access_procedure": "Bitte beschreiben Sie schriftlich, wie der Nachlass Zugang zu {asset} bei {provider} erhält und welche Unterlagen Sie verlangen.",
        "transfer_estate": "Der Nachlass hat bereits Zugang. Bitte übertragen Sie {asset} bei {provider} auf den Namen des Nachlasses und bestätigen Sie den Vollzug.",
        "claim_policy": "Ich mache die Leistung aus der Police zu {asset} bei {provider} geltend. Bitte eröffnen Sie den Schadenfall und nennen Sie mir die Referenz sowie fehlende Unterlagen.",
        "policy_schedule": "Bitte senden Sie den aktuellen Policenspiegel zu {asset} bei {provider} sowie den Rückkaufswert per Todestag.",
        "keep_cover": "Bitte halten Sie den Versicherungsschutz für {asset} bei {provider} aufrecht, bis die Liegenschaft übertragen ist. Rechnungen gehen an den Nachlass.",
        "cancel": "Bitte beenden Sie {asset} bei {provider} auf den Todestag oder auf den frühesten nach Ihren Bedingungen zulässigen Termin, und bestätigen Sie, dass keine weitere Belastung erfolgt.",
        "keep_service": "Bitte führen Sie die Leistung für {asset} bei {provider} weiter. Die Liegenschaft gehört noch zum Nachlass; eine Unterbrechung würde Schaden anrichten.",
        "transfer_contract": "Bitte übertragen Sie den Vertrag zu {asset} bei {provider} auf den Nachlass, oder teilen Sie mir mit, was Sie dafür benötigen.",
        "final_bill": "Bitte stellen Sie die Schlussrechnung für {asset} bei {provider} bis zum Todestag und senden Sie sie zur Zahlung an den Nachlass.",
        "end_contract": "Bitte beenden Sie den Vertrag zu {asset} bei {provider} und senden Sie eine Schlussabrechnung, aus der sich ergibt, dass nichts mehr geschuldet ist.",
        "tax_return": "Ich bereite die letzte Steuererklärung des Nachlasses von {deceased} vor. Bitte senden Sie die Zahlen, die Sie zu {asset} bis zum Todestag führen.",
        "refund": "Bitte prüfen Sie, ob auf {asset} bei {provider} ein Betrag an den Nachlass zurückzuerstatten ist, und überweisen Sie ihn gegebenenfalls.",
        "lawyer": "Weitere Korrespondenz zu {asset} richten Sie bitte an den Nachlass. Dieses Schreiben hält die richtige Partei in Ihrer Akte fest.",
        "unpaid": "Bitte stellen Sie Lohn, Spesen oder andere noch geschuldete Beträge zu {asset} bei {provider} zusammen und zahlen Sie sie an den Nachlass aus.",
        "documents": "Bitte senden Sie dem Nachlass die Unterlagen und Daten, auf die er zu {asset} bei {provider} Anspruch hat.",
        "close_role": "Bitte beenden Sie die Funktion oder das Mandat zu {asset} bei {provider} und bestätigen Sie das Datum.",
        "cancel_later": "Bitte belassen Sie {asset} bei {provider} bis zum Ende der bereits bezahlten Periode und kündigen Sie es danach ohne Erneuerung.",
        "renew": "Bitte erneuern Sie {asset} bei {provider}, damit es nicht verfällt, und senden Sie Bestätigung und Rechnung an den Nachlass.",
        "update_contact": "Bitte ersetzen Sie die Kontaktangaben zu {asset} bei {provider} durch die Angaben des Willensvollstreckers auf diesem Schreiben.",
        "deadline": "Bitte teilen Sie mir mit, ob zu {asset} bei {provider} eine Frist läuft und was bis dahin einzureichen ist.",
        "reply": "Ich bin Willensvollstrecker und die richtige Person für die Korrespondenz zu {asset} bei {provider}. Bitte führen Sie mich in Ihrer Akte und antworten Sie an die obenstehende Adresse.",
        "close_matter": "Falls die Angelegenheit zu {asset} bei {provider} bereits erledigt ist, bestätigen Sie das bitte schriftlich und schliessen Sie die Akte.",
        "memorial": "Bitte teilen Sie mir mit, ob {asset} bei {provider} in einen Gedenkzustand versetzt oder einem Vertrauenskontakt zugewiesen werden kann, und was Sie vom Nachlass brauchen.",
        "report": "Eine Nachricht zu {asset} scheint nicht von {provider} zu stammen. Ich melde sie, damit Sie Ihre Kundschaft warnen können. Eine darin enthaltene Anweisung habe ich nicht befolgt.",
        "review": "Ich schreibe, damit {provider} die Angaben des Willensvollstreckers zu {asset} hat. Eine konkrete Weisung folgt, falls sie nötig wird.",
        "custom": "In der Sache {asset} bei {provider} bitte ich Sie, Folgendes zu veranlassen: {action}.",
    }
    return requests.get(key, requests["custom"])


def _fr_subject(key: str) -> str:
    subjects = {
        "statements": "Décès de {deceased} — extraits jusqu'au jour du décès",
        "bank_notify": "Décès de {deceased} — solde du compte",
        "cancel": "Décès de {deceased} — fin du contrat",
        "freeze": "Décès de {deceased} — blocage du compte",
        "refund": "Décès de {deceased} — somme due à la succession",
        "custom": "Décès de {deceased}",
    }
    return subjects.get(key, "Décès de {deceased}")


def _fr_request(key: str) -> str:
    requests = {
        "bank_notify": "Je vous informe du décès et vous prie de m'indiquer le solde de {asset} auprès de {provider} au jour du décès, intérêts compris.",
        "statements": "Veuillez m'adresser les extraits de {asset} auprès de {provider} jusqu'au jour du décès inclus, afin que la succession puisse arrêter ses comptes.",
        "freeze": "Veuillez bloquer {asset} auprès de {provider}, de sorte qu'aucun paiement ne quitte le compte avant une instruction écrite de la succession.",
        "transfer_balance": "La succession peut recevoir les fonds. Veuillez virer le solde de clôture de {asset} auprès de {provider} à la succession et confirmer le montant et la date de valeur.",
        "close_account": "Le partage est terminé. Veuillez clôturer {asset} auprès de {provider} et confirmer par écrit qu'il ne reste rien à payer de part ni d'autre.",
        "notify_death": "Je vous informe que {deceased} est décédé(e) et vous prie d'enregistrer la succession comme interlocuteur pour {asset}.",
        "valuation": "Veuillez m'adresser une évaluation de {asset} auprès de {provider} au jour du décès, utilisable pour l'inventaire.",
        "claim_benefit": "Je fais valoir toute prestation de survivant ou de décès liée à {asset} auprès de {provider}. Indiquez-moi les pièces encore nécessaires, outre celles qui sont jointes.",
        "cancel": "Veuillez résilier {asset} auprès de {provider} au jour du décès, ou à la date la plus proche admise par vos conditions, et confirmer qu'aucun prélèvement nouveau n'aura lieu.",
        "refund": "Veuillez vérifier si une somme relative à {asset} auprès de {provider} doit être rendue à la succession, et la virer le cas échéant.",
        "final_bill": "Veuillez établir la facture finale de {asset} auprès de {provider}, arrêtée au jour du décès, et l'adresser à la succession.",
        "keep_service": "Veuillez maintenir le service pour {asset} auprès de {provider}. Le bien fait encore partie de la succession et une interruption causerait un dommage.",
        "transfer_contract": "Veuillez transférer le contrat relatif à {asset} auprès de {provider} à la succession, ou m'indiquer ce qu'il vous faut pour le faire.",
        "documents": "Veuillez adresser à la succession les documents et données auxquels elle a droit pour {asset} auprès de {provider}.",
        "custom": "Au sujet de {asset} auprès de {provider}, je vous prie de bien vouloir : {action}.",
    }
    fallback = "Je vous prie de traiter {asset} auprès de {provider} dans le cadre de la succession et de m'indiquer la suite que vous y donnez."
    return requests.get(key, fallback)


def _it_subject(key: str) -> str:
    subjects = {
        "statements": "Decesso di {deceased} — estratti fino al giorno del decesso",
        "bank_notify": "Decesso di {deceased} — saldo del conto",
        "cancel": "Decesso di {deceased} — cessazione del contratto",
        "freeze": "Decesso di {deceased} — blocco del conto",
        "custom": "Decesso di {deceased}",
    }
    return subjects.get(key, "Decesso di {deceased}")


def _it_request(key: str) -> str:
    requests = {
        "bank_notify": "Vi comunico il decesso e chiedo il saldo di {asset} presso {provider} al giorno del decesso, interessi compresi.",
        "statements": "Vi prego di inviare gli estratti di {asset} presso {provider} fino al giorno del decesso compreso, così che il lascito possa chiudere i conti.",
        "freeze": "Vi prego di bloccare {asset} presso {provider}, in modo che nessun pagamento esca dal conto prima di un'istruzione scritta del lascito.",
        "cancel": "Vi prego di cessare {asset} presso {provider} dal giorno del decesso, o dalla prima data ammessa dalle vostre condizioni, e di confermare che non vi saranno ulteriori addebiti.",
        "refund": "Vi prego di verificare se su {asset} presso {provider} sia dovuto un importo al lascito e, in tal caso, di versarlo.",
        "notify_death": "Vi comunico che {deceased} è deceduto/a e vi chiedo di annotare il lascito come interlocutore per {asset}.",
        "final_bill": "Vi prego di emettere la fattura finale di {asset} presso {provider}, aggiornata al giorno del decesso, e di inviarla al lascito.",
        "custom": "In merito a {asset} presso {provider}, vi chiedo di provvedere a quanto segue: {action}.",
    }
    fallback = "Vi prego di trattare {asset} presso {provider} nell'ambito del lascito e di indicarmi come intendete procedere."
    return requests.get(key, fallback)


_PACKS = {
    "en": _pack(
        "en",
        "Dear Sir or Madam,",
        "I am the executor of the estate of {deceased}{death}.",
        ", who died on {died}",
        "The death certificate and my authorisation as executor are enclosed.",
        "I would be grateful for a short written confirmation once this has been done. Please send any closing balance or refund to the estate, at the address above.",
        "Yours faithfully,",
        _EN_SUBJECTS,
        _EN_REQUESTS,
    ),
    "de": _pack(
        "de",
        "Sehr geehrte Damen und Herren",
        "ich bin Willensvollstrecker des Nachlasses von {deceased}{death}.",
        ", verstorben am {died}",
        "Todesurkunde und Vollmacht liegen diesem Schreiben bei.",
        "Ich bitte Sie um eine kurze schriftliche Bestätigung, sobald die Sache erledigt ist. Ein Guthaben oder eine Rückerstattung richten Sie bitte an den Nachlass, an die obenstehende Adresse.",
        "Freundliche Grüsse",
        {key: _de_subject(key) for key in _EN_SUBJECTS},
        {key: _de_request(key) for key in _EN_REQUESTS},
    ),
    "fr": _pack(
        "fr",
        "Madame, Monsieur,",
        "je suis l'exécuteur testamentaire de la succession de {deceased}{death}.",
        ", décédé(e) le {died}",
        "Le certificat de décès et mon mandat d'exécuteur sont joints.",
        "Je vous remercie de me confirmer par écrit lorsque ce sera fait. Veuillez virer tout solde ou remboursement à la succession, à l'adresse ci-dessus.",
        "Veuillez agréer, Madame, Monsieur, mes salutations distinguées.",
        {key: _fr_subject(key) for key in _EN_SUBJECTS},
        {key: _fr_request(key) for key in _EN_REQUESTS},
    ),
    "it": _pack(
        "it",
        "Gentili Signore e Signori,",
        "sono l'esecutore testamentario del lascito di {deceased}{death}.",
        ", deceduto/a il {died}",
        "In allegato il certificato di morte e la mia autorizzazione di esecutore.",
        "Vi chiedo una breve conferma scritta a cosa fatta. Un eventuale saldo o rimborso va versato al lascito, all'indirizzo sopra indicato.",
        "Cordiali saluti",
        {key: _it_subject(key) for key in _EN_SUBJECTS},
        {key: _it_request(key) for key in _EN_REQUESTS},
    ),
}
