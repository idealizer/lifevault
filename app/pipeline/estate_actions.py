"""Next steps an executor can take for a confirmed asset of a deceased person."""

from __future__ import annotations

import json
import re

from app.categories import CATEGORY_KEYS

ESTATE_ACTIONS: dict[str, list[str]] = {
    "banking": [
        "Notify the bank of the death and request the balance",
        "Ask for statements up to the date of death",
        "Freeze the account until the estate is ready",
        "Move the balance to the estate account",
        "Close the account after distribution",
    ],
    "investments_pensions": [
        "Notify the provider of the death",
        "Request a valuation at the date of death",
        "Claim a survivor or death benefit",
        "Transfer the holding to the heir named in the will",
        "Sell the holding and pay the proceeds to the estate",
    ],
    "crypto": [
        "Record the exchange or wallet in the estate inventory",
        "Notify the exchange of the death",
        "Ask the exchange for the estate-access procedure",
        "Transfer the holding to the estate if access already exists",
        "Leave the holding documented until access is found",
    ],
    "insurance": [
        "Notify the insurer of the death",
        "File a claim on the policy",
        "Ask for the policy schedule and surrender value",
        "Keep cover on estate property until it is transferred",
        "Cancel cover that is no longer needed",
    ],
    "property_utilities": [
        "Notify the provider of the death",
        "Keep the service running for the property",
        "Transfer the contract to the heir or estate",
        "Settle the final bill",
        "End the contract",
    ],
    "tax_government": [
        "Tell the authority that the person has died",
        "Include the item in the estate filing",
        "File the final tax return",
        "Claim a refund owed to the estate",
        "Send the notice to the estate lawyer",
    ],
    "employment_business": [
        "Notify the employer of the death",
        "Claim unpaid salary or expenses",
        "Ask about a death-in-service benefit",
        "Collect employment documents for the estate",
        "Close the business role or mandate",
    ],
    "subscriptions": [
        "Cancel the subscription",
        "Settle the final invoice",
        "Check whether a refund is due",
        "Transfer the subscription if the provider allows it",
        "Leave it until the paid period ends, then cancel",
    ],
    "domains_hosting": [
        "Renew the domain so it does not expire",
        "Transfer the domain to the heir or estate",
        "Update the registrant contact",
        "Download site or mailbox data the estate needs",
        "Cancel hosting after the content is saved",
    ],
    "legal": [
        "Send the document to the estate lawyer",
        "Keep the document in the estate file",
        "Check whether a deadline applies",
        "Reply to the sender as executor",
        "Close the matter if it is already settled",
    ],
    "online_accounts": [
        "Ask the provider to close the account",
        "Ask the provider about a memorial or legacy contact",
        "Download data the estate is entitled to",
        "Recover the account only if the estate already has access",
        "Leave the account documented and take no login attempt",
    ],
    "risks": [
        "Do not reply to the sender",
        "Record it as a likely impersonation",
        "Report it to the real institution",
        "Ignore it after it is noted in the file",
        "Ask the estate lawyer before any response",
    ],
    "other": [
        "Review what the estate should do with it",
        "Contact the provider as executor",
        "Keep it in the inventory until more evidence appears",
        "Transfer it to an heir",
        "Close it",
    ],
}

PROPOSAL_PROMPT = """You help an estate executor choose the next administrative step for each confirmed asset of a deceased person.
For every asset, choose exactly one action from that asset's allowed list. Do not invent an action.
Return JSON only: {"proposals":[{"id":1,"action":"exact list text","reason":"one short sentence"}]}"""


def actions_for(category: str) -> list[str]:
    if category not in CATEGORY_KEYS:
        category = "other"
    return list(ESTATE_ACTIONS.get(category) or ESTATE_ACTIONS["other"])


def parse_proposals(text: str, allowed: dict[int, list[str]]) -> dict[int, tuple[str, str]]:
    payload = _load(text)
    rows = []
    if isinstance(payload, dict):
        rows = payload.get("proposals") or payload.get("actions") or []
    chosen: dict[int, tuple[str, str]] = {}
    if not isinstance(rows, list):
        return chosen
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            finding_id = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        options = allowed.get(finding_id)
        if not options:
            continue
        action = str(row.get("action") or "").strip()
        if action not in options:
            continue
        reason = re.sub(r"\s+", " ", str(row.get("reason") or "")).strip()[:400]
        chosen[finding_id] = (action, reason)
    return chosen


def proposal_prompt(findings: list[dict]) -> str:
    blocks = []
    for finding in findings:
        options = actions_for(finding["category"])
        lines = "\n".join(f"- {option}" for option in options)
        blocks.append(
            "\n".join(
                [
                    f'Asset id={finding["id"]}',
                    f'Category: {finding["category"]}',
                    f'Label: {finding.get("label") or ""}',
                    f'Provider: {finding.get("provider") or ""}',
                    f'Kind: {finding.get("asset_kind") or ""}',
                    "Allowed actions:",
                    lines,
                ]
            )
        )
    return "Choose one allowed action for each asset.\n\n" + "\n\n".join(blocks)


def propose_confirmed() -> int:
    from app.db import list_findings, save_proposal
    from app.llm.client import complete

    findings = [row for row in list_findings("confirmed") if row.get("action_status") != "accepted"]
    if not findings:
        return 0
    text, _used = complete(proposal_prompt(findings), system=PROPOSAL_PROMPT)
    allowed = {row["id"]: actions_for(row["category"]) for row in findings}
    chosen = parse_proposals(text, allowed)
    for row in findings:
        action, reason = chosen.get(row["id"]) or (
            allowed[row["id"]][0],
            "Listed first until the model returns one of the allowed steps.",
        )
        save_proposal(row["id"], action, reason)
    return len(findings)


def _load(text: str):
    raw = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
