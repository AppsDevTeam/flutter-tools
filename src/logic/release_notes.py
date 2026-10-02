# src/logic/release_notes.py
"""
Release notes psané přes Claude Code CLI.

Nástroj sám umí jen syrový výpis `git log` (build_common.update_changelog). Tady
se místo něj zavolá `claude -p "/release-notes <verze>"`: slash command v projektu
(.claude/commands/release-notes.md) nese pravidla, jak má záznam vypadat — oblasti,
jazyk, odkazy na tikety. Pravidla tak žijí v repu projektu, kde je tým může upravit,
a nástroj zůstává obecný. Když projekt soubor nemá, založí se ze šablony níže.

Claude nikdy nesmí zastavit build: při jakémkoli selhání (binárka nenalezena, chyba
CLI, timeout, chybějící hlavička verze) se vrací False a volající použije git log.
"""
import os
import re
import shutil
import subprocess
import threading

from ..constants import (
    ADT_PROJECT_CONFIG_FILENAME,
    RELEASE_NOTES_COMMAND_NAME, RELEASE_NOTES_MODEL, RELEASE_NOTES_EFFORT,
    RELEASE_NOTES_FALLBACK_MODEL, RELEASE_NOTES_TIMEOUT_S,
)

CHANGELOG_FILENAME = "CHANGELOG.md"
COMMAND_DIR = os.path.join(".claude", "commands")
COMMAND_FILE = os.path.join(COMMAND_DIR, f"{RELEASE_NOTES_COMMAND_NAME}.md")

# GUI spuštěné z Finderu/Docku má minimální PATH (bez ~/.local/bin ani Homebrew),
# takže `claude` i `git` je potřeba hledat i tady. Bez toho by Claude tiše nikdy
# neběžel a nástroj by vždy spadl na git log.
_EXTRA_BIN_DIRS = [
    os.path.expanduser("~/.local/bin"),
    os.path.expanduser("~/.claude/local"),
    os.path.expanduser("~/.npm-global/bin"),
    "/opt/homebrew/bin",
    "/usr/local/bin",
]

# Šablona slash commandu. {jira_rule} doplní ensure_release_notes_command() podle
# JIRA_BROWSE_URL a volitelného JIRA_PROJECT_KEYS (čárkami oddělené klíče projektů;
# bez něj se za Jira považuje každý kód KLÍČ-123) v adt_tools_config.env.
COMMAND_TEMPLATE = """---
description: Dopíše lidsky čitelný záznam nové verze do CHANGELOG.md z commitů od poslední aktualizace changelogu
argument-hint: <verze např. 1.15.22+245>
allowed-tools: Read, Grep, Glob, Edit, Bash(git log:*), Bash(git show:*), Bash(git diff:*), Bash(date:*)
---

Připrav release notes pro verzi **$1** do `CHANGELOG.md`.

Soubor i tento command spravuje build nástroj ADT Flutter Tools (volba „Sepsat přes
Claude" u aktualizace CHANGELOG.md). Pravidla níže patří projektu — upravuj je tady.

## Postup

1. Zjisti rozsah commitů. Changelog generuje i build nástroj, takže hranicí není tag,
   ale poslední commit, který měnil `CHANGELOG.md`:
   `git log -1 --format=%H -- CHANGELOG.md`
2. Vypiš commity od něj a vynech commity samotného build nástroje
   (`Version …`, `Symbols …`, `Build …`, `Cocoapods …`, `Web Build …`, `Desktop Build …`):
   `git log <sha>..HEAD --no-merges --invert-grep --extended-regexp --grep='^(Version|Web Build|Desktop Build|Symbols|Cocoapods|Build) ' --pretty=format:'%h %s%n%b%n---'`
   — čti i tělo commitu, bývá v něm důvod změny a verze, ve které se chyba projevila
3. U commitů, z jejichž předmětu není jasné, co se pro uživatele změnilo (`fix`, `wip`,
   `oprava crashe`, holá URL tiketu nebo Crashlytics), si **přečti diff**:
   `git show <hash> -- lib/ | head -300` (seznam souborů ze `--stat` nestačí, z názvů
   souborů se obsah změny jen hádá). Tiket z takového commitu patří jen k odrážce
   popisující právě tuto změnu — nikdy ho nepřilepuj k jiné odrážce jen proto, že je
   ve stejném releasu
4. Pokud sekce `## [$1]` v `CHANGELOG.md` už existuje (nástroj ji založil jako syrový
   výpis `git log`), přepiš její obsah a rozsah commitů vezmi mezi posledními dvěma
   commity, které `CHANGELOG.md` měnily: `git log -2 --format=%H -- CHANGELOG.md`
5. Přečti si 2–3 nejnovější záznamy v `CHANGELOG.md`. Formát níže má vždy přednost;
   ze starších záznamů přebírej jen názvy oblastí a tón, a to pouze pokud už tento
   formát mají — syrové výpisy commitů (jedna odrážka na commit bez oblastí), které
   dřív generoval nástroj, nenapodobuj
6. Nový záznam vlož **nad dosavadní nejnovější záznam** (hned pod úvodní text souboru)
7. Než skončíš, projdi seznam commitů z kroku 2 ještě jednou a ověř, že každý je
   v záznamu zastoupen (vlastní odrážkou, nebo sloučený do jiné); samostatná oprava
   pádu nesmí zmizet sloučením

## Formát záznamu

```
## [$1] - RRRR-MM-DD

Jedna věta o zaměření releasu (jen když je změn víc než zhruba osm).

**Oblast:**
- popis změny — [KLÍČ-123](odkaz na tiket)
```

- Hlavička musí být přesně `## [$1] - <datum>`; podle ní build nástroj pozná, že záznam
  pro tuto verzi už existuje, a nepřipíše svůj syrový výpis
- Datum = dnešní den v ISO tvaru `RRRR-MM-DD` (`date +%F`)
- Změny seskupuj podle funkčních oblastí, které už soubor používá — novou oblast zaveď,
  jen když žádná existující nesedí; sekce **Infrastruktura** je pro interní změny
- Změna platná jen pro některý flavor nese jeho jméno v textu odrážky

## Odkazy na tikety

{jira_rule}
- **Trello**: Trello URL z commitu uveď jako ` — [Trello 9804](https://trello.com/c/8VvgZJmD)`
  — text odkazu je číslo karty ze slugu, URL stačí krátká, bez slugu. Když slug karty
  obsahuje klíč Jira (`…-tapy-245`), jde o tutéž věc — uveď jen odkaz na Jira, Trello
  vynech. Trello odkaz tedy zůstává jen u karet bez klíče Jira
- Víc tiketů u jedné odrážky odděluj čárkou; víc odrážek k jednomu tiketu je v pořádku
- URL na Crashlytics ani jiné interní konzole nekopíruj — napiš „pád hlášený
  v Crashlytics" a verzi, ve které se projevil, pokud ji commit uvádí

## Pravidla

- Piš česky s diakritikou, věcně a konkrétně — uživatelsky viditelné změny popiš tak, aby
  jim rozuměl i ne-programátor (co se stalo a proč); u technických změn uveď dotčené
  třídy/soubory v backtickách
- Oprava chyby říká, co uživatel viděl a kdy (např. „po přepnutí záložky padala aplikace
  při přesunu účtu"), ne jen co se změnilo v kódu
- Interní drobnosti (formátování, CI, refactoring, úpravy testů, launch konfigurace)
  shrň do jedné–dvou odrážek v sekci **Infrastruktura**
- Commity, které mění jen `CHANGELOG.md`, `.claude/commands/release-notes.md` nebo
  `adt_tools_config.env`, do záznamu nepatří — jsou to úpravy release notes samotných
- Řádky `Co-Authored-By` v tělech commitů ignoruj
- **Neměň nic jiného** v souboru (hlavičku, starší záznamy)
- Po dokončení vypiš jen stručné shrnutí, co jsi do záznamu zahrnul
"""

_JIRA_RULE_WITH_URL = """- **Jira**: klíč ve tvaru `TAPY-245` připoj na konec odrážky jako odkaz
  ` — [TAPY-245]({url}/TAPY-245)`. Hledej ho v předmětu i těle commitu, včetně
  Trello slugu (`9804-pokladna-tapy-245` → `TAPY-245`) a Jira URL
  (`selectedIssue=PAY-8` → `PAY-8`). {projects}Zkratky jako `SHA-256` nebo `BSD-3` tikety nejsou"""

_JIRA_PROJECTS_RULE = """Jira projekty jsou jen {keys}; jiný kód ve slugu
  Trello karty (např. `tvsb-635`) Jira není — odkaz veď na Trello, text odkazu je ten
  kód: ` — [TVSB-635](https://trello.com/c/xxdgisLj)`. """

_JIRA_RULE_WITHOUT_URL = """- **Jira**: klíč ve tvaru `PROJEKT-123` uveď na konci odrážky jako prostý text; projekt
  nemá v `adt_tools_config.env` nastavené `JIRA_BROWSE_URL`, takže odkaz není kam vést.
  Zkratky jako `SHA-256` nebo `BSD-3` tikety nejsou"""


def find_claude():
    """Vrátí cestu k binárce `claude`, nebo None."""
    found = shutil.which("claude")
    if found:
        return found
    for directory in _EXTRA_BIN_DIRS:
        candidate = os.path.join(directory, "claude")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def render_command_template(env_vars):
    """Sestaví obsah slash commandu podle hodnot z adt_tools_config.env."""
    jira_url = (env_vars or {}).get("JIRA_BROWSE_URL", "").strip().rstrip("/")
    keys = [k.strip() for k in (env_vars or {}).get("JIRA_PROJECT_KEYS", "").split(",") if k.strip()]
    projects = _JIRA_PROJECTS_RULE.format(keys=", ".join(f"`{k}`" for k in keys)) if keys else ""
    jira_rule = _JIRA_RULE_WITH_URL.format(url=jira_url, projects=projects) if jira_url else _JIRA_RULE_WITHOUT_URL
    return COMMAND_TEMPLATE.replace("{jira_rule}", jira_rule)


def ensure_release_notes_command(logger, env_vars):
    """
    Zajistí, že projekt má .claude/commands/release-notes.md. Existující soubor se
    nikdy nepřepisuje — je to projektová konfigurace, ne výstup nástroje.
    Vrací True, když soubor existuje (ať už byl, nebo se právě založil).
    """
    if os.path.isfile(COMMAND_FILE):
        return True

    try:
        os.makedirs(COMMAND_DIR, exist_ok=True)
        with open(COMMAND_FILE, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_command_template(env_vars))
    except Exception as e:
        logger.error(f"Nepodařilo se založit {COMMAND_FILE}: {e}")
        return False

    logger.info(
        f"ℹ️ Založen {COMMAND_FILE} s výchozími pravidly pro release notes. "
        f"Commitne se s buildem — upravte si ho podle projektu."
    )
    if not (env_vars or {}).get("JIRA_BROWSE_URL"):
        logger.warn(
            f"⚠️ V {ADT_PROJECT_CONFIG_FILENAME} chybí JIRA_BROWSE_URL, tikety Jira budou "
            f"v release notes bez odkazu. Po doplnění smažte {COMMAND_FILE}, založí se znovu."
        )
    return True


def changelog_has_section(version_str):
    """True, když CHANGELOG.md obsahuje hlavičku `## [<verze>]`."""
    if not os.path.exists(CHANGELOG_FILENAME):
        return False
    try:
        with open(CHANGELOG_FILENAME, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False
    return re.search(rf"^## \[{re.escape(version_str)}\]", content, re.MULTILINE) is not None


def write_release_notes_with_claude(logger, version_str, env_vars):
    """
    Nechá Claude dopsat záznam verze do CHANGELOG.md. Vrací True jen tehdy, když po
    doběhnutí v souboru hlavička verze opravdu je; všechno ostatní je False a volající
    má použít výpis git log.
    """
    env_vars = env_vars or {}
    claude = find_claude()
    if not claude:
        logger.warn("⚠️ Binárka `claude` nenalezena (PATH ani ~/.local/bin, Homebrew). Release notes přes Claude se přeskakují.")
        return False

    if not ensure_release_notes_command(logger, env_vars):
        return False

    model = env_vars.get("RELEASE_NOTES_MODEL", RELEASE_NOTES_MODEL)
    effort = env_vars.get("RELEASE_NOTES_EFFORT", RELEASE_NOTES_EFFORT)
    fallback_model = env_vars.get("RELEASE_NOTES_FALLBACK_MODEL", RELEASE_NOTES_FALLBACK_MODEL)

    command = [
        claude, "-p", f"/{RELEASE_NOTES_COMMAND_NAME} {version_str}",
        "--model", model,
        "--effort", effort,
        "--permission-mode", "acceptEdits",
    ]
    if fallback_model:
        command += ["--fallback-model", fallback_model]

    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([os.path.dirname(claude)] + _EXTRA_BIN_DIRS + [env.get("PATH", "")])

    logger.header(f"--- Release notes přes Claude ({model}, effort {effort}) ---")
    logger.info(f"🔧 Spouštím: {' '.join(command)}")

    ret_code, output = _run_streaming(command, logger, env, RELEASE_NOTES_TIMEOUT_S)

    if ret_code is None:
        logger.warn(f"⚠️ Claude nedoběhl do {RELEASE_NOTES_TIMEOUT_S // 60} minut a byl ukončen. Použije se výpis git log.")
        return False
    if ret_code != 0:
        tail = output.strip().splitlines()[-5:]
        logger.warn("⚠️ Claude skončil chybou, použije se výpis git log. Konec výstupu:")
        for line in tail:
            logger.warn(f"   {line}")
        logger.warn(
            f"   Pokud hlásí neznámý model, alias '{model}' už neexistuje — změňte RELEASE_NOTES_MODEL "
            f"v {ADT_PROJECT_CONFIG_FILENAME}, nebo výchozí hodnotu v nástroji (src/constants.py)."
        )
        return False
    if not changelog_has_section(version_str):
        logger.warn(f"⚠️ Claude doběhl, ale v {CHANGELOG_FILENAME} chybí hlavička `## [{version_str}]`. Použije se výpis git log.")
        return False

    logger.success(f"✅ Release notes pro [{version_str}] napsal Claude ({model}).")
    return True


def _run_streaming(command, logger, env, timeout_s):
    """
    Spustí příkaz, výstup průběžně posílá do loggeru. Vrací (returncode, výstup);
    returncode je None, když proces skončil na timeout.
    Vlastní implementace místo execute_command kvůli env, timeoutu a stdin=DEVNULL —
    `claude -p` by jinak čekal na vstup z roury.
    """
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            startupinfo=startupinfo, env=env,
        )
    except FileNotFoundError:
        logger.error(f"PŘÍKAZ NENALEZEN: {command[0]}")
        return -1, ""
    except Exception as e:
        logger.error(f"CHYBA PŘI SPUŠTĚNÍ: {e}")
        return -1, str(e)

    timed_out = threading.Event()

    def _kill():
        timed_out.set()
        process.kill()

    watchdog = threading.Timer(timeout_s, _kill)
    watchdog.start()

    output_lines = []
    try:
        for line in iter(process.stdout.readline, ""):
            logger.raw(line)
            output_lines.append(line)
        process.stdout.close()
        process.wait()
    finally:
        watchdog.cancel()

    if timed_out.is_set():
        return None, "".join(output_lines)
    return process.returncode, "".join(output_lines)
