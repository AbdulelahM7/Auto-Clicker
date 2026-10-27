# Contributing to Auto Clicker

Thank you for your interest in contributing to Auto Clicker!

## Development Setup

1. Clone the repository and install dependencies:
   ```powershell
   git clone https://github.com/E7TRAF702/auto-clicker.git
   cd auto-clicker
   py -m pip install -r requirements.txt pytest ruff
   ```
2. Run the app from source:
   ```powershell
   py auto_clicker.py
   ```
3. Run tests and linter before opening a Pull Request:
   ```powershell
   pytest -v
   ruff check .
   ```
4. Run the timing benchmark:
   ```powershell
   py tools/benchmark.py
   ```

## Pull Request Guidelines
- Keep changes focused and maintain clean separation between `autoclicker/config.py`, `autoclicker/engine.py`, and `autoclicker/gui.py`.
- Add or update unit tests in `tests/test_logic.py` for any new logic or settings.
