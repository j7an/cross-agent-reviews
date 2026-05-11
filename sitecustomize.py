"""Enable coverage instrumentation in subprocess test runners.

CLI test helpers set `PYTHONPATH=REPO_ROOT` and pass the parent process
environment through (which carries pytest-cov's `COVERAGE_PROCESS_START`
variable). Python imports a `sitecustomize` module from any directory on
sys.path during interpreter startup, so placing this file at the repo root
— the same directory PYTHONPATH points at — makes it run before the
script's `main()`. `coverage.process_startup()` is a no-op unless
`COVERAGE_PROCESS_START` is set, so this file has no effect outside of
test runs.
"""

try:
    import coverage

    coverage.process_startup()
except ImportError:  # pragma: no cover
    pass
