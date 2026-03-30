
from typing import Dict, Any


def create_runtime(session_id: str) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "current_state": "initialized",
        "raw_data": {
            "chart_of_accounts": None,
            "gl": None,
            "subledger": None,
        },
        "clean_data": {},
        "vendor_normalization_map": [],
        "profiling": {},
        "preprocessing": {},
        "probabilistic": {},
        "ai_suggested_meta": {},
        "consolidation": {},
        "manual_overrides": {},
        "manual_rejected": [],
        "export": {},
        "matching": {
            "deterministic": [],
            "probabilistic": [],
            "ai_suggested": [],
            "final": [],
            "rejected": [],
        },
        "residual_pool": {},
        "snapshots": {},
        "config": {
            "weights": {},
            "threshold": None,
            "ai_model": None,
            "vendor_nlp_threshold": 0.90,
            "alias_map": {},
            "alias_version": "v1.0.0",
            "column_map": {
                "side_a_label": "GL",
                "side_b_label": "Subledger",
                "side_a": {
                    "id": "gl_id",
                    "vendor": "vendor_name",
                    "amount": "amount",
                    "date": "transaction_date",
                    "entity": "entity",
                    "currency": "currency",
                },
                "side_b": {
                    "id": "subledger_id",
                    "vendor": "vendor_name",
                    "amount": "amount",
                    "date": "transaction_date",
                    "entity": "entity",
                    "currency": "currency",
                },
            },
            "matching_config": {
                "deterministic": [],
                "probabilistic": {},
            },
        },
    }
