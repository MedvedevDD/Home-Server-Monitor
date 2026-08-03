# Contributing

## Release policy

- Patch releases contain fixes, tests, and documentation.
- Minor releases add providers or user-visible features.
- Breaking architecture changes require a major release.

## Required checks

Before packaging a release, run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m py_compile collector.py hsm.py config.py metric.py
sh -n install.sh
sh -n update.sh
```

Validate every JSON file under `dashboard/` with a JSON parser.
Do not include `__pycache__`, `.pyc`, local reports, or secrets in release archives.

## Bug workflow

1. Add a regression test reproducing the issue.
2. Confirm that the test fails.
3. Fix the implementation.
4. Confirm all tests pass.
5. Update `CHANGELOG.md`.
