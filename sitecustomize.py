"""Enable coverage instrumentation in subprocess test runners.

CLI test helpers set `PYTHONPATH=REPO_ROOT` and pass the parent process
environment through. During pytest-cov runs, coverage.py's subprocess patch
adds serialized startup config to that environment. Python imports a
`sitecustomize` module from any directory on sys.path during interpreter
startup, so placing this file at the repo root - the same directory
PYTHONPATH points at - makes it run before the script's `main()`.
`coverage.process_startup()` is a no-op unless coverage startup config is
present, so this file has no effect outside of test runs.
"""

try:
    import coverage

    coverage.process_startup()
except ImportError:  # pragma: no cover
    pass
