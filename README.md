# Strom

[![Unit Tests](https://github.com/Bloodwing1/Strom/actions/workflows/strom-tests.yml/badge.svg)](https://github.com/Bloodwing1/Strom/actions/workflows/strom-tests.yml)

Strom is a free, open-source smart-heating controller. It uses weather
forecasts and day-ahead electricity prices to compute a heating schedule with
convex optimization, then switches a smart plug to follow it.

There are two ways to run Strom, built on the same control code:

| Way to run | What it is |
| --- | --- |
| **Strom Desktop (alpha)** | A self-contained Linux x86-64 AppImage with a native Qt interface and a built-in updater. No Python, pip, or source checkout needed. |
| **Strom CLI** | The scriptable control cycle for servers, cron jobs, and development, installed from this repository with Python 3.12.8. |

The desktop app is a front end for the CLI, not a second implementation. It
runs the same control code in a child process.

[Read the docs here](https://janbalanya.com/strom-docs/)

---

# Strom Desktop (alpha)

Strom Desktop is the Linux desktop app, still early alpha. Get the latest
AppImage from the
[releases page](https://github.com/Bloodwing1/Strom/releases/latest). Expect
changes, and please report anything that misbehaves.

## Install with Gear Lever

[Gear Lever](https://github.com/mijorus/gearlever) adds AppImages to your
application menu and keeps them in one folder.

1. Download `Strom-<version>-x86_64.AppImage` from the
   [releases page](https://github.com/Bloodwing1/Strom/releases/latest).
2. Install Gear Lever if you do not have it:

   ```sh
   flatpak install flathub it.mijorus.gearlever
   ```

3. Open Gear Lever and drag the AppImage into it, or run:

   ```sh
   flatpak run it.mijorus.gearlever --integrate ./Strom-<version>-x86_64.AppImage
   ```

Strom then shows up in your application menu. Keep the file somewhere you can
write to, because Strom replaces it in place when it updates.

You can also skip Gear Lever and run the AppImage directly:

```sh
chmod +x Strom-<version>-x86_64.AppImage
./Strom-<version>-x86_64.AppImage
```

If FUSE is unavailable, add `--appimage-extract-and-run`.

## Updating Strom Desktop

Strom checks for a newer release when it starts and from **Help → Check for
updates**, then replaces its own AppImage in place. Your settings stay in
`~/.config/strom`. If the AppImage is not writable, Strom offers the release
page for a manual download instead.

## What Strom Desktop does

- Four setup steps: language, weather, prices, plug. Each account has a
  **Test** button that checks it for real. The plug account is optional and
  folded away behind **Use the TP-Link account**; many plugs need no login,
  and account details go only to the plug on your local network. Strom keeps
  a derived key, never the password.
- **Start heating** runs one control interval, about an hour. **Keep running
  automatically** (on by default) starts the next run when the current one
  finishes, and each run shows the heater on-time and estimated cost.
- Closing the window during a run hides it to the system tray and notifies
  you when it finishes. Without a tray, closing during a run is refused.
  There is no Stop button.
- Settings live in `~/.config/strom` and use the same files as the CLI, so
  both can share one configuration directory. Environment variables override
  the files, exactly as with the CLI.
- Needs a Linux x86-64 desktop with X11 or Wayland; the AppImage is built
  against Ubuntu 22.04. If Qt cannot load its platform plugin, clear custom
  `QT_*` variables and check your distribution's desktop libraries.
- Not included yet: scheduling, charts, house-parameter editing, device
  discovery, manual on/off.

## Running Strom Desktop from source

Prefer the AppImage above. If you already have the Python package from the
CLI installation, the same interface is available with the optional GUI
extra:

```sh
pip install '.[gui]'
strom-gui
# or: python -m strom.linux_gui
```

This was verified against **PySide6 6.11.2**. It needs Python 3.12.8 and a
working Qt 6 desktop environment (X11 or Wayland); a PySide6 wheel does not
remove your distribution's shared library requirements.

---

# Strom CLI

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

4. Create a _config_ folder in the root project directory. This folder is
   where your personal API keys will be saved.

5. Place your electricity price and weather API keys in a
   `price_api_key.txt` and `weather_api_key.txt` file that you create in the
   _config_ folder.

6. Place your plug details in a `tapologin.env` file in the _config_ folder.
   `DEVICEIP` is required; `EMAIL` and `PASSWORD` are only needed when the
   plug requires a TP-Link account. Plugs that need no account work with just
   the address:

    ```env
    DEVICEIP=192.168.1.42
    EMAIL=myemail@hotmail.com
    PASSWORD=myPassword12
    ```

    A derived `PLUG_CONFIG` line can also be used instead of the account
    password; the desktop app's **Test** button writes that line for you.

7. You can optionally add your custom house heating parameters to a
   `house_config.json` file in the _config_ folder:

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
    If the file is malformed or contains unknown keys, Strom fails fast with
    an actionable error instead of guessing.

## Usage

[Technical documentation](https://janbalanya.com/strom-docs/)

The `strom` CLI (also available as `python -m strom`) is the single supported
entry point for the control logic. Strom Desktop delegates every run to this
same, unchanged code path:

```sh
strom --config-dir ./config --horizon-hours 24 --log-level INFO
```

`python main.py` remains as a backwards-compatible shim that runs the same
code path.

The control policy executes a bounded duty cycle: the optimizer's fractional
output for each interval is translated into an exact ON/OFF schedule for the
smart plug, and an independent watchdog forces the plug off if it ever stays
on too long.
