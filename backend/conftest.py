from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _stop_started_patches():
    """Tests may start a patch without a context manager (see
    apps.finance.testing_helpers.seed_net_profit); make sure none leaks."""
    yield
    mock.patch.stopall()
