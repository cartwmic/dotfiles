"""The work-profile op shim (.chezmoitemplates/op-shim-service-account, the shim as it was before 1Password Connect routing) passes
the same black-box suite as the personal one: test_op_shim.py's class, run against the other file.

    python3 -m unittest discover -s tests/pi-op-shim -p 'test_op_shim_service_account.py' -v
"""
import unittest

import test_op_shim as base
from connect_support import SA_SHIM


class ServiceAccountShim(base.OpShim):
    shim_source = SA_SHIM


if __name__ == "__main__":
    unittest.main()
