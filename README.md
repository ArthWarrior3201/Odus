<p align="center"><img src="odus_logo.png" alt="Odus logo" width="360"></p>

# Odus

Odus works the same way on Windows, macOS and Linux.

```
odus [preset] [multi-package] <command> [what...] [options]
```

## Download

Get the latest version from the
[releases page](https://github.com/ArthWarrior3201/Odus/releases/latest).
It's a single file, and you don't need to install Python.

- **Windows:** download `odus.bat`, then double-click it or run it in Command
  Prompt. If Windows warns about a downloaded file, choose **Run** (or
  **More info > Run anyway**).
- **macOS:** download `odus.command`, then run `chmod +x odus.command` once in
  Terminal. After that, double-click it, or run `./odus.command`. If macOS
  says it can't check the developer, right-click it and choose **Open**.
  On **macOS Tahoe 26 (Developer Beta) or newer** that no longer works (nor does
  **Open Anyway**); remove the quarantine flag instead, then open it as usual:
  `xattr -d com.apple.quarantine odus.command`
- **Linux:** download `odus.sh`, then run `chmod +x odus.sh` and `./odus.sh`.
- **Any system with Python 3.9+:** download `odus.py` and run `python odus.py`.

### No Python? No problem

`odus.bat`, `odus.command` and `odus.sh` use the Python already on your
computer if it's 3.9 or newer. If there isn't one, the first run offers to
download a private copy just for Odus (about 11 MB on Windows, 20 MB on
macOS/Linux). It's checked against a known fingerprint before it's used, and
it's only used by Odus: nothing is installed system-wide and your PATH isn't
touched. Say no and Odus shows how to install Python yourself instead.

The private copy lives in `%LOCALAPPDATA%\Odus` (Windows) or
`~/.local/share/odus` (macOS/Linux). Delete that folder to remove it.

## First run

The first time you run Odus it asks whether to add itself to your PATH.

- **Yes:** type `odus` from any folder. On Windows the PATH is changed directly
  in the registry (never `setx`, which cuts PATH off at 1024 characters) and a
  backup is saved first. On macOS/Linux Odus links `~/.local/bin/odus` and adds
  a small block to your shell settings.
- **No:** nothing changes. Run the file you downloaded (`odus.bat`,
  `./odus.command` or `./odus.sh`) from its folder.

Change your mind any time with `odus path add` or `odus path remove`.

## Presets

| Preset      | What it does                                                         | Load on your PC |
|-------------|----------------------------------------------------------------------|-----------------|
| *(none)*    | Standard. One thing at a time, default settings. Slowest.             | normal          |
| `fast`      | Low CPU priority, a little parallel work. Gentlest on weak machines.  | lowest          |
| `fastplus`  | Several things side by side.                                         | medium          |
| `ufa`       | Ultra-Fast Actions: everything at once, high priority, graphics-card video encoding when available, never asks. | no mercy |

How much faster each preset is depends on your internet, disk, CPU and graphics.

## Apps

```
odus update                         update every app
odus fast update all my apps
odus install Google Chrome          everything after the command is ONE app
odus uninstall Adobe Premiere Pro 2026
odus search adobe premiere
odus list
odus managers                       which package managers Odus found
```

For several apps at once add `multi-package`. Spaces then separate apps and
dashes stand for the spaces inside a name:

```
odus multi-package install Adobe-Premiere-Pro-2026 vlc 7-zip
odus ufa multi-package uninstall Adobe-Media-Encoder-2026 Spotify
```

If an app isn't found, or you answer `n`, Odus says so and reports that nothing
was changed.

Supported: **Windows** winget, scoop, choco · **macOS** brew · **Linux** apt,
dnf, pacman, zypper, apk, flatpak, snap, brew.

## Compression

```
odus compress holiday.mp4                 one video
odus fastplus compress C:\Users\me\Pictures   a whole folder of photos and videos
odus compress *.jpg --replace             swap the originals for the smaller files
```

- Uses FFmpeg. Videos become H.265 (or H.264 if your FFmpeg has no H.265);
  JPG, PNG and WebP stay in their format; BMP/TIFF become lossless PNG.
- Originals are kept unless you add `--replace`. New files are named
  `name (compressed).ext`. A file that wouldn't get smaller is left alone.
- `ufa` uses your graphics card (NVIDIA, Intel or AMD on Windows; Apple on
  macOS) when it can, and works on several files at once.
- No FFmpeg? Odus offers to install it and then carries on. Say no and it tells
  you to run `odus install ffmpeg` or get it from ffmpeg.org first.
- Odus skips broken or very old copies of FFmpeg and also finds ones that winget
  installed without adding them to PATH.

```
odus compress-app Adobe Premiere Pro 2026     shrink an installed app in place
odus ufa compress-app "D:\Games\Some Game"    or point it at a folder
odus decompress-app Adobe Premiere Pro 2026   undo it
```

- **Windows:** the built-in `compact` tool (LZX; `fast` uses the lighter
  XPRESS8K; pick your own with `--algo xpress4k|xpress8k|xpress16k|lzx`). The
  app keeps working normally. Apps in Program Files need an admin terminal.
- **macOS:** `afsctool` (Odus offers to install it with brew).
- **Linux:** only on btrfs drives (`btrfs filesystem defragment -czstd`); other
  filesystems such as ext4 can't compress in place, and Odus says so.
- Close the app first. Files that are in use get skipped.

## Downloads

```
odus download "https://www.youtube.com/watch?v=..."   video (yt-dlp, 1000+ sites)
odus download "https://youtu.be/..." --audio          MP3 only
odus download "github.com/owner/repo"                 git clone
odus clone owner/repo                                 same, GitHub shorthand
odus ufa download "https://example.com/file.zip"      any file link
odus download "<link>" --to D:\Downloads              somewhere else
```

- Several links at once are fine; `fastplus` and `ufa` download them side by side.
- Always put links in quotes (`"..."`), like in the examples above.
- No yt-dlp or git? Odus offers to install it and then carries on. Say no and it
  shows the normal install command for your system and the command to run after.

## Live Refresh

Normally a terminal only sees PATH changes (like a newly installed tool) after
you close and reopen it. With Live Refresh, Odus brings the terminal up to date
after every command, and folders that were deleted or moved drop out of PATH.

```
odus refresh          update this terminal now and show what changed
odus refresh off      stop doing it automatically (on to turn it back on)
```

Where it works:

- **Command Prompt:** always (through `odus.bat`).
- **PowerShell:** only when PowerShell may run local scripts (Settings > System
  > For developers > PowerShell). Odus never changes that setting itself; once
  you allow scripts it adds `odus.ps1` by itself. Until then `odus` still works
  in PowerShell, just without Live Refresh.
- **macOS/Linux (bash, zsh):** after `odus path add` and opening a new terminal
  once.

## Options

`--dry-run` show the commands without running them · `--yes` don't ask ·
`--with <manager>` use one package manager · `--to <folder>` · `--audio` ·
`--replace` · `--shallow` (git: latest commit only) · `--algo <name>`

Typos and synonyms are understood: `odus fsat isntall git`,
`odus ufa upgrade-applications`, `odus compres video.mp4`.

## Making a release

1. Set `VERSION` in `odus.py`.
2. Run `python build.py`. It writes `dist/odus.bat` (Windows),
   `dist/odus.command` (macOS), `dist/odus.sh` (Linux) and `dist/odus.py`
   (plain source). Each is the whole program in one file.
3. On GitHub, create a release tagged `v<VERSION>` (for example `v0.1`) and
   upload all four files.

The private Python that the launchers can download is pinned in `build.py`
(`PY_VERSION` and its SHA-256 fingerprints). To move to a newer Python, update
the version and the fingerprints there.

## Download page

`index.html` is a one-page site: the logo and a Download button. The button
asks GitHub for the latest release and offers Windows (`.bat`), macOS
(`.command`), Linux (`.sh`) and Python source (`.py`) downloads, highlighting
the visitor's system. Older releases that only have `.cmd`/`.sh` files still
work. See More Releases lists every release so older versions can be
downloaded the same way. To put it online,
open the repo's **Settings > Pages**, choose **Deploy from a branch**, then
**main** and **/ (root)**.

## License

MIT - see [LICENSE](LICENSE).
