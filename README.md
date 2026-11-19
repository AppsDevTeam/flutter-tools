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
- **CHANGELOG.md update** — appends the new version with the bumped number, either as a raw `git log` list or written by Claude Code from the project's own rules (see [Release notes via Claude](#release-notes-via-claude)). Both are on by default for every preset; untick them per preset to opt out.
- **Obfuscation** toggle (`--obfuscate --split-debug-info`) for mobile builds.
- **Dart snapshot verification (Android)** — non-debug `apk` / `appbundle` builds drop the Gradle native-lib merge cache for the variant beforehand, and afterwards every `lib/<abi>/libapp.so` inside the artifact is matched by GNU build-id against the `libapp.so` this build actually produced. A stale snapshot or a missing ABI fails the build instead of shipping an app that runs old Dart code — or crashes on startup on the ABI whose snapshot is missing.
- **Pre-build checks** — run first, before `flutter pub get` and before the version or changelog changes, so a build that would fail at the very end stops in seconds instead:
  - **Decrypted SOPS secrets** — for every git-tracked `*.enc.*` / `*.enc` SOPS file the decrypted counterpart (`secrets.enc.properties` → `secrets.properties`, `.env.enc` → `.env`) must exist, must contain every key of a dotenv/properties file, and must not be older than the `lastmodified` date in the SOPS metadata. Problems are listed with a hint (`make secrets-decrypt` when the project's makefile has that target) and the build asks whether to continue.
  - **Android signing** — non-debug `apk` / `appbundle` builds run `./gradlew :app:validateSigning<Variant>` first, which fails when the variant's keystore is not set or missing. If the task does not exist or Gradle fails for a reason unrelated to signing (e.g. something `pub get` has yet to generate), the check is skipped.
- **Dart symbols guaranteed** — Flutter caches the AOT snapshot in `.dart_tool/flutter_build/` and does not track the `--split-debug-info` files, so after a rollback deleted the symbol folder the next build would reuse the snapshot and write no symbols. When the symbol folder has no `*.symbols` file before the build, the AOT stamps in `.dart_tool/flutter_build/*/` and the Android `build/app/intermediates/flutter/*/flutter_build.d` depfiles are deleted (without the depfile Gradle would skip `compileFlutterBuild<Variant>` as up-to-date and never reach the stamps), so `gen_snapshot` runs again (the kernel compile stays cached); an obfuscated build that still ends up without symbols fails.
- **Symbol upload** to the project's crash reporting service, chosen by `CRASH_REPORTING` (see [Crash reporting](#crash-reporting)):
  - **Firebase Crashlytics** (default) — Android via the Firebase CLI (`crashlytics:symbols:upload`), iOS via the `upload-symbols` script that ships with the FirebaseCrashlytics CocoaPod.
  - **GlitchTip** — Dart symbols, iOS dSYMs, the Android R8 mapping and web source maps via `sentry-cli`.
- **CocoaPods install** for iOS (clean reinstall before the build).
- **Upload to App Store Connect** (optional, `ipa` release builds) — instead of opening the archive in Xcode for *Distribute App*, the build uploads it with `xcodebuild -exportArchive` and the account signed in to Xcode (Settings → Accounts; the Developer role is enough, no API key). It reuses the `ExportOptions.plist` Flutter exported the IPA with, so the signing matches the flavor, and only switches `destination` to `upload`. The build number is never changed (`manageAppVersionAndBuildNumber` off): a build number App Store Connect already has is rejected instead of being uploaded under the next free number that would no longer match `pubspec.yaml`, git and the symbols. The upload runs after the git push; when it fails, the archive opens in Xcode as before so it can be uploaded by hand.
- **Git push** of `pubspec.yaml` and `CHANGELOG.md` after a successful build.
- **Web extras**: optional check for the `sqlite3.wasm` file expected by some apps; *CanvasKit z vlastního serveru* builds with `--no-web-resources-cdn`, so the browser loads Flutter's renderer from the app's own server instead of Google's CDN (stored in the project as `WEB_RESOURCES_CDN=false`); the ZIP of `build/web` is optional (on by default) — it is committed with the build, so it keeps every released build in git even after the next build rewrites `build/web`. Without the ZIP the output folder is not opened after the build.
- **Web deploy** (optional, needs git push) with Deployer, see [Web deploy](#web-deploy).
- **Presets** — saved combinations of the above so you can reproduce a release with one click.
- **Cancel** — while a build runs, the run button turns into an *Ukončit build* swipe button. Swiping it to the end stops the running command with its child processes (Gradle, xcodebuild, pod, Claude) and returns the project to its state before the build: version, changelog, `GoogleService-Info.plist`, Pods and the Xcode project, `build/web`, new symbol folders and anything the build staged in git. Once the commit and push start, the build can no longer be cancelled. A failed build is rolled back the same way.

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

## Crash reporting

`CRASH_REPORTING` in `adt_tools_config.env` picks the service that receives symbols: `firebase` (default, the original behaviour), `glitchtip` or `none`. Like other keys it can be set per flavor/env (`CRASH_REPORTING_<flavor>_<env>`).

The build tab shows the service and lets you switch it (*Hlášení pádů*); the choice is written to `adt_tools_config.env`, so it applies to everyone building the project. With a per-flavor/env value in the file the selector only shows it. For GlitchTip, *Nastavit…* opens a dialog for the URL, organisation and project with a hint where to find each value. Switching to GlitchTip without them opens the dialog right away, and starting a build with symbol upload while any of them is missing offers the same dialog with *Uložit a pokračovat*, *Pokračovat bez nahrání symbolů* and *Zrušit*.

- **firebase** — `GoogleService-Info.plist` is copied for iOS (`IOS_PLIST_*`, required), symbols go to Crashlytics (`FIREBASE_APP_ID`).
- **glitchtip** — no Firebase files are needed. With *Nahrát symboly* checked, `sentry-cli` uploads:
  - Android: Dart symbols from `--split-debug-info` and the R8 `mapping.txt` when the build is minified,
  - iOS: Dart symbols and the archive's dSYMs,
  - web: the build runs with `--source-maps`; the maps are uploaded to the release after the local verification and then **deleted from `build/web`**, so they reach neither the server nor git / the ZIP (also when the upload fails).
- **none** — nothing is uploaded and iOS needs no `GoogleService-Info.plist`.

GlitchTip settings:

```env
CRASH_REPORTING=glitchtip
GLITCHTIP_URL=https://glitchtip.yourcompany.com
GLITCHTIP_ORG=yourcompany
GLITCHTIP_PROJECT=yourapp
```

These keys live in the project repository, so everyone who builds the project uploads to the same place. The build tab shows the service and GlitchTip target resolved for the selected flavor/env, so it is visible before the build where the symbols go; missing GlitchTip keys are reported before the build starts.

The upload token is personal and never goes into the repository: enter it in the build tab (*GlitchTip token*, shown when the project uses GlitchTip). It is stored in the tool's local `config.json` (git-ignored) and shared by all projects. Without it the tool falls back to `SENTRY_AUTH_TOKEN` (or `GLITCHTIP_AUTH_TOKEN`) in the environment, then to a `sentry-cli login` (`~/.sentryclirc`). The token reaches `sentry-cli` through the environment, so it does not appear in the build console.

Symbols are matched to errors by the release name `<PACKAGE_NAME>@<version>+<build>` (e.g. `cz.firma.app@1.2.3+45`). With `glitchtip` every build gets it as `--dart-define=SENTRY_RELEASE=…`; pass it to the SDK:

```dart
await SentryFlutter.init((options) {
  options.dsn = '…';
  options.release = const String.fromEnvironment('SENTRY_RELEASE');
}, appRunner: …);
```

The SDK's default release does not match on the web (`package_info` returns the Dart package name there, not the app's package name).

## Web deploy

For projects deployed with Deployer from `adt/docker-deployer` (`deploy.php`, `config/.env.<stage>`, `make dep` / `make dep-pub`). The server clones the branch `BRANCH` from `config/.env.<stage>` and serves the committed `build/web`, so the deploy runs only after a successful push. Enable it in the project's `adt_tools_config.env`:

```env
WEB_DEPLOY_STAGE=test
```

Like `DART_DEFINES_*`, the stage can be set per flavor / env (`WEB_DEPLOY_STAGE_<flavor>_<env>`, `_<flavor>`, `_<env>`, then the plain key), so a build for another API environment goes to its own server. An empty value disables the deploy for that build, e.g. while the production web does not exist yet:

```env
WEB_DEPLOY_STAGE=test
WEB_DEPLOY_STAGE_prod=
```

Without a value for the selected flavor / env the *Nasadit na server* option in the Web box stays disabled (and unchecked). With it, a web build with git push and the option checked continues after the push:

1. Moves `BRANCH` on the remote to the build commit (`git push <remote> HEAD:<BRANCH>`, no force), unless the build already is on that branch. A branch with commits the build branch does not have stops the deploy; merge it by hand.
2. Runs `composer install` when `vendor/bin/dep` is missing — through the `composer:2` Docker image when composer is not installed.
3. Checks that Docker runs; on macOS a stopped Docker is started (OrbStack or Docker Desktop by the active Docker context) and the deploy waits until it responds.
4. `make dep -- <stage>` uploads the release to the servers (the SSH key in the agent is required).
5. Asks for confirmation, then `make dep-pub -- <stage>` switches the site to the new release. Declining leaves the release uploaded; publish later with `make dep-pub -- <stage>`.

A failed deploy does not fail the build: the build is already committed and pushed, so only the deploy needs repeating. The final message then says that the deploy failed instead of reporting success.

## Release notes via Claude

*Aktualizovat CHANGELOG.md* and *Sepsat přes Claude* are checked by default in every new preset, and a `config.json` written before this default existed is brought up to it once on start (`config_version` in the file records that the step ran, so a preset you untick afterwards stays unticked). With *Aktualizovat CHANGELOG.md* checked, the tool normally inserts a section `## [X.Y.Z+BUILD] - date` followed by one bullet per commit since the last change of `CHANGELOG.md`. Checking *Sepsat přes Claude* instead runs

```
claude -p "/release-notes X.Y.Z+BUILD" --model sonnet --effort medium --fallback-model opus --permission-mode acceptEdits
```

in the project directory before the build. The slash command lives in the project at `.claude/commands/release-notes.md` and carries the rules: Czech wording a non-programmer understands, changes grouped by functional area, ticket links. The first run creates it from a built-in template (with Jira links when `JIRA_BROWSE_URL` is set in `adt_tools_config.env`; `JIRA_PROJECT_KEYS=TAPY,PAY` limits which ticket codes count as Jira, anything else found in a Trello card slug links to Trello); after that the file belongs to the project, the tool never overwrites it, so edit the rules there. The section header `## [X.Y.Z+BUILD]` is the contract between the two: the tool checks for it to know a section already exists, so the command must keep it exact.

Builds made with the changelog option off leave released versions without an entry. Both paths handle that: the tool finds every `Version|Build|Symbols|Cocoapods … X.Y.Z (BUILD) -env` commit since the last changelog change, treats each distinct version as a release boundary (prerelease-only versions excluded), and writes one section per missed release, dated by its build commit, below the new version's section. Claude gets the list and the commit ranges in the prompt; the git log fallback splits the same way.

Claude never blocks a build. If the `claude` binary is missing (looked up on `PATH`, then `~/.local/bin`, `~/.claude/local`, `~/.npm-global/bin`, Homebrew), the CLI exits with an error, runs past 15 minutes, or leaves `CHANGELOG.md` without the version header, the tool logs a warning with the tail of Claude's output and falls back to the `git log` list.

Model choice: `sonnet` at `medium` effort writes well in Czech and groups commits reliably; heavier models mostly add cost here. The values are **aliases**, not pinned model IDs, so the CLI always resolves them to the current model of that family and a retired version (`claude-sonnet-5-5` and the like) does not break anything. `--fallback-model opus` covers a primary that is overloaded or unavailable. Should an alias itself disappear, the CLI fails, the warning in the build console says so, and the fix is either `RELEASE_NOTES_MODEL` / `RELEASE_NOTES_EFFORT` / `RELEASE_NOTES_FALLBACK_MODEL` in the project's `adt_tools_config.env` or the defaults in `src/constants.py`.

## Requirements

- **Required**: Python 3, Tkinter, Git, Flutter SDK.
- **Optional**: Firebase CLI (Crashlytics symbol upload), sentry-cli (GlitchTip symbol and source map upload), CocoaPods (iOS builds, macOS only), Claude Code CLI logged in (release notes via Claude), Docker and make (web deploy).

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

`--project <folder>` opens the project stored for that folder (or for a folder above it) instead of the last used one; a Flutter project the tool does not know yet is offered in the *Přidat projekt* dialog with its path and name filled in.

## VS Code button

`vscode_extension/` adds a button that opens the tool from VS Code: the tool's icon above the editor (next to *Run*) and *ADT Tools* in the status bar. It opens the tool with the project of the VS Code window, so you do not have to switch projects in the tool by hand:

- **The tool is not running** — it starts with that project.
- **The tool is running** — the open window switches to that project and comes to the front; no second window opens. While a build or another task runs, it stays on its project and says so.
- **The project is not in the tool yet** — the *Přidat projekt* dialog opens with the path and name filled in; saving it opens the project. A folder without `pubspec.yaml` leaves the tool on its current project.

Install it once from the repository (needs only Python, no Node.js):

```bash
python3 vscode_extension/install.py
```

then in VS Code run *Developer: Reload Window* (Cmd/Ctrl+Shift+P). The script writes the path of your clone into the extension, so the button starts `main.py` from wherever you keep the repository. Run it again after moving the repository or when the extension changes. Without the `code` command in PATH, run *Shell Command: Install 'code' command in PATH* in VS Code first; for Cursor use `--editor cursor`. The `adtTools.dir` setting overrides the folder if needed.

The tool starts through your login shell (`python3` from your PATH, as in a terminal); its output goes to `~/.cache/adt_flutter_tools/vscode-launch.log`. On macOS, bringing the window to the front uses System Events; allow it if macOS asks.

## Building a release binary

A PyInstaller spec is included. The repository's release helper does the work:

```bash
python3 build_release.py
```

The output binary is placed in `dist/`.

## Repository layout

```
main.py             — entry point (`--project`, `--from-editor`)
vscode_extension/   — VS Code button, installed by install.py
setup.sh            — interactive dependency installer
build_release.py    — PyInstaller wrapper
src/
  constants.py      — config keys and the adt_tools_config.env template
  config_manager.py — persisted UI settings (config.json)
  instance_link.py  — hands a VS Code request over to the running app
  ui/               — Tkinter app, main window, project selector, in-app logger
  logic/
    build_logic.py  — orchestrates the full build pipeline
    build_common.py — pubspec parsing, version bumping, changelog, git push
    release_notes.py — CHANGELOG.md section written by Claude Code, command template
    build_android.py / build_ios.py / build_web.py / build_desktop.py
    serializable_logic.py — JsonSerializable tab actions
    nbsp_logic.py         — non-breaking space insertion
```
