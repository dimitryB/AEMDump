# Contributing

## Getting Started

1. Fork the repository.
2. Create a branch for your change.
3. Install dependencies with `pip install -r requirements.txt`.
4. Run a quick validation:
   - `python3 -m py_compile aem_export.py`
   - `python3 aem_export.py --help`
   - `python3 -m unittest discover -s tests -v`
5. Open a pull request with a clear description and testing notes.

## Pull Request Guidelines

- Keep changes focused and small.
- Include rationale for behavior changes.
- Update README when user-facing behavior changes.
- Avoid introducing breaking CLI changes without discussion.

## Reporting Issues

Please include:

- Python version
- Command used
- Relevant logs (remove secrets)
- Expected vs actual behavior
