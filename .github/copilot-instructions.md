# Copilot Instructions for Anemone

## Project Overview

Anemone is a modular, context-aware NLP and natural code engine written in Python. It provides subject-specific blending, algebraic solving, and natural language processing capabilities.

## Repository Structure

- `eng1neer.py` / `eng1neer_patch.py` – Main code/definition engine
- `new_natural_code_engine.py` – Natural language code engine logic
- `nerve_center.py` – Session and conjecture management
- `taxonomic_grammar.py` – Taxonomic grammar analysis
- `shell.py` – Interactive shell entry point
- `main.py` – Main entry point
- `data/` – Definitions and domain data (JSON files)
- `tests/` – Unit tests (Python `unittest`)
- `requirements.txt` – Python dependencies
- `setup.py` – Package setup/install script
- `docs/` – Documentation

## Setup & Installation

```sh
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
pip install .
```

## Running Tests

Tests are located in the `tests/` directory and use Python's built-in `unittest` framework. Run with either:

```sh
python -m unittest discover tests/
# or, if pytest is installed:
python -m pytest tests/
```

Always run the full test suite before committing changes.

## Code Quality Guidelines

- **Do not introduce broken code into the repository without first notifying the user.** If a change may break existing functionality or tests, explain the issue clearly before proceeding.
- Keep changes minimal and surgical — modify as few lines as possible to achieve the goal.
- Follow existing code style and conventions in each file.
- Do not remove or modify working tests unless absolutely necessary.
- Validate all changes by running the test suite and linting before committing.

## Dependencies

Key Python packages: `nltk`, `spacy`, `wordfreq`, `numpy`, `sympy`, `fastapi`, `uvicorn`, `pydantic`, `prompt_toolkit`

## Notes

- Python 3.7+ is required.
- JSON data files in `data/` are core to the engine's domain knowledge — handle with care.
- The project exposes CLI entry points defined in `setup.py` (`ollama-shell`, `patch-kingdom-json`, `pending-patches`, `kingdom-editor`).
