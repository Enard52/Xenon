"""Allow ``python -m xenon`` to launch the CLI.

A PATH-independent entry point: on Windows the ``xenon.exe`` console script
may be installed into a ``Scripts`` directory that is not on ``PATH`` (see
issue #110), so ``python -m xenon`` is the reliable fallback.
"""

from xenon.main import cli

if __name__ == "__main__":
    cli()
