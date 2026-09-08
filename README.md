# Strom Project

[![Unit Tests](https://github.com/Bloodwing1/Strom/actions/workflows/strom-tests.yml/badge.svg)](https://github.com/Bloodwing1/Strom/actions/workflows/strom-tests.yml)

## Overview

Strom is a free, open-source script that brings smart heating to your home. It uses weather forecasts and electricity price data to fine-tune energy use, finding a cost-effective heating schedule through convex optimization. With a smart plug, Strom quietly takes care of the details, automatically adjusting your heating to save energy. It’s a simple, clever way to make your home more efficient and eco-friendly.

[Read the docs here](https://janbalanya.com/strom-docs/)

## Requirements

Requires **Python 3.12.8**. With [mise](https://mise.jdx.dev/) the correct
Python (and Node for the git hooks) is provisioned automatically.

## Installation

1. Clone the repository:

    ```sh
    git clone https://github.com/Bloodwing1/Strom.git
    cd Strom
    ```

2. Create a virtual environment and activate it:

    ```sh
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3. Install the package (all runtime dependencies included):

    ```sh
    pip install .
    ```

    For development (tests, lint, type-check):

    ```sh
    pip install -e ".[dev]"
    ```

4. Create a _config_ folder in the root project directory. This folder is where your personal api keys will be saved
5. Place your electricity price and weather API keys in a "price_api_key.txt" "weather_api_key.txt" file that you create in the _config_ folder.
6. Place your tapo account credentials in a "tapologin.env" file in the _config_ folder. The content of this .env file should look like this:

    ```env
    EMAIL=myemail@hotmail.com
    PASSWORD=myPassword12
    DEVICEIP=192.168.1.42
    ```

6. You can optionally add your custom house heating parameters to a "house_config.json" file in the _config_ folder.

```json
{
    "C_air": 0.56,
    "C_wall": 3.5,
    "R_interior": 1.0,
    "R_exterior": 6.06,
    "Q_heater": 2.0,
    "Q_cooling": 0.0,
    "T_min": 18.0,
    "T_max": 24.0,
    "T_interior_init": 18.5,
    "T_wall_init": 18.5,
    "P_base": 0.01,
    "freq": "1h"
}
```

 If the file is missing, the documented default parameters above are used.
 If the file is malformed or contains unknown keys, Strom fails fast with an
 actionable error instead of guessing.

## Usage

[Technical documentation](https://janbalanya.com/strom-docs/)

The `strom` CLI (also available as `python -m strom`) is the single supported
entry point for the control logic. The optional desktop GUI (below) delegates
every run to this same, unchanged code path — it is a convenient front end,
not a separate implementation:

```sh
strom --config-dir ./config --horizon-hours 24 --log-level INFO
```

`python main.py` remains as a backwards-compatible shim that runs the same
code path.

The control policy executes a bounded duty cycle: the optimizer's fractional
output for each interval is translated into an exact ON/OFF schedule for the
smart plug, and an independent watchdog forces the plug off if it ever stays
on too long.

## Desktop GUI (Linux)

An optional native desktop GUI built on Qt 6 Widgets (PySide6) is available.
It was verified against **PySide6 6.11.2**; desktop acceptance testing on a
real Linux X11/Wayland session is tracked separately, so offscreen test
results should not be read as desktop verification.

Install it on top of the normal installation:

```sh
pip install '.[gui]'
```

Then launch it from any directory with either of:

```sh
strom-gui
python -m strom.linux_gui
```

Both launchers need Python 3.12.8 and a working Qt 6 desktop environment
(X11 or Wayland); a PySide6 wheel does not remove your distribution's shared
library requirements.

### What the GUI does in this version

- Select a configuration directory with the same file layout as the CLI
  (`tapologin.env`, `price_api_key.txt`, `weather_api_key.txt`, optional
  `house_config.json` — see Installation above).
- Choose the optimization horizon (1–48 hours, default 24) and the log level
  (INFO, WARNING, or ERROR).
- Run **one** control cycle. A confirmation dialog states that this operates
  the real smart plug and may switch your heater on for one control interval
  (about one hour) before anything happens; Cancel is the default.
- Watch the cycle's output in a bounded, read-only log while it runs.

### Configuration and environment precedence

- The GUI starts the CLI with the selected directory exported as
  `STROM_CONFIG_DIR` for that run; the CLI resolves the config path explicitly
  and never depends on the directory the GUI was launched from.
- Credentials exported as environment variables (`WEATHER_API_KEY`,
  `PRICE_API_KEY`) override the corresponding files, exactly as with the CLI.
- The GUI remembers the last used directory, horizon, log level, and window
  geometry. The initial directory suggestion is the saved path, then
  `STROM_CONFIG_DIR`, then `./config`. Only non-secret preferences are
  stored; API keys never enter the GUI's settings.

### Long-running behavior and limitations

- Keep the window open until the cycle finishes. Closing while a cycle is
  starting or running is refused with an explanation, and the child process
  is never killed or detached; the run button and form stay disabled until
  the cycle exits. There is deliberately **no Stop/Force-quit** control in
  this version: no silent process termination.
- Only one cycle runs at a time; duplicate starts are prevented.
- Not included in this version: credential editing, house-parameter editing,
  charts, scheduling, tray icon, autostart, device discovery, and manual
  ON/OFF control.

### Linux troubleshooting

- An error such as "xcb plugin found but could not load" usually means
  missing system shared libraries or a mixed Qt installation — not a missing
  Python import. Check Qt's Linux requirements for the libraries your
  distribution needs.
- Do not force `QT_QPA_PLATFORM=xcb` globally or overwrite Qt plugin paths.
  To diagnose a plugin problem, run once with `QT_DEBUG_PLUGINS=1` and clear
  any stray Qt environment settings instead of hard-coding a workaround.
- On Wayland the GUI uses the Wayland platform plugin automatically.

## Development

- `mise run check` — lint, type-check and deterministic tests (what CI blocks on)
- `mise run test-integration` — live provider canaries (needs API keys)
- `mise run mutation` — mutation testing of the safety-critical modules

Git hooks (via [husky](https://typicode.github.io/husky/)) run the linter on
commit and the full check on push; enable them with `mise run hooks`.

## Future Considerations

- Cron job installer
- Standalone executable
