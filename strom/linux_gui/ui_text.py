"""Text, sizes and timing constants shared by the window modules.

Kept apart from the window classes so the setup, settings, run and tray
parts share one source of truth without importing each other.
"""

from __future__ import annotations

from strom.linux_gui.runner import RunnerState
from strom.linux_gui.setup_files import PRICE_FILE, TAPO_FILE, WEATHER_FILE

_LOG_LEVELS = ("INFO", "WARNING", "ERROR")
_DEFAULT_HORIZON = 24
_MIN_HORIZON = 2
_MAX_HORIZON = 48
_INITIAL_SIZE = (720, 640)
_CONTENT_MAX_WIDTH = 760
_LOG_MAX_BLOCKS = 2000
_LOG_MIN_HEIGHT = 120
_REPEAT_DELAY_MS = 2000
_ELAPSED_TICK_MS = 30_000
_STEP_SHORT_NAMES = ("Language", "Weather", "Prices", "Plug")
_CONTRIBUTE_URL = "https://github.com/Bloodwing1/Strom"
_RUNNER_LABELS = {
    RunnerState.Idle: "Ready",
    RunnerState.Starting: "Starting…",
    RunnerState.Running: "Working…",
    RunnerState.Completed: "Done",
    RunnerState.FailedToStart: "Couldn't start",
    RunnerState.Failed: "Couldn't finish",
}
_ERROR_COLOR = "#c0392b"
_RUN_BLOCKED_TEXT = (
    "An update is being installed; starting a heating cycle is blocked "
    "until it finishes or is rolled back."
)
_INTRO_TEXT = (
    "Plan your heating around lower electricity prices. "
    "Nothing runs until you choose Start heating."
)
_FOLDER_HELP_TEXT = (
    "Your weather key, price key, and plug account are saved as small "
    f"files ({WEATHER_FILE}, {PRICE_FILE}, {TAPO_FILE}) inside the settings "
    "folder shown above; the folder is created automatically. Already using "
    "the strom command line? Tick 'Use a custom settings folder' and pick "
    "your existing folder so Strom finds your keys."
)
_HORIZON_HELP_TEXT = (
    "How far ahead Strom plans, in hours. This does not make the run take "
    "longer. 24 hours is a good default."
)
_LOG_LEVEL_HELP_TEXT = (
    "How much detail the activity log below shows. INFO (recommended) shows "
    "normal progress; WARNING shows only warnings and errors; ERROR shows "
    "only failures."
)
_LOCATION_NOTE_TEXT = (
    "Using Barcelona weather and Spanish (ES) electricity prices."
)
_CYCLE_TEXT = (
    "Clicking Start heating checks the weather and prices, then may switch "
    "your heater on or off for about one hour. Keep Strom running until the "
    "run finishes."
)
_CONFIRM_TEXT = (
    "Strom will check the weather and electricity prices, then may switch "
    "your real heater on or off for about one hour. Keep Strom running until "
    "the run finishes."
)
_REPEAT_HELP_TEXT = (
    "When a run finishes, Strom starts the next one automatically. Strom "
    "must stay running for this to keep your home warm."
)
_CLOSE_REFUSED_TEXT = (
    "A control cycle is starting or running, so the window must stay open "
    "until the cycle finishes. There is no safe way to cancel a running "
    "cycle from here; the run button and form are disabled until the child "
    "process exits."
)
_WEATHER_SIGNUP_URL = "https://openweathermap.org/api"
_PRICE_SIGNUP_URL = "https://transparency.entsoe.eu"
_WEATHER_HELP_TEXT = (
    "<html><head/><body><p>Strom uses the free <b>OpenWeatherMap</b> "
    "service for the weather forecast.</p>"
    "<ol>"
    "<li>Open <a href=\"https://openweathermap.org/api\">"
    "openweathermap.org/api</a> and click <b>Sign up</b> (free).</li>"
    "<li>After signing in, open <b>API keys</b> under your account name.</li>"
    "<li>Copy the key (a long code) and paste it into the box, then click "
    "<b>Save</b>.</li>"
    "</ol></body></html>"
)
_PRICE_HELP_TEXT = (
    "<html><head/><body><p>Strom uses the <b>ENTSO-E Transparency "
    "Platform</b> for European electricity prices.</p>"
    "<ol>"
    "<li>Open <a href=\"https://transparency.entsoe.eu\">"
    "transparency.entsoe.eu</a> and create a free account.</li>"
    "<li>Request a Web API token as described on the platform; the token "
    "is sent to you by email.</li>"
    "<li>Paste the token into the box, then click <b>Save</b>.</li>"
    "</ol></body></html>"
)
_TAPO_HELP_TEXT = (
    "These are the login details for your TP-Link Tapo account — the email "
    "and password you use in the Tapo phone app for the smart plug your "
    "heater is connected to. You only need the account if the plug asks for "
    "it; many newer plugs work without one. The IP address is shown in the "
    "Tapo app: tap your plug, then the gear icon, then look under device "
    "information."
)
