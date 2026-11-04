#!/usr/bin/env python3
"""
Odus - your whole computer, one command: apps, compression and downloads.

    odus update                  Standard: one thing at a time, default settings
    odus fast update             Fast: low CPU priority, a few parallel downloads
    odus fastplus update         Fast+: package managers run side by side
    odus ufa update-apps         Ultra-Fast Actions: everything at once, no mercy

Odus "understands" commands with simple rules and fuzzy matching (no AI model),
so it stays light enough for weak machines.
"""
from __future__ import annotations

import difflib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

VERSION = "0.1"
IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
OS_NAME = "windows" if IS_WIN else "macos" if IS_MAC else "linux"

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# --------------------------------------------------------------------- colors
if IS_WIN:
    os.system("")  # turns on ANSI colors in Windows consoles
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


# -------------------------------------------------------------------- presets
@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    managers_at_once: int   # package managers running side by side (0 = all)
    packages_at_once: int   # packages installed at once, where the manager allows it
    downloads: int          # parallel-download hint for managers that support it
    priority: str           # "low" | "normal" | "high"
    confirm: bool           # ask before changing anything


PRESETS = {
    "standard": Preset("standard", "Standard", 1, 1, 1, "normal", True),
    "fast": Preset("fast", "Fast", 1, 1, 3, "low", True),
    "fastplus": Preset("fastplus", "Fast+", 2, 3, 10, "normal", True),
    "ufa": Preset("ufa", "Ultra-Fast Actions", 0, 8, 20, "high", False),
}
PRESET_NAMES = {
    "standard": ["standard", "std", "normal", "default", "regular", "slow"],
    "fast": ["fast", "quick", "f"],
    "fastplus": ["fastplus", "fast+", "fastp", "f+", "fp", "faster", "quicker", "fastpls"],
    "ufa": ["ufa", "uf", "ultra", "ultrafast", "ultra-fast", "ultra-fast-actions", "ultrafastactions",
            "fastest", "turbo", "max", "nomercy", "no-mercy", "godmode", "god-mode"],
}

# -------------------------------------------------------------------- actions
VERBS = {
    "update": ["update", "upgrade", "up", "upd", "upg", "patch", "sync", "renew",
               "updates", "upgrades", "update-apps", "upgrade-apps", "update-applications",
               "upgrade-applications", "update-all", "upgrade-all", "update-everything",
               "upgrade-everything", "update-programs", "upgrade-programs"],
    "install": ["install", "add", "get", "i", "setup", "inst", "grab",
                "obtain", "install-apps", "install-app", "put"],
    "uninstall": ["uninstall", "remove", "delete", "rm", "purge", "un", "erase", "del", "rem",
                  "uninst", "deinstall", "nuke", "yeet", "drop", "remove-app", "uninstall-app"],
    "search": ["search", "find", "lookup", "look", "s", "query", "seek", "look-for", "search-for"],
    "list": ["list", "ls", "installed", "show", "list-all", "list-apps", "installed-apps"],
    "managers": ["managers", "doctor", "detect", "status", "check", "info"],
    "compress": ["compress", "shrink", "squeeze", "optimize", "optimise", "reduce", "compress-files",
                 "compress-file", "compress-video", "compress-videos", "compress-photo", "compress-photos",
                 "compress-images", "compress-media", "compress-pics"],
    "compress-app": ["compress-app", "compress-apps", "compact", "compact-app", "shrink-app",
                     "app-compress", "compress-program", "compress-programs"],
    "decompress-app": ["decompress-app", "decompress-apps", "uncompress-app", "uncompact", "decompact",
                       "expand-app", "restore-app"],
    "download": ["download", "dl", "fetch", "clone", "yt", "youtube", "ytdl", "download-video",
                 "download-audio", "save-video", "get-video", "download-repo"],
    "path": ["path", "paths"],
    "path-add": ["add-to-path", "path-add", "addpath"],
    "path-remove": ["remove-from-path", "path-remove", "rmpath"],
    "refresh": ["refresh", "live-refresh", "reload", "rehash", "refresh-path", "reload-path", "refresh-env"],
    "help": ["help", "h", "?", "commands", "usage", "man"],
    "version": ["version", "ver"],
}


# ------------------------------------------------------------- typo engine
def norm(word: str) -> str:
    """update-apps, update_apps, Update.Apps, updateapps -> updateapps"""
    return "".join(ch for ch in word.lower() if ch not in "-_. ")


_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl;", "zxcvbnm,./"]
NEAR: dict = {}
for _r, _row in enumerate(_ROWS):
    for _i, _ch in enumerate(_row):
        spots = [(_r, _i - 1), (_r, _i + 1), (_r - 1, _i), (_r - 1, _i + 1), (_r + 1, _i - 1), (_r + 1, _i)]
        NEAR[_ch] = "".join(_ROWS[r][i] for r, i in spots
                            if 0 <= r < len(_ROWS) and 0 <= i < len(_ROWS[r]) and _ROWS[r][i].isalpha())
_SOUNDS_ALIKE = {"a": "e", "e": "ai", "i": "ey", "o": "u", "u": "o", "y": "i", "c": "ks", "k": "c", "s": "cz"}


def typo_variants(word: str) -> set:
    """Every single-mistake version of a word: missed key, double tap, swapped
    letters, neighbouring key, extra neighbouring key, sound-alike letter."""
    out = set()
    n = len(word)
    for i, ch in enumerate(word):
        if n >= 4:
            out.add(word[:i] + word[i + 1:])                         # instal
        out.add(word[:i] + ch + word[i:])                            # innstall
        if i < n - 1:
            out.add(word[:i] + word[i + 1] + ch + word[i + 2:])      # isntall
        for k in NEAR.get(ch, "") + _SOUNDS_ALIKE.get(ch, ""):
            out.add(word[:i] + k + word[i + 1:])                     # inatall
            out.add(word[:i] + k + word[i:])                         # insrtall
            out.add(word[:i + 1] + k + word[i + 1:])
    out.discard(word)
    return {v for v in out if len(v) >= 3}


def build_table(groups: dict, avoid: set) -> tuple[dict, dict]:
    """exact words -> meaning, plus typo -> meaning (typos that could mean two
    different things, or clash with `avoid`, are dropped instead of guessed)."""
    exact = {norm(w): key for key, words in groups.items() for w in words}
    seen: dict = {}
    for key, words in groups.items():
        for w in words:
            if len(norm(w)) >= 3:
                for t in typo_variants(norm(w)):
                    seen.setdefault(t, set()).add(key)
    typos = {t: next(iter(keys)) for t, keys in seen.items()
             if len(keys) == 1 and t not in exact and t not in avoid}
    return exact, typos


_preset_exact = {norm(w) for ws in PRESET_NAMES.values() for w in ws}
_verb_exact = {norm(w) for ws in VERBS.values() for w in ws}
VERB_EXACT, VERB_TYPOS = build_table(VERBS, _preset_exact)
PRESET_EXACT, PRESET_TYPOS = build_table(PRESET_NAMES, _verb_exact)
for _t in set(VERB_TYPOS) & set(PRESET_TYPOS):  # ambiguous between a preset and a command
    del VERB_TYPOS[_t], PRESET_TYPOS[_t]
WORD_TO_VERB = VERB_EXACT  # kept for compatibility
FILLER = {"please", "pls", "the", "my", "all", "every", "everything", "app", "apps",
          "application", "applications", "package", "packages", "software", "and",
          "a", "an", "of", "for", "me", "now", "odus"}
# leading words someone might type before the actual verb
LEAD_IN = {"please", "pls", "can", "you", "could", "go", "just", "now", "odus"}


# ------------------------------------------------------------------- managers
@dataclass
class Manager:
    name: str
    exe: str
    systems: tuple
    upgrade: list
    upgrade_one: list
    install: list
    uninstall: list
    search: list
    listing: list
    refresh: list | None = None
    root: bool = False          # needs sudo / admin
    batch: bool = True          # accepts several packages in one call
    parallel_safe: bool = False  # several calls can run at the same time
    tune: Callable[[Preset], tuple[list, dict]] = lambda p: ([], {})

    def available(self) -> bool:
        return OS_NAME in self.systems and shutil.which(self.exe) is not None


def _apt_tune(p: Preset):
    args = []
    if p.downloads >= 10:
        args += ["-o", "Acquire::Queue-Mode=access"]  # one download queue per mirror
    if p.downloads >= 20:
        args += ["-o", "Acquire::http::Pipeline-Depth=20"]
    return args, {"DEBIAN_FRONTEND": "noninteractive"}


def _dnf_tune(p: Preset):
    args = []
    if p.downloads > 1:
        args.append(f"--setopt=max_parallel_downloads={min(p.downloads, 20)}")
    if p.downloads >= 10:
        args.append("--setopt=fastestmirror=True")
    return args, {}


def _zypper_tune(p: Preset):
    return [], ({"ZYPP_CURL2": "1", "ZYPP_PCK_PRELOAD": "1"} if p.downloads >= 3 else {})


def _brew_tune(p: Preset):
    env = {"HOMEBREW_NO_ENV_HINTS": "1"}
    if p.downloads > 1:
        env["HOMEBREW_DOWNLOAD_CONCURRENCY"] = str(p.downloads)
    if p.name != "standard":
        env["HOMEBREW_NO_AUTO_UPDATE"] = "1"
    if p.name == "ufa":
        env["HOMEBREW_NO_INSTALL_CLEANUP"] = "1"
    return [], env


WG_AGREE = ["--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]

MANAGERS = [
    # ---- Windows
    Manager("winget", "winget", ("windows",),
            refresh=["winget", "source", "update"],
            upgrade=["winget", "upgrade", "--all", "--silent", *WG_AGREE],
            upgrade_one=["winget", "upgrade", "--silent", *WG_AGREE],
            install=["winget", "install", "--silent", *WG_AGREE],
            uninstall=["winget", "uninstall", "--silent", "--disable-interactivity"],
            search=["winget", "search", "--accept-source-agreements"],
            listing=["winget", "list", "--accept-source-agreements"],
            batch=False, parallel_safe=True),
    Manager("scoop", "scoop", ("windows",),
            refresh=["scoop", "update"], upgrade=["scoop", "update", "*"],
            upgrade_one=["scoop", "update"], install=["scoop", "install"],
            uninstall=["scoop", "uninstall"], search=["scoop", "search"],
            listing=["scoop", "list"]),
    Manager("choco", "choco", ("windows",), root=True,
            upgrade=["choco", "upgrade", "all", "-y", "--no-progress"],
            upgrade_one=["choco", "upgrade", "-y", "--no-progress"],
            install=["choco", "install", "-y", "--no-progress"],
            uninstall=["choco", "uninstall", "-y"], search=["choco", "search"],
            listing=["choco", "list"]),
    # ---- Linux system managers
    Manager("apt", "apt-get", ("linux",), root=True,
            refresh=["apt-get", "update"], upgrade=["apt-get", "upgrade", "-y"],
            upgrade_one=["apt-get", "install", "--only-upgrade", "-y"],
            install=["apt-get", "install", "-y"], uninstall=["apt-get", "remove", "-y"],
            search=["apt-cache", "search"], listing=["apt", "list", "--installed"],
            tune=_apt_tune),
    Manager("dnf", "dnf", ("linux",), root=True,
            refresh=["dnf", "makecache"], upgrade=["dnf", "upgrade", "-y"],
            upgrade_one=["dnf", "upgrade", "-y"], install=["dnf", "install", "-y"],
            uninstall=["dnf", "remove", "-y"], search=["dnf", "search"],
            listing=["dnf", "list", "--installed"], tune=_dnf_tune),
    Manager("pacman", "pacman", ("linux",), root=True,
            upgrade=["pacman", "-Syu", "--noconfirm"],
            upgrade_one=["pacman", "-S", "--needed", "--noconfirm"],
            install=["pacman", "-S", "--needed", "--noconfirm"],
            uninstall=["pacman", "-R", "--noconfirm"], search=["pacman", "-Ss"],
            listing=["pacman", "-Q"]),
    Manager("zypper", "zypper", ("linux",), root=True,
            refresh=["zypper", "--non-interactive", "refresh"],
            upgrade=["zypper", "--non-interactive", "update"],
            upgrade_one=["zypper", "--non-interactive", "update"],
            install=["zypper", "--non-interactive", "install"],
            uninstall=["zypper", "--non-interactive", "remove"],
            search=["zypper", "search"], listing=["zypper", "search", "--installed-only"],
            tune=_zypper_tune),
    Manager("apk", "apk", ("linux",), root=True,
            refresh=["apk", "update"], upgrade=["apk", "upgrade"],
            upgrade_one=["apk", "add", "-u"], install=["apk", "add"],
            uninstall=["apk", "del"], search=["apk", "search"], listing=["apk", "info"]),
    # ---- Cross-distro / macOS
    Manager("brew", "brew", ("macos", "linux"),
            refresh=["brew", "update"], upgrade=["brew", "upgrade"],
            upgrade_one=["brew", "upgrade"], install=["brew", "install"],
            uninstall=["brew", "uninstall"], search=["brew", "search"],
            listing=["brew", "list"], tune=_brew_tune),
    Manager("flatpak", "flatpak", ("linux",),
            upgrade=["flatpak", "update", "-y", "--noninteractive"],
            upgrade_one=["flatpak", "update", "-y", "--noninteractive"],
            install=["flatpak", "install", "-y", "--noninteractive", "flathub"],
            uninstall=["flatpak", "uninstall", "-y", "--noninteractive"],
            search=["flatpak", "search"], listing=["flatpak", "list", "--app"]),
    Manager("snap", "snap", ("linux",), root=True,
            upgrade=["snap", "refresh"], upgrade_one=["snap", "refresh"],
            install=["snap", "install"], uninstall=["snap", "remove"],
            search=["snap", "find"], listing=["snap", "list"]),
]


# ------------------------------------------------------------- understanding
MODE_NAMES = {"multi": ["multi-package", "multipackage", "multi-packages", "multi", "multiple",
                        "multi-app", "multi-apps", "multiapp", "many", "mp", "bulk", "several"]}
MODE_EXACT, MODE_TYPOS = build_table(MODE_NAMES, set(VERB_EXACT) | set(PRESET_EXACT))
for _t in set(MODE_TYPOS) & (set(VERB_TYPOS) | set(PRESET_TYPOS)):  # never guess when it's unclear
    MODE_TYPOS.pop(_t, None)
    VERB_TYPOS.pop(_t, None)
    PRESET_TYPOS.pop(_t, None)
for _t in MODE_EXACT:
    VERB_TYPOS.pop(_t, None)
    PRESET_TYPOS.pop(_t, None)


@dataclass
class App:
    """One app the user means, e.g. 'Adobe Premiere 2026'."""
    name: str
    spaced: list   # names to try with managers that accept spaces (winget)
    plain: list    # names to try with managers whose IDs can't have spaces


def make_apps(words: list, multi: bool) -> list:
    """Standard mode: all the words are ONE app ("Adobe Premiere 2026").
    Multi-package mode: each word is its own app and dashes stand for spaces
    ("Adobe-Premiere-2026 vlc" -> "Adobe Premiere 2026" and "vlc")."""
    def uniq(xs):
        return list(dict.fromkeys(x for x in xs if x))
    if not words:
        return []
    if multi:
        apps = []
        for w in words:
            spaced = " ".join(p for p in w.replace("_", "-").split("-") if p)
            apps.append(App(spaced or w, uniq([spaced, w]), uniq([w])))
        return apps
    name = " ".join(words)
    return [App(name, [name], uniq(["-".join(words)]))]


@dataclass
class Request:
    preset: Preset
    verb: str
    args: list
    dry_run: bool = False
    yes: bool = False
    only: str | None = None
    multi: bool = False
    notes: list = field(default_factory=list)
    opts: dict = field(default_factory=dict)
    raw: list = field(default_factory=list)

    @property
    def apps(self) -> list:
        return make_apps(self.args, self.multi)


def _fuzzy(word: str, choices, cutoff: float):
    hit = difflib.get_close_matches(word, list(choices), n=1, cutoff=cutoff)
    return hit[0] if hit else None


def _lookup(word: str, exact: dict, typos: dict, cutoff: float, label: str, fuzzy: bool = True):
    """exact word -> typo table -> (optionally) fuzzy guess, trying the whole
    word and then just its first part (update-my-apps -> update)."""
    parts = [norm(word)]
    head = norm(word.lower().replace("_", "-").split("-")[0])
    if head and head != parts[0]:
        parts.append(head)
    for w in parts:
        if w in exact:
            return exact[w], None
    for w in parts:
        if w in typos:
            return typos[w], f"'{word}' -> {label}'{typos[w]}'"
    if fuzzy:
        for w in parts:
            guess = _fuzzy(w, exact, cutoff) if len(w) >= 3 else None
            if guess:
                return exact[guess], f"'{word}' -> {label}'{exact[guess]}'"
    return None, None


def match_preset(word: str, fuzzy: bool = True):
    return _lookup(word, PRESET_EXACT, PRESET_TYPOS, 0.8, "preset ", fuzzy)


def match_verb(word: str, fuzzy: bool = True):
    return _lookup(word, VERB_EXACT, VERB_TYPOS, 0.75, "", fuzzy)


def match_mode(word: str, fuzzy: bool = True):
    if not fuzzy:  # "multi-app" must not be split into "multi"
        w = norm(word)
        if w in MODE_EXACT:
            return MODE_EXACT[w], None
        if w in MODE_TYPOS:
            return MODE_TYPOS[w], f"'{word}' -> 'multi-package'"
        return None, None
    hit = _fuzzy(norm(word), MODE_EXACT, 0.8) if len(norm(word)) >= 4 else None
    return (MODE_EXACT[hit], f"'{word}' -> 'multi-package'") if hit else (None, None)


def parse(argv: list) -> Request:
    flags = {"dry": False, "yes": False, "only": None}
    opts: dict = {}
    words = []
    it = iter(argv)
    for a in it:
        if a in ("-n", "--dry-run", "--dry"):
            flags["dry"] = True
        elif a in ("-y", "--yes"):
            flags["yes"] = True
        elif a in ("-h", "--help"):
            words = ["help"]
            break
        elif a in ("-v", "--version"):
            words = ["version"]
            break
        elif a in ("--with", "--using", "-m"):
            flags["only"] = next(it, None)
        elif a.startswith("--with="):
            flags["only"] = a.split("=", 1)[1]
        elif a in ("--multi", "--multi-package"):
            words.insert(0, "multi-package")
        elif a in ("--to", "-o", "--out", "--dest"):
            opts["to"] = next(it, None)
        elif a in ("--audio", "--mp3", "--audio-only"):
            opts["audio"] = True
        elif a == "--replace":
            opts["replace"] = True
        elif a == "--shallow":
            opts["shallow"] = True
        elif a == "--algo":
            opts["algo"] = next(it, None)
        else:
            words.append(a)

    notes, preset, multi, verb = [], None, False, None

    # Read the words before the command: preset, "multi-package", "please"...
    # Sure matches (exact or known typo) beat guesses, so try those first.
    while words and verb is None:
        w = words[0]
        for fuzzy in (False, True):
            found = None
            v, note = match_verb(w, fuzzy)
            if v and not (preset is None and match_preset(w, False)[0]):
                verb, found = v, note or ""
                break
            m, note = match_mode(w, fuzzy)
            if m and not multi:
                multi, found = True, note or ""
                break
            if preset is None:
                p, note = match_preset(w, fuzzy)
                if p:
                    preset, found = PRESETS[p], note or ""
                    break
            if norm(w) in LEAD_IN:
                found = ""
                break
        if found is None:
            break
        if found:
            notes.append(found)
        words = words[1:]
        # multi-word presets: "fast plus", "ultra fast actions"
        if found is not None and preset and verb is None:
            if preset.name == "fast" and words and norm(words[0]) in ("plus", "+", "puls", "pluss", "plu"):
                preset, words = PRESETS["fastplus"], words[1:]
            if preset.name == "ufa":
                while words and norm(words[0]) in ("fast", "action", "actions", "mode"):
                    words = words[1:]
    # "odus install multi-package a b" works too
    if verb and words and match_mode(words[0], False)[0]:
        multi, words = True, words[1:]

    preset = preset or PRESETS["standard"]
    if verb is None:
        verb = "help" if not words else "unknown"
    if verb in ("update", "list", "managers"):
        words = [w for w in words if w.lower() not in FILLER]
    elif verb in ("install", "uninstall", "search"):
        while words and words[0].lower() in {"please", "pls", "the"}:
            words = words[1:]
    return Request(preset, verb, words, flags["dry"], flags["yes"], flags["only"], multi, notes, opts, list(argv))


# ----------------------------------------------------------------- execution
_print_lock = threading.Lock()
_sudo_ok = False
_skipped_admin: list = []  # admin-only managers left out because this terminal isn't admin

OK, FAILED, NOT_FOUND, AMBIGUOUS, CANCELLED, SKIPPED = 0, 1, 1001, 1002, 1003, 1004

# Some managers print "not found" but still exit as if it worked (scoop does).
_NOT_FOUND = re.compile(
    r"isn't installed|is not installed|no installed package found|no package found|"
    r"couldn't find manifest|could not find|unable to locate package|no match for argument|"
    r"target not found|no available formula|no formulae or casks found|was not found|"
    r"no such package|not found in any|nothing matches|no matching|unknown package|"
    r"is not a known|has no installation candidate|repository not found", re.I)
_AMBIGUOUS = re.compile(r"multiple (installed )?packages found|more than one package", re.I)
_ERROR_LINE = re.compile(r"^\s*(error|fatal)\b", re.I)


def say(msg: str = ""):
    with _print_lock:
        try:
            print(msg, flush=True)
        except OSError:  # output closed (e.g. piped into head) - keep working
            pass


def is_admin() -> bool:
    if IS_WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def build_argv(m: Manager, base: list, preset: Preset, tuned: bool, extra: list = ()):
    """Turn a manager command into the final argv (speed tuning, sudo, priority)."""
    args, env = m.tune(preset) if tuned else ([], {})
    argv = list(base)
    if args and argv[0] == m.exe:
        argv = argv[:1] + args + argv[1:]
    argv += list(extra)
    exe_path = shutil.which(argv[0])
    if exe_path:
        argv[0] = exe_path
    if m.root and not is_admin() and not IS_WIN:
        prefix = ["sudo"]
        if preset.priority == "high":
            prefix += ["nice", "-n", "-10"]
        if env:
            prefix += ["env", *[f"{k}={v}" for k, v in env.items()]]
        argv = prefix + argv
        env = {}
    return argv, env


_SPINNER = set("-\\|/ ") | set("█▒░▓ ")


def _show(a: str) -> str:
    return f'"{a}"' if " " in a else a


_PROGRESS = re.compile(
    r"^\s*(frame=|size=|\[download\]\s+[\d.]+%|receiving objects|resolving deltas|updating files|"
    r"counting objects|compressing objects|remote: (counting|compressing|enumerating)|[\d.]+\s*%)", re.I)
_ERRORISH = re.compile(r"error|fail|denied|\[err", re.I)


def run(tag: str, argv: list, env: dict, preset: Preset, dry: bool, check: bool = False,
        cwd: str | None = None, quiet: bool = False, capture: list | None = None) -> int:
    """Run a command, stream its output, and return OK / FAILED / NOT_FOUND /
    AMBIGUOUS. With check=True the output is read too, so a manager that says
    'not installed' but exits 0 still counts as a failure. quiet=True only
    shows problems; progress lines are shown at most every 2 seconds."""
    shown = " ".join(os.path.basename(argv[0]) if i == 0 else _show(a) for i, a in enumerate(argv))
    if dry or not quiet:
        say(f"{c(f'[{tag}]', '36')} {c('$ ' + shown, '2')}")
    if dry:
        return OK
    kw = {}
    if IS_WIN:
        kw["creationflags"] = {"low": 0x4000, "normal": 0, "high": 0x80}[preset.priority]
    elif preset.priority == "low":
        kw["preexec_fn"] = lambda: os.nice(10)
    try:
        p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, env={**os.environ, **env}, cwd=cwd,
                             text=True, encoding="utf-8", errors="replace", bufsize=1, **kw)
    except OSError as e:
        say(f"{c(f'[{tag}]', '36')} {c(f'could not start: {e}', '31')}")
        return FAILED
    last, not_found, ambiguous, error, last_progress = None, False, False, False, 0.0
    for line in p.stdout:
        line = line.rstrip()
        if not line.strip() or set(line) <= _SPINNER or line == last:
            continue  # drop progress spinners and repeated lines
        last = line
        if capture is not None:
            capture.append(line)
        if check:
            not_found = not_found or bool(_NOT_FOUND.search(line))
            ambiguous = ambiguous or bool(_AMBIGUOUS.search(line))
            error = error or bool(_ERROR_LINE.search(line))
        if _PROGRESS.search(line) and "100%" not in line:
            if time.time() - last_progress < 2:
                continue
            last_progress = time.time()
        if quiet and not _ERRORISH.search(line):
            continue
        say(f"{c(f'[{tag}]', '36')} {line}")
    rc = p.wait()
    if ambiguous:
        return AMBIGUOUS
    if not_found:
        return NOT_FOUND
    if rc != 0 or (check and error):
        return FAILED
    return OK


def ensure_privileges(mgrs: list, dry: bool) -> list:
    """Ask for sudo once up front; skip admin-only managers on Windows without admin."""
    global _sudo_ok
    usable = []
    needs = [m for m in mgrs if m.root and not is_admin()]
    if IS_WIN:
        for m in mgrs:
            if m not in needs:
                usable.append(m)
            elif len(mgrs) == 1:  # it's the only one (e.g. --with choco), so say why right away
                say(c(f"{m.name} needs an admin terminal (right-click > Run as administrator).", "33"))
            elif m.name not in _skipped_admin:
                _skipped_admin.append(m.name)  # only mentioned later if it matters
        return usable
    if needs and not dry and not _sudo_ok:
        say(c("Some package managers need sudo. Asking once:", "33"))
        _sudo_ok = subprocess.call(["sudo", "-v"]) == 0
        if not _sudo_ok:
            say(c("sudo failed, skipping: " + ", ".join(m.name for m in needs), "31"))
            return [m for m in mgrs if m not in needs]
    return list(mgrs)


def pool_size(preset: Preset, n: int) -> int:
    return max(1, n if preset.managers_at_once == 0 else min(preset.managers_at_once, n))


def confirm(req: Request, what: str) -> bool:
    if req.dry_run or req.yes or not req.preset.confirm or not sys.stdin.isatty():
        return True
    try:
        ans = input(f"{what} Go ahead? [Y/n] ").strip().lower()
    except EOFError:
        return False
    return ans in ("", "y", "yes")


def names(apps: list) -> str:
    return ", ".join(f'"{a.name}"' for a in apps)


# ----------------------------------------------------------------- commands
def detected(req: Request) -> list:
    mgrs = [m for m in MANAGERS if m.available()]
    if req.only:
        mgrs = [m for m in mgrs if m.name == req.only.lower()]
        if not mgrs:
            say(c(f"'{req.only}' isn't available here. Run 'odus managers' to see what is.", "31"))
    return mgrs


def try_app(app: App, chain: list, base_of: Callable, p: Preset, dry: bool, tuned: bool):
    """Try one app with each manager (and each spelling of its name) until one works."""
    t = time.time()
    status, tried = NOT_FOUND, []
    for m in chain:
        for query in (app.spaced if m.name == "winget" else app.plain):
            tried.append(m.name)
            status = run(f"{m.name}:{app.name}", *build_argv(m, base_of(m), p, tuned, [query]), p, dry, check=True)
            if status == OK:
                return f"{app.name} ({m.name})", OK, time.time() - t
            if status == AMBIGUOUS:
                say(c(f'"{app.name}": {m.name} found several matching apps. Use the exact name or ID '
                      f'(odus search {app.name}).', "33"))
                return app.name, AMBIGUOUS, time.time() - t
            if status == FAILED:
                break  # found but it failed: don't retry the same manager with another spelling
        if m is not chain[-1]:
            say(c(f'"{app.name}": not done with {m.name}, trying {chain[chain.index(m) + 1].name}', "33"))
    return f"{app.name} (checked {', '.join(dict.fromkeys(tried))})", status, time.time() - t


def run_apps(req: Request, chain: list, base_of: Callable, tuned: bool):
    p = req.preset
    apps = req.apps
    workers = p.packages_at_once if chain[0].parallel_safe else 1
    with ThreadPoolExecutor(max(1, min(workers, len(apps)))) as ex:
        return list(ex.map(lambda a: try_app(a, chain, base_of, p, req.dry_run, tuned), apps))


def do_update(req: Request) -> int:
    mgrs = ensure_privileges(detected(req), req.dry_run)
    if not mgrs:
        say("No package managers found.")
        return FAILED
    if req.apps:
        if not confirm(req, f"Update {names(req.apps)}."):
            return CANCELLED
        return summary(req, run_apps(req, mgrs, lambda m: m.upgrade_one, True))
    if not confirm(req, f"Update all apps with {', '.join(m.name for m in mgrs)}."):
        return CANCELLED

    def job(m: Manager):
        t = time.time()
        rc = OK
        if m.refresh:
            rc = run(m.name, *build_argv(m, m.refresh, req.preset, True), req.preset, req.dry_run)
        if rc == OK:
            rc = run(m.name, *build_argv(m, m.upgrade, req.preset, True), req.preset, req.dry_run)
        return m.name, rc, time.time() - t

    with ThreadPoolExecutor(pool_size(req.preset, len(mgrs))) as ex:
        results = list(ex.map(job, mgrs))
    rc = summary(req, results)
    if _skipped_admin:
        say(c(f"  (apps from {', '.join(_skipped_admin)} weren't updated - that needs an admin terminal)", "2"))
    return rc


def do_install(req: Request) -> int:
    if not req.apps:
        say("Tell me what to install, e.g. " + c("odus install firefox", "1"))
        return FAILED
    chain = ensure_privileges(detected(req), req.dry_run)
    if not chain:
        say("No package managers found.")
        return FAILED
    fallback = f" (falls back to {', '.join(m.name for m in chain[1:])})" if chain[1:] else ""
    if not confirm(req, f"Install {names(req.apps)} using {chain[0].name}{fallback}."):
        return CANCELLED
    primary, p, apps = chain[0], req.preset, req.apps

    # several apps in one go first, where the manager supports it
    if primary.batch and len(apps) > 1:
        t0 = time.time()
        rc = run(primary.name, *build_argv(primary, primary.install, p, True, [a.plain[0] for a in apps]),
                 p, req.dry_run, check=True)
        if rc == OK:
            return summary(req, [(f"{a.name} ({primary.name})", OK, time.time() - t0) for a in apps])
        say(c("Installing them together failed, trying each app on its own...", "33"))
    return summary(req, run_apps(req, chain, lambda m: m.install, True))


def do_uninstall(req: Request) -> int:
    if not req.apps:
        say("Tell me what to remove, e.g. " + c("odus uninstall vlc", "1"))
        return FAILED
    chain = ensure_privileges(detected(req), req.dry_run)
    if not chain:
        say("No package managers found.")
        return FAILED
    if not confirm(req, f"Remove {names(req.apps)}."):
        return CANCELLED
    return summary(req, run_apps(req, chain, lambda m: m.uninstall, False))


def do_query(req: Request, field_name: str) -> int:
    if field_name == "search" and not req.args:
        say("Tell me what to look for, e.g. " + c("odus search browser", "1"))
        return FAILED
    mgrs = detected(req)
    p = req.preset
    query = [" ".join(req.args)] if field_name == "search" else []

    def job(m: Manager):
        argv, env = build_argv(m, getattr(m, field_name), p, False, query)
        if argv[0] == "sudo":  # searching/listing never needs root
            argv = argv[argv.index(shutil.which(m.exe) or m.exe):]
        return m.name, run(m.name, argv, env, p, req.dry_run), 0

    with ThreadPoolExecutor(pool_size(p, len(mgrs) or 1)) as ex:
        list(ex.map(job, mgrs))
    return OK


def do_managers(req: Request) -> int:
    say(f"Odus v{VERSION} on {OS_NAME}  (admin: {'yes' if is_admin() else 'no'})\n")
    for m in MANAGERS:
        if OS_NAME not in m.systems:
            continue
        ok = m.available()
        mark = c("found  ", "32") if ok else c("missing", "2")
        say(f"  {mark}  {m.name:<8} {'(needs admin/sudo)' if m.root else ''}")
    say("\nPresets:")
    for p in PRESETS.values():
        mg = "all" if p.managers_at_once == 0 else p.managers_at_once
        say(f"  {p.name:<9} managers at once: {mg:<4} downloads: {p.downloads:<3} "
            f"priority: {p.priority:<7} asks first: {'yes' if p.confirm else 'no'}")
    return OK


_LABEL = {OK: ("OK       ", "32"), FAILED: ("FAILED   ", "31"),
          NOT_FOUND: ("NOT FOUND", "31"), AMBIGUOUS: ("UNCLEAR  ", "33"), SKIPPED: ("SKIPPED  ", "33")}


def summary(req: Request, results: list) -> int:
    say("")
    worst = OK
    for name, rc, secs in results:
        text, color = _LABEL.get(rc, _LABEL[FAILED])
        say(f"  {c(text, color)}  {name}  {c(f'{secs:.1f}s', '2')}")
        if rc not in (OK, SKIPPED) and worst in (OK, NOT_FOUND):
            worst = rc
    if worst in (NOT_FOUND, FAILED) and _skipped_admin and req.verb in ("install", "uninstall", "update"):
        say(c(f"\n{', '.join(_skipped_admin)} wasn't tried because it needs an admin terminal "
              f"(right-click > Run as administrator) - it might have it.", "2"))
    if worst == NOT_FOUND and not req.multi and len(req.args) > 1 and req.verb in ("install", "uninstall", "update"):
        say(c(f"\nTip: Odus read that as ONE app called \"{' '.join(req.args)}\". For several apps use\n"
              f"     odus {req.preset.name + ' ' if req.preset.name != 'standard' else ''}"
              f"multi-package {req.verb} {' '.join(req.args)}", "33"))
    return worst


# ================================================================== extras
SELF = os.path.realpath(__file__)  # odus.py, or the single-file odus.cmd / odus.sh
HERE = os.path.dirname(SELF)
SINGLE_FILE = SELF.lower().endswith((".cmd", ".sh"))
CPUS = os.cpu_count() or 2
CONFIG_DIR = (os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Odus") if IS_WIN
              else os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "odus"))
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
START_ENV = dict(os.environ)  # what the terminal gave us, to work out what changed
SKIP_ENV = {"PSMODULEPATH", "PROMPT", "TEMP", "TMP", "ODUS_REFRESH_FILE", "USERNAME", "USERPROFILE"}


def load_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        say(c(f"Couldn't save Odus settings: {e}", "33"))


def ask_yes(question: str, req: Request | None = None) -> bool:
    """Yes/no question. --yes and the ufa preset (never asks) count as yes."""
    if req and (req.yes or not req.preset.confirm):
        return True
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [Y/n] ").strip().lower() in ("", "y", "yes")
    except EOFError:
        return False


def quote_arg(a: str) -> str:
    return f'"{a}"' if re.search(r"[\s&|<>^]", a) else a


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ------------------------------------------------------------ Live Refresh
def _key(p: str) -> str:
    return os.path.normcase(os.path.normpath(p)).rstrip("\\/") if p else ""


def _expand(s: str) -> str:
    if IS_WIN:
        import ctypes
        buf = ctypes.create_unicode_buffer(32767)
        return buf.value if ctypes.windll.kernel32.ExpandEnvironmentStringsW(s, buf, 32767) else s
    return os.path.expandvars(s)


def _win_read_env(scope: str) -> dict:
    """Environment variables saved in the registry ('user' or 'machine')."""
    import winreg
    hive, sub = ((winreg.HKEY_CURRENT_USER, "Environment") if scope == "user" else
                 (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
    out = {}
    try:
        with winreg.OpenKey(hive, sub) as k:
            i = 0
            while True:
                try:
                    name, val, kind = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if isinstance(val, str):
                    out[name.upper()] = _expand(val) if kind == winreg.REG_EXPAND_SZ else val
    except OSError:
        pass
    return out


def system_env() -> dict:
    """What a brand-new terminal would get right now."""
    if IS_WIN:
        env = _win_read_env("machine")
        for k, v in _win_read_env("user").items():
            env[k] = (env.get("PATH", "").rstrip(";") + ";" + v) if k == "PATH" else v
        return env
    shell = os.environ.get("SHELL") or "/bin/sh"
    try:
        out = subprocess.run([shell, "-ilc", 'printf "__ODUS__%s__ODUS__" "$PATH"'], capture_output=True,
                             text=True, timeout=8, stdin=subprocess.DEVNULL).stdout
        m = re.search(r"__ODUS__(.*?)__ODUS__", out, re.S)
        return {"PATH": m.group(1)} if m else {}
    except (OSError, subprocess.SubprocessError):
        return {}


def fresh_env() -> dict:
    """This session's environment brought up to date with the system. PATH
    entries that only this session has (like a Python venv) are kept if the
    folder still exists; folders that were deleted or moved are dropped."""
    sysenv = system_env()
    if not sysenv:
        return {}
    sep = os.pathsep
    sys_parts = [p for p in sysenv.get("PATH", "").split(sep) if p]
    known = {_key(p) for p in sys_parts}
    extras = [p for p in os.environ.get("PATH", "").split(sep)
              if p and _key(p) not in known and os.path.isdir(p)]
    seen, merged = set(), []
    for p in extras + sys_parts:
        if _key(p) not in seen:
            seen.add(_key(p))
            merged.append(p)
    new = {"PATH": sep.join(merged)}
    for k, v in sysenv.items():
        if k.upper() not in SKIP_ENV and k.upper() != "PATH" and v:
            new[k] = v
    return new


def live_refresh_self():
    """Let Odus itself see tools installed since the terminal was opened."""
    for k, v in fresh_env().items():
        os.environ[k] = v


def env_diff() -> dict:
    """Variables that differ between the terminal (START_ENV) and the system now."""
    diff = {}
    for k, v in fresh_env().items():
        old = START_ENV.get(k)
        if k == "PATH" and old is not None:
            if {_key(p) for p in old.split(os.pathsep) if p} == {_key(p) for p in v.split(os.pathsep) if p}:
                continue  # same folders, maybe in another order: leave the terminal's order alone
        if old != v:
            diff[k] = v
    return diff


def write_shell_refresh(diff: dict | None = None) -> dict:
    """Hand the changes to the launcher (odus.cmd / odus.ps1 / the shell
    function), which applies them to the terminal you're typing in."""
    target = START_ENV.get("ODUS_REFRESH_FILE")
    diff = env_diff() if diff is None else diff
    if not target or not diff:
        return diff
    ext = os.path.splitext(target)[1].lower()
    try:
        if ext == ".cmd":
            import ctypes
            cp = ctypes.windll.kernel32.GetConsoleOutputCP() or 437
            lines = [f'set "{k}={v.replace("%", "%%")}"' for k, v in diff.items()]
            with open(target, "w", encoding=f"cp{cp}", errors="replace", newline="\r\n") as f:
                f.write("\n".join(lines) + "\n")
        elif ext == ".ps1":
            lines = [f"Set-Item -LiteralPath 'Env:{k}' -Value '{v.replace(chr(39), chr(39) * 2)}'"
                     for k, v in diff.items()]
            with open(target, "w", encoding="utf-8-sig") as f:
                f.write("\n".join(lines) + "\n")
        else:
            q = lambda v: "'" + v.replace("'", "'\\''") + "'"
            lines = [f"export {k}={q(v)}" for k, v in diff.items() if re.fullmatch(r"[A-Za-z_]\w*", k)]
            with open(target, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
    except (OSError, LookupError):
        pass
    return diff


def describe_diff(diff: dict) -> list:
    lines = []
    if "PATH" in diff:
        old = {_key(p) for p in START_ENV.get("PATH", "").split(os.pathsep) if p}
        new_parts = [p for p in diff["PATH"].split(os.pathsep) if p]
        new = {_key(p) for p in new_parts}
        added = [p for p in new_parts if _key(p) not in old]
        removed = [p for p in START_ENV.get("PATH", "").split(os.pathsep) if p and _key(p) not in new]
        lines += [f"  + PATH {p}" for p in added] + [f"  - PATH {p}  (gone)" for p in removed]
    lines += [f"  ~ {k}" for k in diff if k != "PATH"]
    return lines


# ---------------------------------------------------------------- PATH setup
PS1_MARK = "# Odus launcher for PowerShell"
_PS1_TARGET = '-x "$PSScriptRoot\\odus.cmd"' if SELF.lower().endswith(".cmd") else '"$PSScriptRoot\\odus.py"'
PS1 = PS1_MARK + r""" (written by Odus; turns on Live Refresh)
$env:ODUS_REFRESH_FILE = Join-Path $env:TEMP ("odus-refresh-" + [guid]::NewGuid().ToString("N") + ".ps1")
if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 TARGET @args } else { & python TARGET @args }""".replace("TARGET", _PS1_TARGET) + r"""
$odusRc = $LASTEXITCODE
if (Test-Path -LiteralPath $env:ODUS_REFRESH_FILE) { . $env:ODUS_REFRESH_FILE; Remove-Item -LiteralPath $env:ODUS_REFRESH_FILE -Force }
Remove-Item Env:ODUS_REFRESH_FILE -ErrorAction SilentlyContinue
$global:LASTEXITCODE = $odusRc
"""
RC_BLOCK = """# >>> odus >>>
# Added by Odus: puts ~/.local/bin on PATH and turns on Live Refresh.
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
odus() {
  ODUS_REFRESH_FILE="$(mktemp "${TMPDIR:-/tmp}/odus-refresh.XXXXXX")" && export ODUS_REFRESH_FILE
  command odus "$@"
  __odus_rc=$?
  if [ -s "$ODUS_REFRESH_FILE" ]; then . "$ODUS_REFRESH_FILE"; fi
  rm -f "$ODUS_REFRESH_FILE"; unset ODUS_REFRESH_FILE
  hash -r 2>/dev/null
  return $__odus_rc
}
# <<< odus <<<
"""


def _ps_scripts_allowed() -> bool:
    """Can Windows PowerShell run a local .ps1? (Read-only check; Odus never changes this.)"""
    import winreg
    def read(hive, sub):
        try:
            with winreg.OpenKey(hive, sub) as k:
                return str(winreg.QueryValueEx(k, "ExecutionPolicy")[0])
        except OSError:
            return None
    gpo = r"SOFTWARE\Policies\Microsoft\Windows\PowerShell"
    shell = r"Software\Microsoft\PowerShell\1\ShellIds\Microsoft.PowerShell"
    pol = (read(winreg.HKEY_LOCAL_MACHINE, gpo) or read(winreg.HKEY_CURRENT_USER, gpo) or
           read(winreg.HKEY_CURRENT_USER, shell) or read(winreg.HKEY_LOCAL_MACHINE, shell) or "Restricted")
    return pol.lower() in ("remotesigned", "unrestricted", "bypass")


def sync_ps1():
    """Keep odus.ps1 only while PowerShell is allowed to run it; otherwise it
    would block the working odus.cmd in PowerShell."""
    if not IS_WIN:
        return
    path = os.path.join(HERE, "odus.ps1")
    try:
        current = open(path, encoding="utf-8-sig").read() if os.path.exists(path) else None
        if _ps_scripts_allowed():
            if current != PS1:
                with open(path, "w", encoding="utf-8-sig", newline="\r\n") as f:
                    f.write(PS1)
        elif current is not None and current.startswith(PS1_MARK):
            os.remove(path)
    except OSError:
        pass


def _win_user_path_raw():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
        try:
            return winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ


def _win_set_user_path(new: str) -> str:
    """Write the user PATH straight to the registry (never setx, which cuts
    PATH at 1024 characters). Keeps the value type and saves a backup."""
    import ctypes
    import winreg
    raw, kind = _win_user_path_raw()
    os.makedirs(CONFIG_DIR, exist_ok=True)
    backup = os.path.join(CONFIG_DIR, f"PATH-backup-{time.strftime('%Y%m%d-%H%M%S')}.txt")
    with open(backup, "w", encoding="utf-8") as f:
        f.write(raw)
    if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
        kind = winreg.REG_EXPAND_SZ
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Path", 0, kind, new)
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000,
                                             ctypes.byref(ctypes.c_size_t()))
    return backup


def _rc_files() -> list:
    home = os.path.expanduser("~")
    shell = os.path.basename(os.environ.get("SHELL", ""))
    if shell == "zsh":
        names = [".zshrc"]
    elif shell == "bash":
        names = [".bashrc"] + ([".bash_profile"] if IS_MAC else [])
    else:
        names = [".profile"]
    return [os.path.join(home, n) for n in names]


def _write_rc_block(path: str, add: bool):
    try:
        text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    except OSError:
        return
    text = re.sub(r"\n*# >>> odus >>>.*?# <<< odus <<<\n?", "\n", text, flags=re.S).rstrip("\n")
    if add:
        text = (text + "\n\n" if text else "") + RC_BLOCK
    with open(path, "w", encoding="utf-8") as f:
        f.write(text if text.endswith("\n") else text + "\n")


def on_path() -> bool:
    here = _key(HERE)
    if IS_WIN:
        parts = _win_user_path_raw()[0].split(";") + _win_read_env("machine").get("PATH", "").split(";")
        return any(_key(_expand(p)) == here for p in parts if p)
    link = os.path.expanduser("~/.local/bin/odus")
    return os.path.islink(link) and _key(os.path.realpath(link)) == _key(SELF)


# When run from the source (odus.py) on Windows, 'odus' needs a small odus.cmd next to it.
SOURCE_CMD = """@echo off
rem Odus launcher (written by Odus for running from source). No setlocal, so Live Refresh can update this window.
set "ODUS_REFRESH_FILE=%TEMP%\\odus-refresh-%RANDOM%%RANDOM%.cmd"
where py >nul 2>nul && goto :use_py
python "%~dp0odus.py" %*
goto :after
:use_py
py -3 "%~dp0odus.py" %*
:after
set "ODUS_RC=%errorlevel%"
if exist "%ODUS_REFRESH_FILE%" call "%ODUS_REFRESH_FILE%"
if exist "%ODUS_REFRESH_FILE%" del "%ODUS_REFRESH_FILE%" >nul 2>nul
set "ODUS_REFRESH_FILE="
set "ODUS_RC=" & exit /b %ODUS_RC%
"""


def path_add() -> bool:
    if on_path():
        say(c("Odus is already on your PATH.", "32"))
        sync_ps1()
        return True
    try:
        if IS_WIN:
            if not SINGLE_FILE and not os.path.exists(os.path.join(HERE, "odus.cmd")):
                with open(os.path.join(HERE, "odus.cmd"), "w", encoding="ascii", newline="\r\n") as f:
                    f.write(SOURCE_CMD)
            raw, _ = _win_user_path_raw()
            backup = _win_set_user_path((raw.rstrip(";") + ";" if raw else "") + HERE)
            os.environ["PATH"] = os.environ.get("PATH", "").rstrip(";") + ";" + HERE
            sync_ps1()
            say(c(f"Added {HERE} to your PATH.", "32") + c(f" (old PATH saved in {backup})", "2"))
            say("Type 'odus' from any folder. This terminal picks it up right away when you use odus.cmd;")
            say("other open terminals need reopening once.")
            return True
        bindir = os.path.expanduser("~/.local/bin")
        os.makedirs(bindir, exist_ok=True)
        launcher = SELF  # odus.sh, or odus.py (it has its own #! line)
        os.chmod(launcher, os.stat(launcher).st_mode | 0o111)
        link = os.path.join(bindir, "odus")
        if os.path.lexists(link):
            os.remove(link)
        os.symlink(launcher, link)
        for rc in _rc_files():
            _write_rc_block(rc, True)
        say(c(f"Linked {link} -> {launcher} and turned on Live Refresh in {', '.join(_rc_files())}.", "32"))
        say(f"Open a new terminal once (or run: source {_rc_files()[0]}) and 'odus' works everywhere.")
        return True
    except OSError as e:
        say(c(f"Couldn't add Odus to PATH: {e}", "31"))
        return False


def path_remove() -> bool:
    try:
        if IS_WIN:
            raw, _ = _win_user_path_raw()
            parts = [p for p in raw.split(";") if p and _key(_expand(p)) != _key(HERE)]
            if len(parts) == len([p for p in raw.split(";") if p]):
                say("Odus wasn't on your user PATH.")
                return True
            backup = _win_set_user_path(";".join(parts))
            say(c("Removed Odus from your PATH.", "32") + c(f" (old PATH saved in {backup})", "2"))
            return True
        link = os.path.expanduser("~/.local/bin/odus")
        if os.path.islink(link):
            os.remove(link)
        for rc in _rc_files():
            _write_rc_block(rc, False)
        say(c("Removed the odus link and the Live Refresh block from your shell settings.", "32"))
        return True
    except OSError as e:
        say(c(f"Couldn't change PATH: {e}", "31"))
        return False


def launcher_hint() -> str:
    return quote_arg(SELF) if SINGLE_FILE else f"python {quote_arg(SELF)}"


def first_run_check(verb: str):
    """The very first time Odus runs, offer to put it on PATH."""
    cfg = load_config()
    if cfg.get("path_asked"):
        return
    if verb.startswith("path") or on_path():
        cfg["path_asked"] = True
        save_config(cfg)
        return
    if not sys.stdin.isatty():
        return  # ask next time someone is at the keyboard
    say(c("Welcome to Odus!", "1"))
    if ask_yes("Add Odus to your PATH so you can type 'odus' from any folder?"):
        path_add()
    else:
        say(f"OK, PATH left alone. Run Odus with {launcher_hint()}")
        say(f"Changed your mind? Run: {launcher_hint()} path add")
    cfg["path_asked"] = True
    save_config(cfg)
    say("")


def do_path(req: Request, sub: str | None = None) -> int:
    sub = sub or (norm(req.args[0]) if req.args else "status")
    if sub in ("add", "on", "yes", "enable", "install", "set"):
        return OK if path_add() else FAILED
    if sub in ("remove", "off", "no", "disable", "delete", "rm", "uninstall", "unset"):
        return OK if path_remove() else FAILED
    cfg = load_config()
    say(f"Odus folder:   {HERE}")
    say(f"On PATH:       {'yes' if on_path() else 'no  (odus path add)'}")
    say(f"Live Refresh:  {'on' if cfg.get('live_refresh', True) else 'off'}  (odus refresh on/off)")
    if IS_WIN:
        say(f"PowerShell:    {'Live Refresh works' if _ps_scripts_allowed() else 'scripts blocked, so Live Refresh only works in Command Prompt'}")
    return OK


def do_refresh(req: Request) -> int:
    sub = norm(req.args[0]) if req.args else ""
    cfg = load_config()
    if sub in ("on", "off"):
        cfg["live_refresh"] = sub == "on"
        save_config(cfg)
        say(f"Live Refresh is now {sub}.")
        return OK
    diff = write_shell_refresh()
    if not diff:
        say(c("Already up to date: nothing changed since this terminal opened.", "32"))
    else:
        say(c("Changes since this terminal opened:", "1"))
        for line in describe_diff(diff):
            say(line)
        if START_ENV.get("ODUS_REFRESH_FILE"):
            say(c("Applied to this terminal - no restart needed.", "32"))
    if not START_ENV.get("ODUS_REFRESH_FILE"):
        say(c("This terminal can't be refreshed from inside Odus.", "33"))
        if IS_WIN and not _ps_scripts_allowed():
            say("In PowerShell that needs local scripts allowed (Settings > System > For developers >")
            say("PowerShell). Odus switches it on by itself once you do. Command Prompt works already.")
        elif not IS_WIN:
            say("Run 'odus path add', then open a new terminal once to turn it on.")
    return OK


# ------------------------------------------------------- helper tools
TOOLS = {
    "ffmpeg": {"label": "FFmpeg", "bins": ["ffmpeg", "ffprobe"], "site": "https://ffmpeg.org/download.html",
               "pkgs": {"winget": "Gyan.FFmpeg", "scoop": "ffmpeg", "choco": "ffmpeg", "brew": "ffmpeg",
                        "apt": "ffmpeg", "dnf": "ffmpeg", "pacman": "ffmpeg", "zypper": "ffmpeg", "apk": "ffmpeg"}},
    "yt-dlp": {"label": "yt-dlp", "bins": ["yt-dlp"], "site": "https://github.com/yt-dlp/yt-dlp#installation",
               "pkgs": {"winget": "yt-dlp.yt-dlp", "scoop": "yt-dlp", "choco": "yt-dlp", "brew": "yt-dlp",
                        "apt": "yt-dlp", "dnf": "yt-dlp", "pacman": "yt-dlp", "zypper": "yt-dlp", "apk": "yt-dlp"}},
    "git": {"label": "Git", "bins": ["git"], "site": "https://git-scm.com/downloads",
            "pkgs": {"winget": "Git.Git", "scoop": "git", "choco": "git", "brew": "git", "apt": "git",
                     "dnf": "git", "pacman": "git", "zypper": "git", "apk": "git"}},
    "afsctool": {"label": "afsctool", "bins": ["afsctool"], "site": "https://github.com/RJVB/afsctool",
                 "pkgs": {"brew": "afsctool"}},
}
_INSTALL_CMD = {"winget": "winget install --id {} --exact", "scoop": "scoop install {}",
                "choco": "choco install {} -y", "brew": "brew install {}", "apt": "sudo apt install {}",
                "dnf": "sudo dnf install {}", "pacman": "sudo pacman -S {}", "zypper": "sudo zypper install {}",
                "apk": "sudo apk add {}"}
_EXTRA_BIN_DIRS = {
    "windows": [r"%LOCALAPPDATA%\Microsoft\WinGet\Links", r"%USERPROFILE%\scoop\shims", r"%ProgramData%\chocolatey\bin"],
    "macos": ["/opt/homebrew/bin", "/usr/local/bin"],
    "linux": ["/home/linuxbrew/.linuxbrew/bin", "~/.local/bin", "/usr/local/bin"],
}


_tool_cache: dict = {}


def _works(exe: str, binary: str) -> bool:
    """Skip broken or ancient copies (e.g. a 2013 ffmpeg left behind by a pip package)."""
    test = {"ffmpeg": ["-hide_banner", "-version"], "ffprobe": ["-hide_banner", "-version"],
            "yt-dlp": ["--version"], "git": ["--version"]}.get(binary)
    if not test:
        return True
    try:
        return subprocess.run([exe, *test], capture_output=True, timeout=20,
                              stdin=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _candidates(binary: str) -> list:
    names = [binary + e for e in (os.environ.get("PATHEXT", ".EXE").lower().split(";") if IS_WIN else [""]) if e or not IS_WIN]
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    dirs += [os.path.expanduser(_expand(d)) for d in _EXTRA_BIN_DIRS[OS_NAME]]
    found = [os.path.join(d, n) for d in dirs for n in names if os.path.isfile(os.path.join(d, n))]
    if IS_WIN:  # winget sometimes installs tools without putting them on PATH
        pkgs = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
        found += sorted(glob.glob(os.path.join(pkgs, "*", "**", binary + ".exe"), recursive=True), reverse=True)
    return list(dict.fromkeys(found))


def find_tool(binary: str, near: str | None = None) -> str | None:
    """The first working copy of a program; prefers one next to `near`."""
    key = (binary, near)
    if key not in _tool_cache:
        cands = _candidates(binary)
        if near:
            cands.sort(key=lambda p: _key(os.path.dirname(p)) != _key(os.path.dirname(near)))
        _tool_cache[key] = next((p for p in cands if _works(p, binary)), None)
    return _tool_cache[key]


def tool_path(key: str) -> str | None:
    bins = TOOLS[key]["bins"]
    first = find_tool(bins[0])
    return first if first and all(find_tool(b, first) for b in bins[1:]) else None


def os_install_command(key: str) -> str:
    pkgs = TOOLS[key]["pkgs"]
    mine = [m for m in MANAGERS if OS_NAME in m.systems and m.name in pkgs]
    pick = next((m for m in mine if m.available()), mine[0] if mine else None)
    return _INSTALL_CMD[pick.name].format(pkgs[pick.name]) if pick else TOOLS[key]["site"]


def ensure_tool(key: str, req: Request, declined: str = "odus") -> bool:
    """Make sure a helper tool (FFmpeg, yt-dlp, git...) is there, offering to
    install it and carrying on with the job afterwards."""
    if tool_path(key):
        return True
    live_refresh_self()  # maybe it was installed after this terminal opened
    if tool_path(key):
        return True
    t = TOOLS[key]
    if req.dry_run:
        say(c(f"(dry run) {t['label']} isn't installed - Odus would offer to install it first.", "33"))
        return True
    if not ask_yes(f"{t['label']} isn't installed and Odus needs it for this. Install it now?", req):
        rerun = "odus " + " ".join(quote_arg(a) for a in req.raw)
        if declined == "odus":
            say(c(f"\nInstall {t['label']} first, then run this again:", "33"))
            say(f"  odus install {key}")
            say(f"  (or download it from {t['site']})")
        else:
            say(c(f"\nTo install {t['label']} yourself, run:", "33"))
            say(f"  {os_install_command(key)}")
            say("Then run this again:")
            say(f"  {rerun}")
        return False
    chain = ensure_privileges([m for m in MANAGERS if m.available() and m.name in t["pkgs"]], req.dry_run)
    if not chain:
        say(c(f"No package manager here can install {t['label']}. Get it from {t['site']}", "31"))
        return False
    for m in chain:
        pkg = t["pkgs"][m.name]
        extra = ["--id", pkg, "--exact"] if m.name == "winget" else [pkg]
        if run(f"{m.name}:{key}", *build_argv(m, m.install, req.preset, True, extra),
               req.preset, req.dry_run, check=True) == OK:
            break
    live_refresh_self()
    _tool_cache.clear()
    for d in _EXTRA_BIN_DIRS[OS_NAME]:
        d = os.path.expanduser(_expand(d))
        if os.path.isdir(d) and _key(d) not in {_key(p) for p in os.environ["PATH"].split(os.pathsep)}:
            os.environ["PATH"] += os.pathsep + d
    if tool_path(key):
        say(c(f"{t['label']} is installed. Carrying on...\n", "32"))
        return True
    say(c(f"{t['label']} was installed but Odus can't see it yet. Open a new terminal and run this again.", "33"))
    return False


# --------------------------------------------------------- app compression
def _win_installed_apps() -> list:
    import winreg
    out = []
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, sub in roots:
        try:
            root = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        for i in range(winreg.QueryInfoKey(root)[0]):
            try:
                k = winreg.OpenKey(root, winreg.EnumKey(root, i))
            except OSError:
                continue

            def val(n):
                try:
                    return str(winreg.QueryValueEx(k, n)[0]).strip()
                except OSError:
                    return ""
            name, loc, icon = val("DisplayName"), val("InstallLocation").strip('"'), val("DisplayIcon")
            if not loc and icon:
                exe = icon.split(",")[0].strip().strip('"')
                if exe.lower().endswith(".exe"):
                    loc = os.path.dirname(exe)
            if name and loc and os.path.isdir(loc):
                out.append((name, loc))
    return out


def _unsafe_dirs() -> set:
    env = os.environ
    dirs = {"/", "/usr", "/opt", "/bin", "/sbin", "/etc", "/var", "/lib", "/System", "/Library",
            "/Applications", "/usr/share", "/usr/local", os.path.expanduser("~"),
            os.path.expanduser("~/Applications"), os.path.expanduser("~/.local/share")}
    for v in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "LOCALAPPDATA", "APPDATA"):
        if env.get(v):
            dirs.add(env[v])
    if env.get("LOCALAPPDATA"):
        dirs.add(os.path.join(env["LOCALAPPDATA"], "Programs"))
    return {_key(d) for d in dirs}


def _is_unsafe(path: str) -> bool:
    k = _key(os.path.abspath(path))
    sysroot = _key(os.environ.get("SystemRoot", "C:\\Windows")) if IS_WIN else None
    return k in _unsafe_dirs() or len(k) <= 3 or bool(sysroot and k.startswith(sysroot))


def find_app_dirs(app: App) -> list:
    """Where an app is installed: an existing folder path, or found by name."""
    for cand in dict.fromkeys([app.name, *app.plain, *app.spaced]):
        if os.path.isdir(cand):
            p = os.path.abspath(cand)
            return [(os.path.basename(p) or p, p)]
    words = [w for w in re.split(r"[\s\-_]+", app.name.lower()) if w]
    match = lambda text: all(w in text.lower() for w in words)
    found = {}
    if IS_WIN:
        for name, loc in _win_installed_apps():
            if match(name):
                found.setdefault(_key(loc), (name, loc))
        roots = [os.environ.get(v, "") for v in ("ProgramFiles", "ProgramFiles(x86)")]
        roots.append(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"))
    elif IS_MAC:
        roots = ["/Applications", os.path.expanduser("~/Applications")]
    else:
        roots = ["/opt", os.path.expanduser("~/.local/share/flatpak/app"), "/var/lib/flatpak/app"]
    for root in roots:
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        for e in entries:
            p = os.path.join(root, e)
            if not os.path.isdir(p):
                continue
            if match(e):
                found.setdefault(_key(p), (e, p))
            elif IS_WIN:  # vendor folders: Program Files\Adobe\Adobe Premiere Pro 2026
                try:
                    for e2 in os.listdir(p):
                        p2 = os.path.join(p, e2)
                        if match(e2) and os.path.isdir(p2):
                            found.setdefault(_key(p2), (e2, p2))
                except OSError:
                    pass
    return [v for v in found.values() if not _is_unsafe(v[1])]


def choose_dirs(app: App, matches: list, req: Request) -> list:
    if len(matches) <= 1:
        return matches
    say(f'"{app.name}" matches more than one folder:')
    for i, (name, path) in enumerate(matches, 1):
        say(f"  {i}. {name}  {c(path, '2')}")
    if req.yes or not req.preset.confirm or not sys.stdin.isatty():
        say("Doing all of them.")
        return matches
    try:
        ans = input("Which one? Type a number, 'a' for all, or press Enter to skip: ").strip().lower()
    except EOFError:
        return []
    if ans in ("a", "all"):
        return matches
    return [matches[int(ans) - 1]] if ans.isdigit() and 1 <= int(ans) <= len(matches) else []


def disk_usage(path: str) -> int:
    """Real space used on disk (after compression), not the file sizes."""
    total = 0
    if IS_WIN:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCompressedFileSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        k32.GetCompressedFileSizeW.restype = wintypes.DWORD
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if IS_WIN:
                    high = wintypes.DWORD(0)
                    low = k32.GetCompressedFileSizeW("\\\\?\\" + os.path.abspath(fp), ctypes.byref(high))
                    if low == 0xFFFFFFFF and ctypes.get_last_error():
                        total += os.path.getsize(fp)
                    else:
                        total += (high.value << 32) + low
                else:
                    total += os.lstat(fp).st_blocks * 512
            except OSError:
                pass
    return total


def _needs_admin_win(path: str) -> bool:
    k = _key(os.path.abspath(path))
    return any(k.startswith(_key(os.environ[v])) for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "SystemRoot")
               if os.environ.get(v))


def compress_dir(path: str, req: Request, undo: bool) -> int:
    p = req.preset
    workers = {"standard": 1, "fast": 1, "fastplus": 4, "ufa": CPUS}[p.name]
    tag = os.path.basename(path.rstrip("\\/")) or path
    if IS_WIN:
        if not is_admin() and _needs_admin_win(path):
            say(c(f"{tag}: this folder needs an admin terminal (right-click > Run as administrator).", "31"))
            return FAILED
        algo = (req.opts.get("algo") or ("xpress8k" if p.name == "fast" else "lzx")).lower()
        if algo not in ("xpress4k", "xpress8k", "xpress16k", "lzx"):
            say(c(f"Unknown --algo '{algo}'. Use xpress4k, xpress8k, xpress16k or lzx.", "31"))
            return FAILED
        compact = shutil.which("compact") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "compact.exe")
        base = [compact, "/u", "/exe", "/i", "/q"] if undo else [compact, "/c", f"/exe:{algo}", "/i", "/q"]
        jobs = []
        try:
            entries = os.listdir(path)
        except OSError as e:
            say(c(f"{tag}: {e}", "31"))
            return FAILED
        for e in entries:  # each top-level folder is its own job, so they can run side by side
            if os.path.isdir(os.path.join(path, e)):
                jobs.append((f"{tag}/{e}", base + ["/s"], os.path.join(path, e)))
        files = [e for e in entries if os.path.isfile(os.path.join(path, e))]
        for i in range(0, len(files), 40):
            jobs.append((tag, base + files[i:i + 40], path))
        if not req.dry_run:
            say(f"{'Decompressing' if undo else 'Compressing'} {tag} with {'compact' if undo else 'compact ' + algo.upper()}"
                f" ({len(jobs)} parts, {min(workers, max(1, len(jobs)))} at a time)...")
        with ThreadPoolExecutor(max(1, min(workers, len(jobs) or 1))) as ex:
            codes = list(ex.map(lambda j: run(j[0], j[1], {}, p, req.dry_run, cwd=j[2], quiet=True), jobs))
        if any(cd != OK for cd in codes):
            say(c(f"{tag}: some files were skipped (probably in use). Close the app and run this again to finish.", "33"))
        return OK
    if IS_MAC:
        if not ensure_tool("afsctool", req):
            return CANCELLED
        argv = ["afsctool", "-d", path] if undo else ["afsctool", "-c", "-T", "LZFSE", f"-j{workers}", path]
        argv[0] = shutil.which("afsctool") or "afsctool"
        if not os.access(path, os.W_OK) and not is_admin():
            argv = ["sudo"] + argv
        return run(tag, argv, {}, p, req.dry_run)
    try:
        fs = subprocess.run(["stat", "-f", "-c", "%T", path], capture_output=True, text=True).stdout.strip()
    except OSError:
        fs = ""
    if fs != "btrfs":
        say(c(f"{tag} is on {fs or 'a filesystem'} with no built-in compression, so Odus can't compress apps there.", "33"))
        say("(On Linux only btrfs can compress files in place.)")
        return SKIPPED
    if undo:
        say(c("btrfs can't switch compression off in place. Copy the folder to undo it.", "33"))
        return SKIPPED
    argv = ["btrfs", "filesystem", "defragment", "-r", "-czstd", path]
    if not is_admin():
        argv = ["sudo"] + argv
    return run(tag, argv, {}, p, req.dry_run)


def do_compress_app(req: Request, undo: bool = False) -> int:
    word = "decompress" if undo else "compress"
    if not req.args:
        say(f"Tell me which app, e.g. " + c(f"odus {word}-app Adobe Premiere Pro 2026", "1"))
        return FAILED
    results, targets = [], []
    for app in req.apps:
        matches = find_app_dirs(app)
        if not matches:
            results.append((f"{app.name} (couldn't find where it's installed - try its folder path)", NOT_FOUND, 0.0))
            continue
        targets += choose_dirs(app, matches, req)
    if targets:
        for name, path in targets:
            say(f"  {name}  {c(path, '2')}")
        if not confirm(req, f"{word.capitalize()} {len(targets)} app folder{'s' if len(targets) > 1 else ''}? "
                            f"Close {'them' if len(targets) > 1 else 'it'} first."):
            return CANCELLED
    for name, path in targets:
        t = time.time()
        before = 0 if req.dry_run else disk_usage(path)
        status = compress_dir(path, req, undo)
        if status == CANCELLED:
            return CANCELLED
        if req.dry_run or status != OK:
            results.append((name, status, time.time() - t))
            continue
        after = disk_usage(path)
        change = (before - after) / before * 100 if before else 0
        note = "back to full size" if undo else f"saved {change:.0f}%" if change >= 0 else "no savings"
        results.append((f"{name}: {human(before)} -> {human(after)} ({note})", OK, time.time() - t))
    return summary(req, results)


# ----------------------------------------------------- photo/video compression
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".ts", ".3gp", ".mts", ".m2ts"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
OUT_TAG = " (compressed)"
HW_ARGS = {"hevc_nvenc": ["-preset", "p1", "-rc", "vbr", "-cq", "30", "-b:v", "0"],
           "hevc_qsv": ["-global_quality", "28", "-preset", "veryfast"],
           "hevc_amf": ["-quality", "speed", "-rc", "cqp", "-qp_i", "28", "-qp_p", "30"],
           "hevc_videotoolbox": ["-q:v", "55"]}
_hw_cache: dict = {}


def expand_paths(words: list) -> list:
    """Glue words back into paths with spaces (C:\\My Videos\\a.mp4) and expand *."""
    out, i = [], 0
    while i < len(words):
        for j in range(len(words), i, -1):
            cand = " ".join(words[i:j]).strip('"')
            if os.path.exists(cand):
                out.append(cand)
                i = j
                break
        else:
            w = words[i]
            hits = glob.glob(w) if any(ch in w for ch in "*?[") else []
            out.extend(hits or [w])
            i += 1
    return out


def collect_media(paths: list):
    files, missing = [], []
    def wanted(f):
        stem, ext = os.path.splitext(f)
        return ext.lower() in VIDEO_EXT | IMAGE_EXT and not stem.endswith(OUT_TAG)
    for p in paths:
        if os.path.isdir(p):
            for root, _d, fs in os.walk(p):
                files += [os.path.join(root, f) for f in sorted(fs) if wanted(f)]
        elif os.path.isfile(p):
            if wanted(p):
                files.append(p)
        else:
            missing.append(p)
    return list(dict.fromkeys(files)), missing


def ffmpeg_encoders(ffmpeg: str) -> set:
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                             errors="replace", timeout=20, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return set(re.findall(r"^\s[VAS][\w.]{5}\s+(\S+)", out, re.M))


def hw_encoder(ffmpeg: str, encs: set) -> str | None:
    """A graphics-card video encoder that actually works on this machine."""
    if "hw" in _hw_cache:
        return _hw_cache["hw"]
    cands = {"windows": ["hevc_nvenc", "hevc_qsv", "hevc_amf"], "macos": ["hevc_videotoolbox"],
             "linux": ["hevc_nvenc", "hevc_qsv"]}[OS_NAME]
    found = None
    for enc in (e for e in cands if e in encs):
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                                "color=c=black:s=256x256:d=0.2", "-c:v", enc, "-f", "null", "-"],
                               capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
            if r.returncode == 0:
                found = enc
                break
        except (OSError, subprocess.SubprocessError):
            pass
    _hw_cache["hw"] = found
    return found


def video_settings(p: Preset, ffmpeg: str, encs: set):
    speed = {"standard": "medium", "fast": "faster", "fastplus": "veryfast", "ufa": "ultrafast"}[p.name]
    jobs = {"standard": 1, "fast": 1, "fastplus": 2, "ufa": max(2, CPUS // 4)}[p.name]
    if p.name == "ufa":
        hw = hw_encoder(ffmpeg, encs)
        if hw:
            return ["-c:v", hw, *HW_ARGS[hw]], f"{hw} (graphics card)", 2, True
    if "libx265" in encs:
        v, label, hevc = ["-c:v", "libx265", "-crf", "28", "-preset", speed, "-x265-params", "log-level=error"], f"H.265 {speed}", True
    else:
        v, label, hevc = ["-c:v", "libx264", "-crf", "26", "-preset", speed], f"H.264 {speed}", False
    if p.name == "fast":
        v += ["-threads", str(max(1, CPUS // 2))]
    return v, label, jobs, hevc


def ffprobe(path: str) -> dict:
    exe = find_tool("ffprobe", find_tool("ffmpeg")) or "ffprobe"
    try:
        out = subprocess.run([exe, "-v", "error", "-show_entries",
                              "stream=index,codec_type,codec_name:stream_disposition=attached_pic",
                              "-of", "json", path], capture_output=True, text=True, errors="replace",
                             timeout=60, stdin=subprocess.DEVNULL).stdout
        return json.loads(out or "{}")
    except (OSError, ValueError, subprocess.SubprocessError, TypeError):
        return {}


def finish_output(src: str, out: str, req: Request, t: float):
    name = os.path.basename(src)
    if req.dry_run:
        return name, OK, 0.0
    if not os.path.exists(out):
        return name, FAILED, time.time() - t
    old, new = os.path.getsize(src), os.path.getsize(out)
    if new >= old * 0.97:
        os.remove(out)
        return f"{name}: already well compressed ({human(old)}), left as is", SKIPPED, time.time() - t
    final = out
    if req.opts.get("replace"):
        target = os.path.splitext(src)[0] + os.path.splitext(out)[1]
        os.replace(out, target)
        if _key(target) != _key(src):
            os.remove(src)
        final = target
    return (f"{name}: {human(old)} -> {human(new)} (saved {(old - new) / old * 100:.0f}%)"
            f"{'' if final == out else ' (replaced original)'}", OK, time.time() - t)


def compress_video(src: str, req: Request, ffmpeg: str, vset) -> tuple:
    t = time.time()
    vargs, _label, _jobs, hevc = vset
    info = ffprobe(src) if not req.dry_run else {"streams": [{"index": 0, "codec_type": "video"}]}
    streams = info.get("streams", [])
    video = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not video:
        return f"{os.path.basename(src)}: no video inside", SKIPPED, 0.0
    audio = [s.get("codec_name", "") for s in streams if s.get("codec_type") == "audio"]
    ext = os.path.splitext(src)[1].lower()
    out_ext = ".mkv" if ext == ".mkv" else ".mp4"
    out = os.path.splitext(src)[0] + OUT_TAG + out_ext
    maps = ["-map", f"0:{video[0].get('index', 0)}", "-map", "0:a?"]
    copy_ok = {"aac", "mp3"} | ({"opus", "vorbis", "ac3", "eac3", "flac"} if out_ext == ".mkv" else set())
    aargs = ["-c:a", "copy"] if all(a in copy_ok for a in audio) else ["-c:a", "aac", "-b:a", "160k"]
    extra = (["-tag:v", "hvc1"] if hevc else []) + ["-movflags", "+faststart"] if out_ext == ".mp4" else ["-map", "0:s?", "-c:s", "copy"]
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-stats", "-i", src,
            *maps, *vargs, *aargs, *extra, out]
    status = run(os.path.basename(src), argv, {}, req.preset, req.dry_run)
    if status != OK:
        if os.path.exists(out):
            os.remove(out)
        return os.path.basename(src), FAILED, time.time() - t
    return finish_output(src, out, req, t)


def compress_image(src: str, req: Request, ffmpeg: str, encs: set) -> tuple:
    t = time.time()
    stem, ext = os.path.splitext(src)
    ext = ext.lower()
    fast = req.preset.name in ("fast", "fastplus", "ufa")
    if ext in (".jpg", ".jpeg"):
        out_ext, args = ext, ["-q:v", "5"]
    elif ext == ".png":
        out_ext, args = ".png", ["-compression_level", "9", "-pred", "paeth" if fast else "mixed"]
    elif ext == ".webp":
        if "libwebp" not in encs:
            return f"{os.path.basename(src)}: this FFmpeg can't write WebP", SKIPPED, 0.0
        out_ext, args = ".webp", ["-c:v", "libwebp", "-quality", "75"]
    else:  # bmp / tiff -> lossless png
        out_ext, args = ".png", ["-compression_level", "9"]
    out = stem + OUT_TAG + out_ext
    argv = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", src,
            "-map_metadata", "0", "-frames:v", "1", "-update", "1", *args, out]
    status = run(os.path.basename(src), argv, {}, req.preset, req.dry_run)
    if status != OK:
        if os.path.exists(out):
            os.remove(out)
        return os.path.basename(src), FAILED, time.time() - t
    return finish_output(src, out, req, t)


def do_compress(req: Request) -> int:
    if not req.args:
        say("Tell me what to compress, e.g. " + c("odus compress holiday.mp4", "1") +
            " or a folder of photos/videos.")
        return FAILED
    files, missing = collect_media(expand_paths(req.args))
    if not files:
        joined = " ".join(req.args)
        if missing and find_app_dirs(make_apps(req.args, req.multi)[0]):
            say(c(f"There's no file called '{joined}', but there's an app - compressing the app instead.", "2"))
            return do_compress_app(req)
        say(c(f"No photos or videos found in: {joined}", "31"))
        return NOT_FOUND
    for m in missing:
        say(c(f"Not found, skipping: {m}", "33"))
    if not ensure_tool("ffmpeg", req, "odus"):
        return CANCELLED
    ffmpeg = find_tool("ffmpeg") or "ffmpeg"
    videos = [f for f in files if os.path.splitext(f)[1].lower() in VIDEO_EXT]
    images = [f for f in files if f not in videos]
    keep = "replacing the originals" if req.opts.get("replace") else "originals are kept"
    if not confirm(req, f"Compress {len(videos)} video(s) and {len(images)} photo(s) ({keep})."):
        return CANCELLED
    encs = ffmpeg_encoders(ffmpeg) if not req.dry_run else {"libx265"}
    results = []
    if videos:
        vset = video_settings(req.preset, ffmpeg, encs)
        say(c(f"Video encoder: {vset[1]}, {min(vset[2], len(videos))} at a time", "2"))
        with ThreadPoolExecutor(max(1, min(vset[2], len(videos)))) as ex:
            results += list(ex.map(lambda f: compress_video(f, req, ffmpeg, vset), videos))
    if images:
        jobs = {"standard": 1, "fast": 1, "fastplus": max(2, CPUS // 2), "ufa": CPUS}[req.preset.name]
        with ThreadPoolExecutor(max(1, min(jobs, len(images)))) as ex:
            results += list(ex.map(lambda f: compress_image(f, req, ffmpeg, encs), images))
    return summary(req, results)


# ------------------------------------------------------------------ download
FILE_EXT = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".xz", ".bz2", ".zst", ".exe", ".msi", ".msix",
            ".appx", ".dmg", ".pkg", ".deb", ".rpm", ".appimage", ".apk", ".iso", ".img", ".pdf", ".epub",
            ".txt", ".csv", ".json", ".xml", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico",
            ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".docx", ".xlsx", ".pptx", ".jar", ".whl", ".bin",
            ".ttf", ".otf", ".woff2"}
GIT_HOSTS = {"github.com", "gitlab.com", "bitbucket.org", "codeberg.org", "gitea.com", "git.sr.ht"}


def looks_like_link(w: str) -> bool:
    return bool(re.match(r"^([a-z][a-z0-9+.-]*://|git@)", w, re.I) or
                re.fullmatch(r"[\w.-]+\.[a-z]{2,}(/\S*)?", w, re.I) or
                re.fullmatch(r"[\w.-]+/[\w.-]+", w))


def classify_link(link: str):
    """-> (kind, url, branch): kind is 'git', 'file' or 'media'."""
    if re.match(r"^(git@|ssh://|git://)", link) or link.endswith(".git"):
        return "git", link, None
    if not re.match(r"^[a-z][a-z0-9+.-]*://", link, re.I):
        first = link.split("/")[0]
        if "." not in first and re.fullmatch(r"[\w.-]+/[\w.-]+", link):
            return "git", f"https://github.com/{link}.git", None  # owner/repo shorthand
        link = "https://" + link
    u = urllib.parse.urlparse(link)
    host = u.netloc.lower().removeprefix("www.")
    parts = [p for p in u.path.split("/") if p]
    ext = os.path.splitext(parts[-1])[1].lower() if parts else ""
    if host in GIT_HOSTS and len(parts) >= 2:
        if host == "github.com" and len(parts) >= 5 and parts[2] == "blob":
            raw = f"https://raw.githubusercontent.com/{parts[0]}/{parts[1]}/{'/'.join(parts[3:])}"
            return "file", raw, None
        rest = [p for p in parts[2:] if p != "-"]
        if not rest or rest[0] == "tree":
            branch = rest[1] if len(rest) > 1 else None
            return "git", f"{u.scheme}://{u.netloc}/{parts[0]}/{parts[1].removesuffix('.git')}.git", branch
    if ext in FILE_EXT or (ext and host in GIT_HOSTS):
        return "file", link, None
    return "media", link, None


def http_download(url: str, dest: str, req: Request) -> tuple:
    t = time.time()
    tag = url.split("/")[-1][:40] or url
    say(f"{c(f'[{tag}]', '36')} {c('$ download ' + url, '2')}")
    if req.dry_run:
        return url, OK, 0.0
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": f"Odus/{VERSION}"}), timeout=30)
    except urllib.error.HTTPError as e:
        say(c(f"[{tag}] {e.code} {e.reason}", "31"))
        return url, NOT_FOUND if e.code == 404 else FAILED, time.time() - t
    except (OSError, ValueError) as e:
        say(c(f"[{tag}] {e}", "31"))
        return url, FAILED, time.time() - t
    with r:
        cd = r.headers.get("Content-Disposition") or ""
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.I)
        name = urllib.parse.unquote(m.group(1) if m else os.path.basename(urllib.parse.urlparse(r.geturl()).path))
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "download"
        path = os.path.join(dest, name)
        stem, ext = os.path.splitext(path)
        n = 1
        while os.path.exists(path):
            path, n = f"{stem} ({n}){ext}", n + 1
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, time.time()
        try:
            with open(path + ".part", "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 2:
                        last = time.time()
                        pct = f"{done / total * 100:.0f}% of {human(total)}" if total else human(done)
                        say(f"{c(f'[{tag}]', '36')} {pct}")
            os.replace(path + ".part", path)
        except OSError as e:
            say(c(f"[{tag}] {e}", "31"))
            return url, FAILED, time.time() - t
    return f"{os.path.basename(path)} ({human(done)})", OK, time.time() - t


def do_download(req: Request) -> int:
    # accept "quoted" links, including curly quotes pasted from chat apps
    req.args = [a.strip("\"'“”‘’") for a in req.args]
    links = [w for w in req.args if looks_like_link(w)]
    others = [w for w in req.args if w not in links]
    if not links:
        if req.args:
            say(c(f"'{' '.join(req.args)}' isn't a link, so Odus will install it as an app.", "2"))
            return do_install(req)
        say("Give me a link, e.g. " + c('odus download "https://youtu.be/..."', "1") +
            " or " + c('odus download "github.com/owner/repo"', "1"))
        return FAILED
    for w in others:
        say(c(f"Skipping '{w}' - it isn't a link.", "33"))
    dest = os.path.abspath(os.path.expanduser(req.opts.get("to") or "."))
    jobs = [classify_link(l) for l in links]
    kinds = {k for k, _u, _b in jobs}
    if "git" in kinds and not ensure_tool("git", req, "os"):
        return CANCELLED
    if "media" in kinds and not ensure_tool("yt-dlp", req, "os"):
        return CANCELLED
    if "media" in kinds and req.opts.get("audio") and not ensure_tool("ffmpeg", req, "odus"):
        return CANCELLED
    if not req.dry_run:
        os.makedirs(dest, exist_ok=True)
    p = req.preset
    say(c(f"Saving to {dest}", "2"))

    def one(job):
        kind, url, branch = job
        t = time.time()
        if kind == "git":
            argv = [find_tool("git") or "git", "clone", "--progress", "--recurse-submodules",
                    "--jobs", str({"standard": 1, "fast": 2, "fastplus": 4, "ufa": 8}[p.name])]
            if branch:
                argv += ["-b", branch]
            if req.opts.get("shallow"):
                argv += ["--depth", "1", "--shallow-submodules"]
            name = os.path.basename(url).removesuffix(".git")
            status = run(name, argv + [url], {}, p, req.dry_run, cwd=dest if not req.dry_run else None)
            return f"{name} (git clone)", status, time.time() - t
        if kind == "file":
            return http_download(url, dest, req)
        frags = {"standard": 1, "fast": 2, "fastplus": 4, "ufa": 16}[p.name]
        argv = [find_tool("yt-dlp") or "yt-dlp", "--newline", "-N", str(frags), "-P", dest,
                "-o", "%(title)s [%(id)s].%(ext)s"]
        if req.opts.get("audio"):
            argv += ["-x", "--audio-format", "mp3"]
        lines: list = []
        status = run("yt-dlp", argv + [url], {}, p, req.dry_run, capture=lines)
        if status != OK and any("Unsupported URL" in l for l in lines):
            say(c("yt-dlp doesn't know this site - downloading it as a plain file instead.", "2"))
            return http_download(url, dest, req)
        return f"{url} (yt-dlp)", status, time.time() - t

    workers = {"standard": 1, "fast": 1, "fastplus": 3, "ufa": 8}[p.name]
    with ThreadPoolExecutor(max(1, min(workers, len(jobs)))) as ex:
        return summary(req, list(ex.map(one, jobs)))


HELP = f"""
{c('Odus v' + VERSION, '1')} - your whole computer, one command.

  odus [preset] [multi-package] <command> [what...] [options]

Presets (pick one, or leave it out for standard):
  (none)     Standard: one thing at a time, default settings. Slowest.
  fast       Low CPU priority + a little parallel work. Easiest on your machine.
  fastplus   Several things side by side.
  ufa        Ultra-Fast Actions: everything at once, high priority, graphics-card
             video encoding when possible, never asks. Hard on weak or hot machines.

Apps:
  update                          update every app
  update | install | uninstall <app>
  search <words>   list   managers
  Everything after the command is ONE app, spaces and all. For several apps add
  multi-package: spaces split apps, dashes join words:
    odus multi-package install Adobe-Premiere-Pro-2026 vlc 7-zip

Compression:
  compress <files or folders>     shrink photos and videos with FFmpeg
                                  (keeps originals; --replace swaps them)
  compress-app <app or folder>    shrink an installed app in place
                                  (Windows: compact, macOS: afsctool, Linux: btrfs)
  decompress-app <app or folder>  undo it

Downloads:
  download <link...>              YouTube & 1000+ sites (yt-dlp), git repos
                                  (git clone), or any file link
    --to <folder>  save somewhere else     --audio  MP3 only     --shallow  latest git commit only
  Always put links in quotes: odus download "https://youtube.com/watch?v=..."

Setup:
  path [add|remove]               put Odus on PATH (or take it off)
  refresh                         Live Refresh: pull in PATH changes and new tools
                                  without reopening the terminal (also runs after every command)
  refresh on|off                  turn the automatic part on or off

Options: --dry-run (show, don't do)  --yes (don't ask)  --with <manager>

Typos and synonyms are fine: odus fsat isntall git, odus ufa upgrade-applications
"""


def main(argv=None) -> int:
    req = parse(sys.argv[1:] if argv is None else argv)
    cfg = load_config()
    if IS_WIN:
        live_refresh_self()  # see tools installed since this terminal opened
        sync_ps1()
    if req.verb not in ("help", "version", "unknown"):
        first_run_check(req.verb)
    for n in req.notes:
        say(c(f"understood {n}", "2"))
    try:
        return _main(req)
    finally:
        if cfg.get("live_refresh", True) and req.verb != "refresh" and \
                (IS_WIN or req.verb in CHANGES_THINGS):
            try:
                write_shell_refresh()
            except Exception:
                pass


CHANGES_THINGS = {"update", "install", "uninstall", "download", "compress", "compress-app",
                  "decompress-app", "path", "path-add", "path-remove"}


def _main(req: Request) -> int:
    if req.verb == "help":
        say(HELP)
        return 0
    if req.verb == "version":
        say(f"Odus v{VERSION}")
        return 0
    if req.verb == "unknown":
        say(c(f"Odus doesn't understand '{' '.join(req.args)}'.", "31") + " Try " + c("odus help", "1"))
        return 2

    if req.verb in ("update", "install", "uninstall", "compress", "compress-app", "decompress-app", "download"):
        what = names(req.apps) if req.verb in ("install", "uninstall", "update", "compress-app", "decompress-app") \
            else " ".join(req.args)
        say(c(f"Odus - {req.preset.label}{' - multi-package' if req.multi else ''} - {req.verb}"
              f"{' ' + what if what else ''}{' - dry run' if req.dry_run else ''}", "1"))
    t = time.time()
    rc = {
        "update": do_update,
        "install": do_install,
        "uninstall": do_uninstall,
        "search": lambda r: do_query(r, "search"),
        "list": lambda r: do_query(r, "listing"),
        "managers": do_managers,
        "compress": do_compress,
        "compress-app": do_compress_app,
        "decompress-app": lambda r: do_compress_app(r, undo=True),
        "download": do_download,
        "path": do_path,
        "path-add": lambda r: do_path(r, "add"),
        "path-remove": lambda r: do_path(r, "remove"),
        "refresh": do_refresh,
    }[req.verb](req)
    if req.verb in ("update", "install", "uninstall", "compress", "compress-app", "decompress-app", "download"):
        secs = f"{time.time() - t:.1f}s"
        if rc == CANCELLED:
            say(c("\nCancelled - nothing was changed.", "33"))
        elif rc == OK:
            say(c(f"\nDone in {secs} ({req.preset.label})", "1"))
        elif rc == NOT_FOUND:
            say(c(f"\nNothing was changed: Odus couldn't find that. ({secs})", "31"))
        else:
            say(c(f"\nFinished with problems in {secs} - see above.", "31"))
    return {OK: 0, CANCELLED: 1, NOT_FOUND: 3, AMBIGUOUS: 4, SKIPPED: 0}.get(rc, 1)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say(c("\nStopped.", "33"))
        sys.exit(130)
