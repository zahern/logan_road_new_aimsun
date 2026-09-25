# =============================================================================
# studio_launcher.py — double-click launcher for batch_runner_studio.py
# =============================================================================
# Compiled to TSP_Batch_Studio.exe with PyInstaller (see build command in the
# repo notes). The exe is a thin launcher: it finds an installed Python that
# has streamlit, then runs `python -m streamlit run batch_runner_studio.py`
# from the folder the exe lives in. Streamlit itself is NOT bundled into the
# exe — keep batch_runner_studio.py (and the corridor folders) next to it.
#
# Closing this console window stops the studio server.
# =============================================================================

import os
import shutil
import subprocess
import sys

PORT = "8577"


def _base_dir() -> str:
    # When frozen by PyInstaller, the app files live next to the exe.
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _candidate_pythons():
    local = os.environ.get("LOCALAPPDATA", r"C:\Users\%USERNAME%\AppData\Local")
    for ver in ("Python312", "Python313", "Python311", "Python310"):
        yield os.path.join(local, "Programs", "Python", ver, "python.exe")
    for name in ("python", "python3"):
        p = shutil.which(name)
        if p:
            yield p


def _find_python_with_streamlit():
    seen = set()
    for py in _candidate_pythons():
        py = os.path.normcase(os.path.abspath(py))
        if py in seen or not os.path.isfile(py):
            continue
        seen.add(py)
        try:
            rc = subprocess.run(
                [py, "-c", "import streamlit"],
                capture_output=True, timeout=30,
            ).returncode
        except Exception:
            continue
        if rc == 0:
            return py
    return None


def _suppress_streamlit_onboarding():
    """Pre-answer Streamlit's first-run email prompt so the server never
    blocks on stdin (it would otherwise hang a double-clicked exe)."""
    cfg_dir = os.path.join(os.path.expanduser("~"), ".streamlit")
    cred = os.path.join(cfg_dir, "credentials.toml")
    if not os.path.isfile(cred):
        try:
            os.makedirs(cfg_dir, exist_ok=True)
            with open(cred, "w", encoding="utf-8") as f:
                f.write('[general]\nemail = ""\n')
        except OSError:
            pass  # non-fatal: streamlit will just ask once


def main() -> int:
    base = _base_dir()
    app = os.path.join(base, "batch_runner_studio.py")
    _suppress_streamlit_onboarding()
    print("=" * 62)
    print("TSP Batch Runner Studio launcher")
    print("=" * 62)

    if not os.path.isfile(app):
        print(f"ERROR: batch_runner_studio.py not found next to the exe:\n  {app}")
        print("Keep TSP_Batch_Studio.exe in the repo root, next to the app file.")
        input("Press Enter to close...")
        return 1

    py = _find_python_with_streamlit()
    if py is None:
        print("ERROR: no Python installation with streamlit was found.")
        print("Install it once with:")
        print("  python -m pip install --user streamlit pandas")
        input("Press Enter to close...")
        return 1

    print(f"Python : {py}")
    print(f"App    : {app}")
    print(f"URL    : http://localhost:{PORT}  (browser opens automatically)")
    print("Close this window to stop the studio.")
    print("-" * 62)

    proc = subprocess.Popen(
        [py, "-m", "streamlit", "run", app,
         "--server.port", PORT,
         "--browser.gatherUsageStats", "false"],
        cwd=base,
    )
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0


if __name__ == "__main__":
    sys.exit(main())
