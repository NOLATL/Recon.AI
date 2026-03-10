"""
API-level test fixtures.

Provides an autouse mock for OpenAIClient so Phase 6 integration tests
run without a real OPENAI_API_KEY. The mock returns a deterministic
GL004↔SUB004 suggestion — matching the designed test data used across
Phase 6, 6A, 7, and 8 integration tests.
"""

import pytest
from unittest.mock import MagicMock, patch


_PATCH = "src.services.ai_matching_service.OpenAIClient"

# Fixed suggestion that matches the Phase 6 test fixture (GL004 / SUB004,
# AI_ENTITY, Delta Vendor — designed to be left unmatched by prior phases).
_STUB_RESPONSE = {
    "matches": [
        {
            "gl_ids":     ["GL004"],
            "sub_ids":    ["SUB004"],
            "confidence": 0.90,
            "reasoning":  "Same vendor and entity; amount difference is a likely accrual adjustment.",
        }
    ]
}


@pytest.fixture(autouse=True)
def mock_openai_client():
    """
    Patch OpenAIClient for every test in tests/test_api/.
    Returns the fixed stub response regardless of which (entity, vendor) group
    is being evaluated — safe because the designed test data leaves only
    GL004/SUB004 (AI_ENTITY, delta vendor) in the residual pool by Phase 6.
    """
    mock_inst = MagicMock()
    mock_inst.generate_json.return_value = _STUB_RESPONSE
    with patch(_PATCH, return_value=mock_inst):
        yield mock_inst
