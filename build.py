#!/usr/bin/env python3
"""
Builds the single-file downloads for a GitHub release from odus.py:

    dist/odus.cmd   Windows        (batch launcher + Python in one file)
    dist/odus.sh    macOS / Linux  (sh launcher + Python in one file)
    dist/odus.py    any system     (plain source: python odus.py)

Each file is the whole program, so people only download one file.
Run:  python build.py   then upload all three files from dist/ to the release.
"""
import os
import re

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

# Windows: cmd runs line 1 and jumps to the batch part at the bottom.
# Python is started with -x, which skips line 1, and sees the batch part as a string.
CMD_HEAD = "@echo off & goto :odus_batch\n"
CMD_TAIL = r"""
r'''
:odus_batch
rem No setlocal on purpose, so Live Refresh can update this window.
set "ODUS_REFRESH_FILE=%TEMP%\odus-refresh-%RANDOM%%RANDOM%.cmd"
where py >nul 2>nul && goto :odus_py
python -x "%~f0" %*
goto :odus_after
:odus_py
py -3 -x "%~f0" %*
:odus_after
set "ODUS_RC=%errorlevel%"
if exist "%ODUS_REFRESH_FILE%" call "%ODUS_REFRESH_FILE%"
if exist "%ODUS_REFRESH_FILE%" del "%ODUS_REFRESH_FILE%" >nul 2>nul
set "ODUS_REFRESH_FILE="
set "ODUS_RC=" & exit /b %ODUS_RC%
'''
"""

# macOS / Linux: sh runs line 2 and hands the file to Python; to Python that
# line is just the module's docstring.
SH_HEAD = ("#!/bin/sh\n"
           "''''command -v python3 >/dev/null 2>&1 && exec python3 \"$0\" \"$@\"; exec python \"$0\" \"$@\" #'''\n")


def main():
    src = open(os.path.join(ROOT, "odus.py"), encoding="utf-8").read().replace("\r\n", "\n")
    body = src.split("\n", 1)[1] if src.startswith("#!") else src
    version = re.search(r'^VERSION = "([^"]+)"', body, re.M).group(1)
    os.makedirs(DIST, exist_ok=True)

    cmd = CMD_HEAD + body.rstrip("\n") + "\n" + CMD_TAIL
    with open(os.path.join(DIST, "odus.cmd"), "w", encoding="utf-8", newline="\r\n") as f:
        f.write(cmd)  # cmd needs Windows line endings to find its labels

    # the original docstring becomes comments, because line 2 is now the docstring
    m = re.match(r'\s*"""(.*?)"""\n', body, re.S)
    doc = "".join(f"# {line}".rstrip() + "\n" for line in m.group(1).strip("\n").split("\n")) if m else ""
    sh = SH_HEAD + doc + (body[m.end():] if m else body)
    path = os.path.join(DIST, "odus.sh")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(sh)
    os.chmod(path, 0o755)

    # the plain Python source, for people who'd rather run: python odus.py
    with open(os.path.join(DIST, "odus.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(src)

    print(f"Built Odus {version}:")
    for name in ("odus.cmd", "odus.sh", "odus.py"):
        print(f"  dist/{name}  ({os.path.getsize(os.path.join(DIST, name)) // 1024} KB)")
    print(f"Upload all three to a GitHub release tagged v{version}.")


if __name__ == "__main__":
    main()
