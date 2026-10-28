# Contributing

Issues and PRs are welcome.

- **Bugs:** open an issue with steps to reproduce, which scorer you use (Jev or LLM, and which model), and the worker logs.
- **Lead quality:** examples of missed leads or false positives help most. Include the post link, the project's keywords, and the similarity and score shown.
- **PRs:** keep them focused. Run `python -m backend.app.worker --once --dry-run` and `cd web && npm run build` before submitting.
- **Style:** match the surrounding code. Python is plain functions and small modules. Don't add docstrings or comments unless the logic isn't obvious.

By contributing, you agree your contributions are licensed under AGPL-3.0.
