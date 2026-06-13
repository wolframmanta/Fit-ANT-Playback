# Agent Brief

## Project Purpose

Python tool to replay FIT power and cadence data as an ANT+ Bike Power source.

## Important Modules

- `fit_ant_playback.py`: CLI entry point.
- `fit_ant_playback_core/fit_parser.py`: FIT file parsing.
- `fit_ant_playback_core/playback_engine.py`: Replay/timing behavior.
- `fit_ant_playback_core/ant_protocol.py`: ANT+ protocol encoding.
- `fit_ant_playback_core/ant_usb.py`: USB/ANT hardware interaction.
- `fit_ant_playback_core/models.py`: Shared data models.
- `tests/`: Unit tests for parser, protocol, USB abstraction, and playback engine.
- `pyproject.toml` and `requirements.txt`: Packaging and dependencies.

## Common Workflows

- FIT parsing issue: start in `fit_ant_playback_core/fit_parser.py` and `tests/test_fit_parser.py`.
- Playback timing issue: start in `fit_ant_playback_core/playback_engine.py` and related tests.
- ANT encoding issue: start in `fit_ant_playback_core/ant_protocol.py`.
- USB/hardware issue: start in `fit_ant_playback_core/ant_usb.py`; do not run hardware/sudo commands unless explicitly asked.

## Commands

- Check repo state: `git status --short`
- Search code: `rg "<term>"`
- Python syntax check: `python3 -m py_compile <file>`
- Run tests: `python3 -m pytest`
- Run CLI locally, only when intended: `python3 fit_ant_playback.py --help`

## Known Constraints

- Do not run `sudo`, hardware playback, or ANT USB commands unless Matthew explicitly asks.
- Preserve timing and protocol behavior unless the requested change is specifically about those areas.
- Keep sample FIT files and hardware-specific paths stable unless the task requires changes.

## Project-Specific Notes

- Favor unit tests for parser/protocol/playback changes because hardware verification may not be available.
