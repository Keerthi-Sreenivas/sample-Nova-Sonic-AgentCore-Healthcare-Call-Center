"""Test setup: make backend importable and stub optional runtime deps."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import strands  # noqa: F401
except ImportError:
    stub = types.ModuleType("strands")
    stub.tool = lambda f: f
    sys.modules["strands"] = stub

try:
    import boto3  # noqa: F401
except ImportError:
    boto = types.ModuleType("boto3")
    boto.client = boto.resource = lambda *a, **k: None
    sys.modules["boto3"] = boto

try:
    import botocore  # noqa: F401
except ImportError:
    bc = types.ModuleType("botocore")
    exc = types.ModuleType("botocore.exceptions")

    class ClientError(Exception):
        pass

    exc.ClientError = ClientError
    bc.exceptions = exc
    sys.modules["botocore"] = bc
    sys.modules["botocore.exceptions"] = exc
