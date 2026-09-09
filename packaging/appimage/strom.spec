# PyInstaller spec for the bundled Strom entry point (AppImage guide, step 2).
#
# One-directory mode: COLLECT places the executable and its _internal payload
# next to each other; the AppDir assembly in build.sh copies that directory
# into Strom.AppDir/usr/bin. One-file mode is deliberately avoided: it would
# add a second extraction layer and complicate child-process behavior.
#
# The entry script is packaging/appimage/strom_entry.py, which imports the
# strom package installed non-editably in the fresh build venv. Console mode
# is required: the packaged CLI branch must keep stdout/stderr for the GUI's
# child-process log (a desktop launcher still shows no console on Linux).

import importlib.util
import os
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

datas = collect_data_files("strom.linux_gui")

# The updater's version lookup reads package metadata (importlib.metadata);
# shipping the dist-info keeps the frozen build reporting its real version,
# from the same pyproject source the pip build uses (update plan §1).
datas += copy_metadata("strom")

# zoneinfo consults the system tzdata (/usr/share/zoneinfo) first and falls
# back to the bundled tzdata package only if that fails. Shipping it keeps
# entsoe/pandas timestamps working on systems without a complete system
# tz database (found by the Ubuntu 22.04 container test).
datas += collect_data_files("tzdata")

# cvxpy.utilities.warn calls os.listdir() on the cvxpy package directory at
# import time. Pure modules live in the PYZ archive, so that directory would
# not exist in a frozen build; shipping py.typed materializes it. Found by
# the staged AppRun self-test (first run), not by reading PyInstaller output.
cvxpy_spec = importlib.util.find_spec("cvxpy")
assert cvxpy_spec is not None and cvxpy_spec.submodule_search_locations
cvxpy_dir = cvxpy_spec.submodule_search_locations[0]
datas += [(os.path.join(cvxpy_dir, "py.typed"), "cvxpy")]

a = Analysis(
    [os.path.join(SPECPATH, "strom_entry.py")],
    pathex=[SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Loaded dynamically by product code, invisible to static analysis
        # if the importing module is only scanned lazily:
        "kasa",      # Tapo plug control (imported inside controller functions)
        "entsoe",    # ENTSO-E price client
        "clarabel",  # native CLARABEL solver behind cvxpy's dynamic loading
        # cvxpy eagerly imports every installed solver interface; osqp picks
        # its algebra backend with a runtime importlib call. Without this,
        # every frozen import of cvxpy logs "No algebra backend available!"
        # into the child log (found by the staged AppRun self-test).
        "osqp.ext_builtin",
        # zoneinfo's bundled fallback; imported dynamically only when the
        # system tz database lookup fails.
        "tzdata",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Never shipped, never imported by product code:
        "tkinter",
        "pytest",
        "setuptools",
        "pip",
    ],
    noarchive=False,
)

# Keep only binaries that ship inside Python wheels (site-packages), the
# build interpreter's own stdlib tree (its lib-dynload binary extensions),
# and libpython itself. PyInstaller otherwise copies the build host's system
# libraries (X11, GTK/glib, OpenSSL, libstdc++, ...) into the bundle, which
# would silently raise the requirement to the build host's glibc (the ELF
# audit in build.sh exists to catch exactly this). GUI system libraries are
# instead resolved at runtime by the target distribution, which is how
# manylinux wheels are designed to work and what preserves the Ubuntu 22.04
# baseline.
#
# The stdlib part matters more than it looks: whether stdlib extensions are
# shared libraries (lib-dynload) or built into the interpreter depends on
# the CPython build. The build host's Python compiled them in, which hid the
# gap locally; the actions/setup-python Python used in CI ships them as .so
# files, and without this rule the frozen bootstrap failed at startup with
# "No module named 'binascii'" (zipfile -> binascii) — found by the PR CI
# run and reproduced locally with the same interpreter.
import sys as _sys
import sysconfig as _sysconfig
import site as _site

_SITE_PATHS = tuple(os.path.realpath(p) for p in _site.getsitepackages())
_PY_LIB_DIR = "python{}.{}".format(*_sys.version_info[:2])
_PYTHON_DIRS = tuple(
    os.path.realpath(candidate)
    for candidate in (
        os.path.join(_sys.base_prefix, "lib", _PY_LIB_DIR),
        os.path.join(_sys.prefix, "lib", _PY_LIB_DIR),
        _sysconfig.get_path("stdlib"),
        _sysconfig.get_path("platstdlib"),
    )
    if candidate
)


def _wheel_or_python_binary(entry) -> bool:
    source = os.path.realpath(entry[1])
    if source.startswith(_SITE_PATHS + _PYTHON_DIRS):
        return True
    return entry[0].startswith("libpython3.")


a.binaries = [entry for entry in a.binaries if _wheel_or_python_binary(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="strom-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="strom-gui",
)
