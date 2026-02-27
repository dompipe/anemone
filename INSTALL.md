# Natural Code Engine Project Structure

## Installation

1. (Optional) Create and activate a virtual environment:

   ```sh
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install requirements:

   ```sh
   pip install -r requirements.txt
   ```

3. Install as a package (registers all CLI entry points):

   ```sh
   pip install .
   ```

## Project Structure

- `eng1neer.py` – Main code/definition engine
- `new_natural_code_engine.py` – Natural language code engine logic
- `anemone_agent/` – Local Ollama-backed coding agent (see below)
- `data/` – Definitions and domain data (JSON)
- `requirements.txt` – Python dependencies
- `setup.py` – Install/setup script

## Usage

Run the engine interactively:

```sh
python eng1neer.py
```

---

## Anemone Coding Agent

`anemone` is a CLI coding agent that uses a local [Ollama](https://ollama.ai)
instance as its LLM backend.  It implements a **plan → act → check → iterate**
loop:

1. Gathers relevant files from the repo for context.
2. Asks the model to produce a plan.
3. Asks the model to generate file edits (unified diff or JSON).
4. Applies the edits safely (path-traversal protection).
5. Runs `ruff` and `pytest`; feeds failures back into the next iteration.

### Prerequisites

- [Ollama](https://ollama.ai) installed and running (`ollama serve`).
- The target model pulled, e.g. `ollama pull llama3.1`.
- (Optional) `ruff` and `pytest` installed in your environment.

### Quick start

```sh
# Install the package (registers the `anemone` command)
pip install .

# Run Ollama in another terminal
ollama serve

# Give the agent a task
anemone "Add a hello_world function to utils.py and a test for it"
```

### CLI reference

```
usage: anemone [-h] [--task TASK] [--model MODEL] [--ollama-url URL]
               [--max-iterations N] [--repo-root PATH]
               [--no-ruff] [--no-pytest] [--dry-run] [--verbose]
               [--math MODE]
               [task]

positional arguments:
  task                  Natural-language task description.

options:
  --task TASK           Alternative way to pass the task.
  --model MODEL         Ollama model name (default: llama3.1).
  --ollama-url URL      Ollama base URL (default: http://localhost:11434).
  --max-iterations N    Maximum agent iterations (default: 5).
  --repo-root PATH      Target repository root (default: .).
  --no-ruff             Disable ruff check.
  --no-pytest           Disable pytest.
  --dry-run             Print patches without applying them.
  --verbose, -v         Enable verbose logging.
  --math MODE           Math solving mode: off | auto | annotated | json | latex
                        (default: auto).
```

### Environment variables

| Variable                | Default                    | Description                  |
|-------------------------|----------------------------|------------------------------|
| `ANEMONE_MODEL`         | `llama3.1`                 | Ollama model name            |
| `ANEMONE_OLLAMA_URL`    | `http://localhost:11434`   | Ollama base URL              |
| `ANEMONE_MAX_ITERATIONS`| `5`                        | Max iterations               |
| `ANEMONE_REPO_ROOT`     | `.`                        | Target repository root       |
| `ANEMONE_MATH`          | `auto`                     | Math solving mode            |

### Examples

```sh
# Use a different model
anemone --model codellama "Refactor auth.py to use dataclasses"

# Dry-run: see what patches would be applied without touching files
anemone --dry-run "Add type hints to all functions in utils.py"

# Disable pytest for a quick lint-only loop
anemone --no-pytest "Fix all ruff warnings in ."

# Point at a different repo
anemone --repo-root ~/projects/myapp "Add a README section about configuration"
```

---

## Math Solving

`anemone` includes a **local math solver** powered by [sympy](https://www.sympy.org)
and [pint](https://pint.readthedocs.io).  No Ollama connection is needed for
math queries – they are handled entirely offline.

### Math modes (`--math`)

| Mode        | Behaviour                                                         |
|-------------|-------------------------------------------------------------------|
| `auto`      | Detect math queries automatically; show annotated solution.       |
| `annotated` | Always treat the task as math; show student-style annotated text. |
| `json`      | Output structured JSON (machine-readable steps + answer).         |
| `latex`     | Output LaTeX-formatted solution.                                  |
| `off`       | Disable math shortcut; always use the Ollama agent loop.          |

### Examples

```sh
# Simple arithmetic
anemone "2 + 3 * 4"
# Output: annotated solution with ANSWER: result = 14

# Distance word problem (schema-based)
anemone --math json "60 * 2.5"
# Output: {"answer": 150.0, "steps": [...], ...}

# LaTeX output
anemone --math latex "3**2 + 4**2"
# Output: \textbf{Answer:} $result = 25$

# Unit conversion (requires pint: pip install pint)
python - <<'EOF'
from anemone_agent.math_solver import convert_units, render_annotated, solve_schema
# Convert 60 mph to m/s
schema = {
    "given": {"speed_mph": 60},
    "unknowns": ["speed_ms"],
    "compute_steps": [{
        "expression": "speed_mph",
        "assign": "speed_ms",
        "description": "Convert 60 mph to m/s",
        "from_unit": "mile / hour",
        "to_unit": "meter / second",
        "unit": "m/s",
    }],
    "answer_unit": "m/s",
}
result = solve_schema(schema)
print(render_annotated(result))
EOF
```

### Supported units

All units supported by the [pint](https://pint.readthedocs.io/en/stable/user/defining.html)
library are available, including:

- **Distance**: `meter`, `kilometer`, `mile`, `foot`, `inch`, `centimeter`
- **Time**: `second`, `minute`, `hour`
- **Speed**: `meter / second`, `kilometer / hour`, `mile / hour`
- **Mass**: `kilogram`, `gram`, `pound`, `ounce`
- **Volume**: `liter`, `milliliter`, `gallon`, `cup`
- **Temperature**: `degC`, `degF`, `kelvin`

### Safety

- Expressions are evaluated by **sympy** only – no `eval()` or `exec()`.
- Forbidden keywords (`import`, `exec`, `eval`, `open`, `__`, …) raise an error.
- Expressions longer than 500 characters are rejected.
- Evaluation times out after 5 seconds.
- Compute schemas with more than 50 steps are rejected.


