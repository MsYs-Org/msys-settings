"""MSYS Settings application.

The package deliberately depends only on Python's standard library and the
language-neutral mIPC wire protocol.  It does not import ``msys_core`` or a
Python-only system service API.
"""

from .client import SettingsClient
from .model import OperationResult, SettingsModel

__all__ = ["OperationResult", "SettingsClient", "SettingsModel"]
__version__ = "0.2.11"
