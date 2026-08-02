"""
Platform adapter selector.
Import `Adapter` and instantiate it — you get the right implementation
for the current OS without any conditional imports at the call site.
"""
import sys

if sys.platform == 'darwin':
    from .macos import MacOSAdapter as Adapter
elif sys.platform == 'win32':
    from .windows import WindowsAdapter as Adapter
else:
    raise RuntimeError(f'Unsupported platform: {sys.platform}')

__all__ = ['Adapter']
