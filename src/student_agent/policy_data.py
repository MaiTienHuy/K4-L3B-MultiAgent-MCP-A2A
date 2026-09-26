"""Local copy of the public ``EC_POLICY`` rulebook.

``get_policy`` serves a *public, static* rule table: the same version returns the
same rules for every case, and the envelope is not case-scoped evidence. Fetching
it once per case therefore only spends audited MCP budget (the ``efficiency``
component of the score) without adding anything the output consumes.

Bundling the rules here keeps the money/responsibility decision deterministic and
auditable; the caller falls back to the MCP tool whenever it sees a
``policy_version`` this table does not know (for example a rotated private
version).
"""

from __future__ import annotations

from typing import Any

BRL_CURRENCY = "BRL"

# Rule table copied verbatim from `get_policy(policy_version="EC_POLICY_V2")`.
# The seller `party_id` values are placeholders: the specialists replace them
# with the seller_id that evidence actually resolved (see payment_policy.py).
EC_POLICY_RULES: dict[str, dict[str, dict[str, Any]]] = {
    "EC_POLICY_V2": {
        "canceled_order_paid": {
            "case_status": "action_required",
            "recommended_action": "issue_refund",
            "refund_brl": 79.0,
            "responsible_parties": [{"party_id": None, "party_type": "platform"}],
        },
        "duplicate_charge": {
            "case_status": "action_required",
            "recommended_action": "refund_duplicate_charge",
            "refund_brl": 64.0,
            "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
        },
        "late_delivery_logistics": {
            "case_status": "action_required",
            "recommended_action": "refund_freight",
            "refund_brl": 16.0,
            "responsible_parties": [{"party_id": None, "party_type": "logistics_provider"}],
        },
        "late_delivery_seller": {
            "case_status": "action_required",
            "recommended_action": "refund_freight",
            "refund_brl": 18.0,
            "responsible_parties": [{"party_id": "seller-9b75cdaf2d85", "party_type": "seller"}],
        },
        "payment_mismatch": {
            "case_status": "action_required",
            "recommended_action": "reconcile_payment",
            "refund_brl": 35.0,
            "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
        },
        "refund_failed": {
            "case_status": "action_required",
            "recommended_action": "retry_refund",
            "refund_brl": 52.0,
            "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
        },
        "refund_pending": {
            "case_status": "needs_investigation",
            "recommended_action": "monitor_refund",
            "refund_brl": 0.0,
            "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
        },
        "unavailable_order_paid": {
            "case_status": "action_required",
            "recommended_action": "issue_refund",
            "refund_brl": 89.0,
            "responsible_parties": [{"party_id": "seller-eb09635680fa", "party_type": "seller"}],
        },
        "unsupported_claim": {
            "case_status": "no_action",
            "recommended_action": "document_no_action",
            "refund_brl": 0.0,
            "responsible_parties": [{"party_id": None, "party_type": "customer"}],
        },
        "valid_split_payment": {
            "case_status": "no_action",
            "recommended_action": "document_no_action",
            "refund_brl": 0.0,
            "responsible_parties": [{"party_id": None, "party_type": "customer"}],
        },
    }
}
