# ADT Flutter Tools

A desktop GUI utility (Python + Tkinter) that automates the routine work around Flutter projects: building releases for all platforms, bumping versions, updating the changelog, pushing to git, regenerating `json_serializable` code, and adding non-breaking spaces to translation files.

It targets the workflow used at AppsDevTeam, where each Flutter project carries an `adt_tools_config.env` file describing its package name, flavors, environments, Firebase App IDs, dart-defines and per-flavor `GoogleService-Info.plist` paths.

## Features

The app is organised into three tabs.

### Build

Runs a parametrised Flutter build with all the steps you would normally chain by hand.

- **Targets**: `apk`, `appbundle`, `ipa`, `web`, `macos`, `linux`, `windows`.
- **Modes**: `release`, `debug`, `profile`.
- **Flavors and environments** resolved from `adt_tools_config.env` — `FIREBASE_APP_ID`, `IOS_PLIST_*`, `DART_DEFINES_*` and `DART_DEFINE_FILES` are picked per `<flavor>_<env>` and copied / passed to the Flutter command.
- **Version bumping**: `major` / `minor` / `patch` / `build` directly in `pubspec.yaml`, with automatic revert if the build fails.
- **CHANGELOG.md update** — appends the new version with the bumped number, either as a raw `git log` list or written by Claude Code from the project's own rules (see [Release notes via Claude](#release-notes-via-claude)).
- **Obfuscation** toggle (`--obfuscate --split-debug-info`) for mobile builds.
- **Dart snapshot verification (Android)** — non-debug `apk` / `appbundle` builds drop the Gradle native-lib merge cache for the variant beforehand, and afterwards every `lib/<abi>/libapp.so` inside the artifact is matched by GNU build-id against the `libapp.so` this build actually produced. A stale snapshot or a missing ABI fails the build instead of shipping an app that runs old Dart code — or crashes on startup on the ABI whose snapshot is missing.
- **Symbol upload to Firebase Crashlytics** — Android via the Firebase CLI (`crashlytics:symbols:upload`), iOS via the `upload-symbols` script that ships with the FirebaseCrashlytics CocoaPod.
- **CocoaPods install** for iOS (clean reinstall before the build).
- **Git push** of `pubspec.yaml` and `CHANGELOG.md` after a successful build.
- **Web extras**: optional check for the `sqlite3.wasm` file expected by some apps.
- **Presets** — saved combinations of the above so you can reproduce a release with one click.

The full output of every step is streamed into an in-app console.

### JsonSerializable

Runs the standard codegen sequence in order:

```
flutter clean
flutter packages pub get
dart run build_runner build --delete-conflicting-outputs
```

### Non-breaking spaces (Nezalomitelná mezera)

Walks translation JSON files (`cs`, `sk`, `en`, `de`) and inserts ` ` after one-letter prepositions and conjunctions (`a`, `i`, `k`, `o`, `s`, `u`, `v`, `z` for Czech/Slovak; language-specific lists for the others). Skips strings that already contain a non-breaking space or a newline.

## Project configuration

Each Flutter project the tool operates on contains an `adt_tools_config.env` file at its root. Example:

```env
PACKAGE_NAME="com.yourcompany.yourapp"

# Optional: desktop binary name
# DESKTOP_APP_NAME="MyApp"

# Per-flavor / per-env Firebase App IDs (used for symbol upload)
FIREBASE_APP_ID_cashdesk_prod="1:..."
FIREBASE_APP_ID_cashdesk_prerelease="1:..."

# Per-flavor / per-env dart defines
DART_DEFINES_SHOW_BANNER_prod=false
DART_DEFINES_SHOW_BANNER_prerelease=true

# Per-flavor / per-env dart defines loaded from a file (--dart-define-from-file).
# Use it for a group of values that belong together and must not leak into another
# flavor's build; the same file can be referenced from the IDE's launch config, so
# the values live in one place only. Missing file fails the build.
DART_DEFINE_FILES_tapygo=dart_defines/tapygo.json

# Per-flavor / per-env GoogleService-Info.plist
IOS_PLIST_DEFAULT=ios/Firebase/GoogleService-Info.plist
IOS_PLIST_cashdesk_prod=ios/Firebase/GoogleService-Info.plist
IOS_PLIST_cashdesk_prerelease=ios/Firebase/GoogleService-Info-Prerelease.plist
```

Keys without a flavor/env suffix are used as a fallback. The tool will create a stub file the first time you point it at a project.

## Release notes via Claude

With *Aktualizovat CHANGELOG.md* checked, the tool normally inserts a section `## [X.Y.Z+BUILD] - date` followed by one bullet per commit since the last change of `CHANGELOG.md`. Checking *Sepsat přes Claude* instead runs

```
claude -p "/release-notes X.Y.Z+BUILD" --model sonnet --effort medium --fallback-model opus --permission-mode acceptEdits
```

in the project directory before the build. The slash command lives in the project at `.claude/commands/release-notes.md` and carries the rules: Czech wording a non-programmer understands, changes grouped by functional area, ticket links. The first run creates it from a built-in template (with Jira links when `JIRA_BROWSE_URL` is set in `adt_tools_config.env`); after that the file belongs to the project, the tool never overwrites it, so edit the rules there. The section header `## [X.Y.Z+BUILD]` is the contract between the two: the tool checks for it to know a section already exists, so the command must keep it exact.

Claude never blocks a build. If the `claude` binary is missing (looked up on `PATH`, then `~/.local/bin`, `~/.claude/local`, `~/.npm-global/bin`, Homebrew), the CLI exits with an error, runs past 15 minutes, or leaves `CHANGELOG.md` without the version header, the tool logs a warning with the tail of Claude's output and falls back to the `git log` list.

Model choice: `sonnet` at `medium` effort writes well in Czech and groups commits reliably; heavier models mostly add cost here. The values are **aliases**, not pinned model IDs, so the CLI always resolves them to the current model of that family and a retired version (`claude-sonnet-5-5` and the like) does not break anything. `--fallback-model opus` covers a primary that is overloaded or unavailable. Should an alias itself disappear, the CLI fails, the warning in the build console says so, and the fix is either `RELEASE_NOTES_MODEL` / `RELEASE_NOTES_EFFORT` / `RELEASE_NOTES_FALLBACK_MODEL` in the project's `adt_tools_config.env` or the defaults in `src/constants.py`.

## Requirements

- **Required**: Python 3, Tkinter, Git, Flutter SDK.
- **Optional**: Firebase CLI (Crashlytics symbol upload), CocoaPods (iOS builds, macOS only), Claude Code CLI logged in (release notes via Claude).

## Setup

Run the interactive installer once. It detects your OS and the available package managers (`brew`, `npm`, `gem`, `apt`, `dnf`, `pacman`, `zypper`, `snap`, `winget`, `scoop`, `choco`) and offers to install everything that is missing. When more than one option is available it asks which one you want to use.

```bash
./setup.sh
```

If the script is not executable (e.g. after downloading a ZIP), make it executable first:

```bash
chmod +x setup.sh
```

On Windows use Git Bash, WSL, or `bash setup.sh` from PowerShell.

## Running

```bash
python3 main.py
```

On first launch, point the project selector at a Flutter project directory. The tool remembers it for next time.

## Building a release binary

A PyInstaller spec is included. The repository's release helper does the work:

```bash
python3 build_release.py
```

The output binary is placed in `dist/`.

## Repository layout

```
main.py             — entry point
setup.sh            — interactive dependency installer
build_release.py    — PyInstaller wrapper
src/
  constants.py      — config keys and the adt_tools_config.env template
  config_manager.py — persisted UI settings (config.json)
  ui/               — Tkinter app, main window, project selector, in-app logger
  logic/
    build_logic.py  — orchestrates the full build pipeline
    build_common.py — pubspec parsing, version bumping, changelog, git push
    release_notes.py — CHANGELOG.md section written by Claude Code, command template
    build_android.py / build_ios.py / build_web.py / build_desktop.py
    serializable_logic.py — JsonSerializable tab actions
    nbsp_logic.py         — non-breaking space insertion
```
