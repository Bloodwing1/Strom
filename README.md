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

## AppImage for Linux (no Python needed)

A self-contained desktop build of Strom is published on the
[GitHub Releases page](https://github.com/Bloodwing1/Strom/releases) as
`Strom-<version>-x86_64.AppImage`. It bundles Python, the GUI and all
dependencies, so it runs on a plain Linux x86_64 desktop without Python, pip,
or a source checkout.

The current release is **0.3.0a1 (alpha)**:
[Strom-0.3.0a1-x86_64.AppImage](https://github.com/Bloodwing1/Strom/releases/tag/v0.3.0a1).
It is marked as a pre-release — expect changes, and please report anything
that misbehaves.

1. Download `Strom-<version>-x86_64.AppImage` and `SHA256SUMS` from the
   [release page](https://github.com/Bloodwing1/Strom/releases).
2. Verify the download:

   ```sh
   sha256sum -c SHA256SUMS
   ```

3. Make it executable and run it:

   ```sh
   chmod +x Strom-<version>-x86_64.AppImage
   ./Strom-<version>-x86_64.AppImage
   ```

If launching fails with a FUSE error, either install your distribution's
libfuse2 package, or run without FUSE:

```sh
./Strom-<version>-x86_64.AppImage --appimage-extract-and-run
```

Replacing the AppImage with a newer release updates the application; your
settings, keys, and credentials stay in the user configuration directory
(`~/.config/strom` and the GUI's saved preferences), never inside the
AppImage. The build is verified against an Ubuntu 22.04 (glibc 2.35)
compatibility baseline, including an X11 smoke test; distributions with the
standard desktop libraries (libglib, libdbus, libfontconfig, X11 or Wayland
client libraries) are expected to work, but Strom does not promise automatic
updates, automatic menu integration, or compatibility with every Linux
distribution or architecture.

### Updating from the GUI

The desktop GUI can check for a newer release and install it over the
running AppImage:

- **Check for updates** lives in the application menu (Help) and is also
  run once, silently, a few seconds after the window opens. Checks use
  GitHub's public releases API (no credentials) and never send your
  configuration anywhere.
- Stable installations are offered stable releases; prerelease
  installations (like the current 0.3.0 alpha) also see newer prereleases.
  Downgrades are never offered.
- On a writable AppImage installation, **Update and restart** downloads the
  new AppImage, verifies it against the release's `SHA256SUMS`, runs the
  bundled offline self-test, and replaces the running AppImage atomically;
  the previous version is preserved beside the target until the new one is
  confirmed. The new instance must report a successful start before the old
  window closes, and a failed start restores the previous version
  automatically. A heating cycle is never interrupted: installation is
  unavailable while a cycle runs, and starting a cycle is blocked once an
  update is accepted.
- Source/pip installations, extracted AppDirs, read-only locations, and
  unsupported architectures get an honest **Open release page** fallback
  with manual installation steps instead. There is still no automatic,
  scheduled, or privileged updating; the transaction is integrity-checked
  against the release checksum, which detects corruption and mismatch but
  is not a release signature.
- The first updater-enabled release (0.3.0a1) must still be installed
  manually: older releases cannot discover an updater they do not contain.

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

- Check for and install Strom updates from the application menu (see
  "Updating from the GUI" above); release checks are silent and never
  interrupt setup or a running cycle.
- Guide first-time users through three setup screens: **Weather forecast**,
  **Electricity prices**, and **Your smart plug**. Continue saves the current
  details; errors stay on the same screen. Back lets you revisit earlier steps,
  and Set up later opens the heating screen without starting anything.
  Each account has a "How do I get this?" helper. Returning users resume at
  the first missing account, or go straight to heating when all details are
  available. **Manage accounts** reopens setup.
- Choose English or Spanish and a city or village on the first setup screen.
  Spain is the only available country; more countries are work in progress.
  Choose a suggested city or type a place name, which OpenWeatherMap resolves
  when a cycle runs. The GUI passes the selected place with the ES country code
  to the CLI through `--city`; electricity prices remain Spanish.
- Keep the heating screen focused on planning and running one cycle. Log
  preferences live under **More options**, and the live log is hidden until
  **Show technical details** is selected. The settings folder defaults to
  `~/.config/strom`; **Advanced settings** in setup reveals the custom-folder
  controls for existing CLI users.
- Paste-and-save setup: the weather key, the electricity price token, and
  the Tapo account (email, password, plug IP) can be typed directly into
  the window. Saving writes the exact files the CLI reads
  (`weather_api_key.txt`, `price_api_key.txt`, `tapologin.env`) into the
  selected folder — created automatically if needed — with mode 0600 so
  other users on the machine cannot read them. Values are trimmed of
  copy-paste whitespace; `tapologin.env` is round-trip verified with
  python-dotenv's own parser before anything is written, so unusual
  passwords are stored verbatim or not at all.
- Show a readiness checklist (weather key / price key / plug account) that
  updates as you save, and mention what is still missing in the run
  confirmation if you start a cycle before finishing setup.
- Select a configuration directory with the same file layout as the CLI
  (`tapologin.env`, `price_api_key.txt`, `weather_api_key.txt`, optional
  `house_config.json` — see Installation above); the folder is created on
  demand if it does not exist yet.
- Explain the technical controls: the optimization horizon (1–48 hours,
  default 24 — how far ahead Strom plans, not how long a run takes), the
  log detail level (INFO/WARNING/ERROR), and the selected weather location /
  Spanish (ES) prices.
- Run **one** control cycle. A confirmation dialog states that this operates
  the real smart plug and may switch your heater on for one control interval
  (about one hour) before anything happens; Cancel is the default.
- Watch the cycle's output in a bounded, read-only log while it runs.

### Configuration and environment precedence

- The GUI starts the CLI with the selected directory exported as
  `STROM_CONFIG_DIR` for that run; the CLI resolves the config path explicitly
  and never depends on the directory the GUI was launched from.
- Credentials and keys exported as environment variables (`EMAIL`,
  `PASSWORD`, `DEVICEIP`, `WEATHER_API_KEY`, and `PRICE_API_KEY`) override
  values from `tapologin.env` and the corresponding key files, exactly as
  with the CLI.
- The GUI remembers the last used directory, city, language, horizon, log level,
  and window geometry. The initial directory is the saved path, then `STROM_CONFIG_DIR`,
  then `~/.config/strom`. Only non-secret preferences are stored; API keys
  never enter the GUI's settings.

### Long-running behavior and limitations

- Keep the window open until the cycle finishes. Closing while a cycle is
  starting or running is refused with an explanation, and the child process
  is never killed or detached; the run button and form stay disabled until
  the cycle exits. There is deliberately **no Stop/Force-quit** control in
  this version: no silent process termination.
- Only one cycle runs at a time; duplicate starts are prevented. The setup
  fields are disabled while a cycle runs so files cannot change mid-cycle.
- Not included in this version: house-parameter editing (`house_config.json`
  must still be created by hand), charts, scheduling, tray icon, autostart,
  device discovery, and manual ON/OFF control.

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
- Flatpak packaging (the AppImage release is the foundation)
