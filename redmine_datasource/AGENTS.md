# Repository Guidelines

## Project Structure & Module Organization
Runtime code lives in `datasources/redmine_datasource.py`; `RedmineDatasourceDataSource` is the hook for retrieving Redmine content. `main.py` only boots the Dify runtime. Update `manifest.yaml` when you change metadata, resource needs, or entry points so Dify can load the plugin accurately. Put icons and other static assets in `_assets/`, and keep contributor docs as Markdown at the repository root. Add helper modules under `datasources/` or a sibling folder (such as `services/`) to keep responsibilities focused.

## Build, Test, and Development Commands
Create an isolated environment before developing:
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Run the plugin locally with `python main.py`; this starts the Dify harness and is the fastest way to verify credential handling. When tests exist, run them with `pytest -q` (see Testing Guidelines) before opening a pull request.

## Coding Style & Naming Conventions
Target Python 3.12 and PEP 8: four-space indentation, lowercase_with_underscores for functions and variables, CapWords for classes. Use explicit type hints (`dict[str, Any]`) and the module-level `logger` for observability. Keep methods short and return typed `Generator` or `Datasource*` objects as required by the `dify_plugin` API, and align file names with their primary class (`redmine_datasource.py` → `RedmineDatasourceDataSource`).

## Testing Guidelines
Adopt `pytest` for unit and integration coverage. Place tests in a `tests/` directory that mirrors the source layout (`tests/datasources/test_redmine_datasource.py`). Name files `test_*.py`, keep fixtures small, and stub network calls to Redmine so suites stay deterministic. Run `pytest -q` locally and attach output from failing tests when you need review help.

## Commit & Pull Request Guidelines
Existing history favors concise, imperative titles (“Add textile2html.py”). Keep subject lines ≤50 characters, explain the “why” in the body, and reference issues using `Refs #123` when relevant. For pull requests, include a summary of behavior changes, test evidence (`pytest -q`, manual `python main.py` run), configuration updates (for example new manifest fields), and screenshots for UI-facing assets. Open drafts early to invite feedback, and request review only after local checks pass.

## Security & Configuration Tips
Never commit real Redmine credentials; rely on the Dify secrets manager. Validate user-supplied URLs with `urllib.parse` helpers already imported in the datasource module. Document new configuration keys in code comments and PR descriptions so operators can update their environments safely.
