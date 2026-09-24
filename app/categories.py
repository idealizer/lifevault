"""Asset categories shown in the inventory."""

CATEGORIES: list[tuple[str, str]] = [
    ("banking", "Banking"),
    ("investments_pensions", "Investments and pensions"),
    ("crypto", "Crypto"),
    ("insurance", "Insurance"),
    ("property_utilities", "Property and utilities"),
    ("tax_government", "Tax and government"),
    ("employment_business", "Employment and business"),
    ("subscriptions", "Subscriptions"),
    ("domains_hosting", "Domains and hosting"),
    ("legal", "Legal"),
    ("online_accounts", "Online accounts"),
    ("risks", "Risks"),
    ("other", "Other"),
]

CATEGORY_KEYS = {key for key, _label in CATEGORIES}
CATEGORY_LABELS = dict(CATEGORIES)

CATEGORY_ICONS = {
    "banking": "M4 10h16M4 10V19h16V10M8 19v-5h8v5M12 3 4 10h16L12 3Z",
    "investments_pensions": "M4 19V5M4 19h16M8 15l3-4 3 2 4-6",
    "crypto": "M12 3v18M8 7c2-2 8-2 8 2s-6 3-8 4-2 4 2 5 6 0 6-2",
    "insurance": "M12 3 5 6v5c0 4 3 7 7 8 4-1 7-4 7-8V6l-7-3Z",
    "property_utilities": "M4 11 12 4l8 7M6 10v9h12v-9",
    "tax_government": "M7 3h7l5 5v13H7V3ZM14 3v5h5M9 13h6M9 17h6",
    "employment_business": "M8 7V5h8v2M4 7h16v12H4V7Z",
    "subscriptions": "M20 12a8 8 0 1 1-2.3-5.7M20 4v4h-4",
    "domains_hosting": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3c2 2.5 3 5.5 3 9s-1 6.5-3 9c-2-2.5-3-5.5-3-9s1-6.5 3-9Z",
    "legal": "M12 3v18M8 7h8M5 10l3 7h-6l3-7ZM19 10l3 7h-6l3-7Z",
    "online_accounts": "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM5 20c1.5-3 4-4.5 7-4.5S17.5 17 19 20",
    "risks": "M12 3 2 20h20L12 3ZM12 10v4M12 17h.01",
    "other": "M4 7h16v12H4V7ZM4 7l8 6 8-6",
}
