#!/usr/bin/env python3
"""
Builds the single-file downloads for a GitHub release from odus.py:

    dist/odus.bat      Windows     (launcher + the whole program in one file)
    dist/odus.sh       Linux       (launcher + the whole program in one file)
    dist/odus.command  macOS       (same as odus.sh; double-clickable in Finder)
    dist/odus.py       any system  (plain source: python odus.py)

The .bat, .sh and .command files don't need Python installed: if there's no Python 3.9+
on the computer, they offer to download a private copy (checked against a
known SHA-256 fingerprint) into Odus's own folder, once.

Run:  python build.py   then upload all four files from dist/ to the release.
"""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

# The private Python that odus.bat / odus.sh / odus.command download when none is installed.
PY_VERSION = "3.12.10"
# Windows: python.org's "embeddable package" (fingerprints checked against python.org's release page)
WIN_SHA256 = {
    "amd64": "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3",
    "arm64": "3065efc3d382d1cda66757ac71ade11904fa6e350f5a97eb74811acd71ba5532",
    "win32": "084b9eb24cb848605c895d05b738fbc2572efc8b4c18c415a824065864a2b853",
}
# macOS / Linux: python-build-standalone (the builds uv uses); fingerprints from its SHA256SUMS
PBS_TAG = "20250409"
PBS_SHA256 = {
    "x86_64-unknown-linux-gnu": "8c59b9ac6bff2dc3934181d7bc82594f9f59a613afed8d72c9e89d7194e790ee",
    "aarch64-unknown-linux-gnu": "e1f450b77b81a250411855bb5e5cbd0f0acbc9ad46b5ea97f224452831bb3276",
    "x86_64-unknown-linux-musl": "1bd983175b02b493231801c0a282a6269851e84b22958b97b881906f0d224a28",
    "x86_64-apple-darwin": "ad3bef94b6054adcf8e0a47886e21b00dfc6a37f22eea229cf0f8725bd0e1023",
    "aarch64-apple-darwin": "0be1fe0b35a4d3c382141764ef16ed3b8cc2b4620b657f678daa7b7f8df39699",
}

# ---------------------------------------------------------------- Windows
# cmd runs line 1 and jumps to the batch part at the bottom. Python is started
# with -x (skips line 1) and sees the batch part as a string.
CMD_HEAD = "@echo off & goto :odus_batch\n"
CMD_TAIL = r"""
r'''
:odus_batch
rem Odus launcher. No setlocal on purpose, so Live Refresh can update this window.
set "ODUS_OWN_REFRESH="
if not defined ODUS_REFRESH_FILE set "ODUS_OWN_REFRESH=1"
if defined ODUS_OWN_REFRESH set "ODUS_REFRESH_FILE=%TEMP%\odus-refresh-%RANDOM%%RANDOM%.cmd"
call :odus_find_python
set "ODUS_RC=1"
if not defined ODUS_PY goto :odus_after
%ODUS_PY% -x "%~f0" %*
set "ODUS_RC=%errorlevel%"
:odus_after
if defined ODUS_OWN_REFRESH if exist "%ODUS_REFRESH_FILE%" call "%ODUS_REFRESH_FILE%"
if defined ODUS_OWN_REFRESH if exist "%ODUS_REFRESH_FILE%" del "%ODUS_REFRESH_FILE%" >nul 2>nul
if defined ODUS_OWN_REFRESH set "ODUS_REFRESH_FILE="
set "ODUS_OWN_REFRESH="
set "ODUS_PY="
set "ODUS_RC=" & exit /b %ODUS_RC%

:odus_find_python
rem 1) Odus's own copy  2) an installed Python 3.9+  3) offer to download one
set "ODUS_PY="
set "ODUS_HOME=%LOCALAPPDATA%\Odus\python-@PY_VERSION@"
if exist "%ODUS_HOME%\python.exe" set ODUS_PY="%ODUS_HOME%\python.exe"
if defined ODUS_PY goto :eof
py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set "ODUS_PY=py -3"
if defined ODUS_PY goto :eof
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && set "ODUS_PY=python"
if defined ODUS_PY goto :eof
call :odus_get_python
goto :eof

:odus_get_python
set "ODUS_ARCH=amd64"
set "ODUS_SHA=@SHA_amd64@"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ODUS_ARCH=arm64"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "ODUS_SHA=@SHA_arm64@"
if /i "%PROCESSOR_ARCHITECTURE%"=="x86" if not defined PROCESSOR_ARCHITEW6432 set "ODUS_ARCH=win32"
if /i "%ODUS_ARCH%"=="win32" set "ODUS_SHA=@SHA_win32@"
echo Odus needs Python to run, and Python 3.9 or newer isn't installed.
set "ODUS_ANS="
set /p "ODUS_ANS=Download a private copy just for Odus (about 11 MB, nothing else on your PC changes)? [Y/n] "
if /i "%ODUS_ANS%"=="n" goto :odus_py_declined
if /i "%ODUS_ANS%"=="no" goto :odus_py_declined
set "ODUS_URL=https://www.python.org/ftp/python/@PY_VERSION@/python-@PY_VERSION@-embed-%ODUS_ARCH%.zip"
set "ODUS_ZIP=%TEMP%\odus-python-%RANDOM%%RANDOM%.zip"
echo Downloading Python @PY_VERSION@ from python.org...
curl.exe -fsSL -o "%ODUS_ZIP%" "%ODUS_URL%" >nul 2>nul
if not exist "%ODUS_ZIP%" powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%ODUS_URL%' -OutFile '%ODUS_ZIP%'" >nul 2>nul
if not exist "%ODUS_ZIP%" goto :odus_py_failed
set "ODUS_GOT="
for /f "skip=1 delims=" %%H in ('certutil -hashfile "%ODUS_ZIP%" SHA256') do if not defined ODUS_GOT set "ODUS_GOT=%%H"
set "ODUS_GOT=%ODUS_GOT: =%"
if /i not "%ODUS_GOT%"=="%ODUS_SHA%" goto :odus_py_badhash
mkdir "%ODUS_HOME%" >nul 2>nul
tar -xf "%ODUS_ZIP%" -C "%ODUS_HOME%" >nul 2>nul
if not exist "%ODUS_HOME%\python.exe" powershell -NoProfile -Command "Expand-Archive -LiteralPath '%ODUS_ZIP%' -DestinationPath '%ODUS_HOME%' -Force" >nul 2>nul
del "%ODUS_ZIP%" >nul 2>nul
if not exist "%ODUS_HOME%\python.exe" goto :odus_py_failed
set ODUS_PY="%ODUS_HOME%\python.exe"
echo Python is ready. Starting Odus...
echo.
goto :eof

:odus_py_badhash
del "%ODUS_ZIP%" >nul 2>nul
echo The download didn't match Python's known fingerprint, so Odus deleted it and stopped.
echo Try again later, or install Python yourself (see below).
goto :odus_py_howto
:odus_py_failed
echo Couldn't download Python. Check your internet connection and try again,
echo or install Python yourself (see below).
goto :odus_py_howto
:odus_py_declined
echo OK, nothing was downloaded.
:odus_py_howto
echo   winget install Python.Python.3.12
echo   (or get it from https://www.python.org/downloads/ )
echo Then run Odus again.
goto :eof
'''
"""

# ------------------------------------------------------------ macOS / Linux
# sh runs lines 2+ and hands the file to Python; to Python those lines are
# just the module's docstring. (No backslashes or three quotes in a row here.)
SH_HEAD = r"""#!/bin/sh
''':'
# Odus launcher: use Odus's own Python, else an installed Python 3.9+, else
# offer to download a private copy once.
ODUS_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/odus/python-@PY_VERSION@"
odus_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; }
ODUS_PY=""
[ -x "$ODUS_HOME/bin/python3" ] && ODUS_PY="$ODUS_HOME/bin/python3"
if [ -z "$ODUS_PY" ]; then
  for c in python3 python; do
    p=$(command -v "$c" 2>/dev/null) || continue
    # on macOS /usr/bin/python3 is only a placeholder until Apple's developer tools are installed
    if [ "$p" = /usr/bin/python3 ] && [ "$(uname -s)" = Darwin ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if odus_ok "$p"; then ODUS_PY="$p"; break; fi
  done
fi
if [ -z "$ODUS_PY" ]; then
  case "$(uname -s)-$(uname -m)" in
    Linux-x86_64) a=x86_64-unknown-linux-gnu; h=@SHA_x86_64-unknown-linux-gnu@
      if [ -f /etc/alpine-release ]; then a=x86_64-unknown-linux-musl; h=@SHA_x86_64-unknown-linux-musl@; fi ;;
    Linux-aarch64|Linux-arm64) a=aarch64-unknown-linux-gnu; h=@SHA_aarch64-unknown-linux-gnu@ ;;
    Darwin-x86_64) a=x86_64-apple-darwin; h=@SHA_x86_64-apple-darwin@ ;;
    Darwin-arm64) a=aarch64-apple-darwin; h=@SHA_aarch64-apple-darwin@ ;;
    *) a="" ;;
  esac
  if [ "$(uname -s)" = Darwin ]; then hint="brew install python   (or: xcode-select --install)"
  else hint="sudo apt install python3   (or your system's package manager)"; fi
  echo "Odus needs Python to run, and Python 3.9 or newer isn't installed."
  if [ -z "$a" ]; then
    echo "Odus can't download Python for this system. Install it yourself:"; echo "  $hint"; exit 1
  fi
  printf "Download a private copy just for Odus (about 20 MB, nothing else changes)? [Y/n] "
  read -r ans || ans=""
  case "$ans" in
    [nN]*) echo "OK, nothing was downloaded. Install Python yourself:"; echo "  $hint"
           echo "Then run Odus again."; exit 1 ;;
  esac
  url="https://github.com/astral-sh/python-build-standalone/releases/download/@PBS_TAG@/cpython-@PY_VERSION@+@PBS_TAG@-$a-install_only_stripped.tar.gz"
  tmp=$(mktemp -d 2>/dev/null || mktemp -d -t odus) || exit 1
  echo "Downloading Python @PY_VERSION@..."
  if command -v curl >/dev/null 2>&1; then curl -fsSL -o "$tmp/py.tgz" "$url"
  else wget -q -O "$tmp/py.tgz" "$url"; fi
  if [ ! -s "$tmp/py.tgz" ]; then
    rm -rf "$tmp"; echo "Couldn't download Python. Check your internet connection, or install it yourself:"
    echo "  $hint"; exit 1
  fi
  got=$( (sha256sum "$tmp/py.tgz" 2>/dev/null || shasum -a 256 "$tmp/py.tgz") | cut -d " " -f 1)
  if [ "$got" != "$h" ]; then
    rm -rf "$tmp"; echo "The download didn't match Python's known fingerprint, so Odus deleted it and stopped."
    echo "Try again later, or install Python yourself:"; echo "  $hint"; exit 1
  fi
  tar -xzf "$tmp/py.tgz" -C "$tmp" && mkdir -p "$(dirname "$ODUS_HOME")" && rm -rf "$ODUS_HOME" && mv "$tmp/python" "$ODUS_HOME"
  rm -rf "$tmp"
  if [ ! -x "$ODUS_HOME/bin/python3" ]; then echo "Couldn't unpack Python. Install it yourself:"; echo "  $hint"; exit 1; fi
  ODUS_PY="$ODUS_HOME/bin/python3"
  echo "Python is ready. Starting Odus..."; echo
fi
exec "$ODUS_PY" "$0" "$@"
':'''
"""


def fill(template: str) -> str:
    out = template.replace("@PY_VERSION@", PY_VERSION).replace("@PBS_TAG@", PBS_TAG)
    for k, v in {**WIN_SHA256, **PBS_SHA256}.items():
        out = out.replace(f"@SHA_{k}@", v)
    left = re.findall(r"@(?:PY_VERSION|PBS_TAG|SHA_[\w.-]+)@", out)
    assert not left, f"unfilled placeholder: {left}"
    return out


def main():
    src = open(os.path.join(ROOT, "odus.py"), encoding="utf-8").read().replace("\r\n", "\n")
    body = src.split("\n", 1)[1] if src.startswith("#!") else src
    version = re.search(r'^VERSION = "([^"]+)"', body, re.M).group(1)
    os.makedirs(DIST, exist_ok=True)

    cmd = fill(CMD_HEAD) + body.rstrip("\n") + "\n" + fill(CMD_TAIL)
    with open(os.path.join(DIST, "odus.bat"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(cmd)  # batch files need Windows line endings to find their labels
    old = os.path.join(DIST, "odus.cmd")  # older builds were called odus.cmd
    if os.path.exists(old):
        os.remove(old)

    # the original docstring becomes comments, because the launcher is now the docstring
    m = re.match(r'\s*"""(.*?)"""\n', body, re.S)
    doc = "".join(f"# {line}".rstrip() + "\n" for line in m.group(1).strip("\n").split("\n")) if m else ""
    sh = fill(SH_HEAD) + doc + (body[m.end():] if m else body)
    for name in ("odus.sh", "odus.command"):  # .command is what macOS opens with a double-click
        path = os.path.join(DIST, name)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(sh)
        os.chmod(path, 0o755)

    # the plain Python source, for people who'd rather run: python odus.py
    with open(os.path.join(DIST, "odus.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(src)

    print(f"Built Odus v{version}:")
    for name in ("odus.bat", "odus.sh", "odus.command", "odus.py"):
        print(f"  dist/{name}  ({os.path.getsize(os.path.join(DIST, name)) // 1024} KB)")
    print(f"Upload all four to a GitHub release tagged v{version}.")


if __name__ == "__main__":
    main()
