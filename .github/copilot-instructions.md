# GitHub Copilot Instructions for Tesla Order Status

You are an expert Python developer specializing in FastAPI, Docker, and clean code practices. This project uses strict linting and formatting rules. Follow these instructions for all code generation.

## Tech Stack
- **Language**: Python 3.11+
- **Framework**: FastAPI
- **Package Manager**: Poetry
- **Containerization**: Docker, Docker Compose
- **Frontend**: Jinja2 Templates + Vanilla JavaScript

## Coding Standards & Style

### Python
- **Formatting**: Strictly follow **Black** formatting rules.
  - Line length: 88 characters.
  - Double quotes for strings.
- **Imports**: Sort imports using **isort** rules.
  - Standard library -> Third party -> Local application.
- **Typing**: All function signatures must have type hints.
  - Use `typing` module or standard collection types (e.g., `list[str]`, `dict[str, Any]`).
  - Code must pass **MyPy** strict mode.
- **Linting**: Code must be free of **Flake8** and **Pylint** errors.
  - No unused imports or variables.
  - Handle exceptions specifically; avoid bare `except:`.
- **Docstrings**: Include docstrings for all public modules, classes, and functions.
  - Prefer Google-style docstrings.

### JavaScript
- Use modern ES6+ syntax.
- Prefer `const` and `let` over `var`.
- Ensure code passes standard JS linters (ESLint).

## Project Structure
- `app/`: Main application source code.
  - `main.py`: Application entry point and route definitions.
  - `utils.py`: Utility functions (keep `main.py` clean).
  - `constants.py`: Configuration and constant values.
  - `templates/`: HTML templates (Jinja2).
  - `static/`: Static assets (CSS, JS, Images).
- `scripts/`: Helper scripts (e.g., `run_super_linter.py`).

## Best Practices
1. **Refactoring**: When modifying existing files, look for opportunities to extract logic into `utils.py` to avoid code duplication (JSCPD is active).
2. **Configuration**: Do not hardcode secrets or configuration. Use environment variables.
3. **Error Handling**: Use FastAPI's exception handling mechanisms. Return appropriate HTTP status codes.
4. **Testing/Validation**:
    - Before finalizing code, ensure it would pass the project's linter suite.
    - Run `poetry run python scripts/run_super_linter.py` to validate changes if asked.

## Specific Instructions
- When generating HTML, ensure it is responsive and accessible.
- When writing Pydantic models, use `Field` for validation and documentation.
- If you encounter complex logic in `main.py`, suggest moving it to a dedicated service or utility module.
