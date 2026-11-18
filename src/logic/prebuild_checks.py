# src/logic/prebuild_checks.py
"""
Kontroly hned na začátku buildu (ještě před `flutter pub get`): věci, na kterých by
build jinak spadl až na konci, po kompilaci Dartu a po změně verze.

- Dešifrované SOPS soubory: v gitu jsou jen zašifrované `*.enc.*` a vedle nich leží
  dešifrované protějšky (v .gitignore). Když někdo zašifrovaný soubor změní (nový
  klíč, nový keystore), dešifrovaný zůstane starý a nikdo to nepozná.
- Podepisování Androidu: AGP má pro každou podepisovanou variantu úlohu
  `validateSigning<Varianta>`, která ověří, že je keystore nastavený a existuje.
  Při buildu ji Gradle spustí až před zabalením APK/AAB, tady se spustí samostatně.
"""
import os
import re
import subprocess
from datetime import datetime, timezone

from .build_common import execute_command
from .android_snapshot_check import variant_name

# Datum poslední změny, které sops zapisuje do metadat zašifrovaného souboru:
# dotenv `sops_lastmodified=...`, JSON / binary `"lastmodified": "..."`, YAML `lastmodified: '...'`.
_SOPS_LASTMODIFIED_RE = re.compile(
    r'''(?:sops_lastmodified=|"lastmodified"\s*:\s*"|lastmodified:\s*['"]?)'''
    r'''(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)'''
)
_DOTENV_KEY_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_.\-]*)\s*=')
_MAX_LISTED_KEYS = 6


def _decrypted_path(enc_path):
    """'a/secrets.enc.properties' -> 'a/secrets.properties', '.env.enc' -> '.env'. Jinak None."""
    directory, name = os.path.split(enc_path)
    parts = name.split('.')
    # 'enc' jako první část jména ('enc.txt') není přípona SOPS konvence.
    if 'enc' not in parts[1:]:
        return None
    index = len(parts) - 1 - parts[::-1].index('enc')
    plain_name = '.'.join(parts[:index] + parts[index + 1:])
    return os.path.join(directory, plain_name) if plain_name else None


def _tracked_encrypted_files():
    """Soubory se segmentem `.enc` ve jméně, které git trackuje. Mimo git repozitář prázdný seznam."""
    try:
        result = subprocess.run(
            ['git', 'ls-files', '-z'], capture_output=True, text=True, encoding='utf-8'
        )
    except (FileNotFoundError, OSError):
        return []
    if result.returncode != 0:
        return []
    return [p for p in result.stdout.split('\0') if p and _decrypted_path(p)]


def _read_text(path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


def _dotenv_keys(content):
    keys = set()
    for line in content.splitlines():
        match = _DOTENV_KEY_RE.match(line)
        if match and not match.group(1).startswith('sops_'):
            keys.add(match.group(1))
    return keys


def find_stale_sops_secrets():
    """
    Vrátí seznam problémů s dešifrovanými SOPS soubory (prázdný = vše v pořádku).

    Dešifrovaný soubor je podezřelý, když chybí, když je starší než poslední změna
    zašifrovaného souboru podle metadat sops, nebo (u dotenv / properties) když v něm
    chybí klíče, které zašifrovaný soubor má. Čas změny zašifrovaného souboru na disku
    se nepoužívá, protože ho git při každém checkoutu přepíše.
    """
    problems = []

    for enc_path in _tracked_encrypted_files():
        content = _read_text(enc_path)
        if content is None or 'sops' not in content:
            continue

        plain_path = _decrypted_path(enc_path)
        if not os.path.exists(plain_path):
            problems.append(f"{plain_path} chybí (zašifrovaný: {enc_path})")
            continue

        if 'sops_lastmodified=' in content:
            plain_content = _read_text(plain_path) or ''
            missing = sorted(_dotenv_keys(content) - _dotenv_keys(plain_content))
            if missing:
                listed = ', '.join(missing[:_MAX_LISTED_KEYS])
                if len(missing) > _MAX_LISTED_KEYS:
                    listed += f" a dalších {len(missing) - _MAX_LISTED_KEYS}"
                problems.append(f"{plain_path} nemá klíče, které má {enc_path}: {listed}")
                continue

        match = _SOPS_LASTMODIFIED_RE.search(content)
        if not match:
            continue
        try:
            encrypted_at = datetime.fromisoformat(match.group(1).replace('Z', '+00:00'))
        except ValueError:
            continue
        decrypted_at = datetime.fromtimestamp(os.path.getmtime(plain_path), tz=timezone.utc)
        if decrypted_at < encrypted_at:
            problems.append(
                f"{plain_path} je starší než poslední změna {enc_path} "
                f"({encrypted_at.astimezone().strftime('%Y-%m-%d %H:%M')})"
            )

    return problems


def decrypt_hint():
    """Jak dešifrované soubory obnovit — podle makefile projektu, jinak obecně."""
    for name in ('makefile', 'Makefile'):
        content = _read_text(name)
        if content and re.search(r'^secrets-decrypt\s*:', content, re.MULTILINE):
            return "Spusť v projektu 'make secrets-decrypt'."
    return "Dešifruj je znovu přes sops."


def _gradle_failure_reason(output):
    """Vytáhne z výstupu Gradlu blok 'What went wrong', jinak posledních pár řádků."""
    match = re.search(r'\* What went wrong:\s*\n(.*?)(?:\n\s*\n|\n\* Try:)', output, re.DOTALL)
    if match:
        return match.group(1).strip()
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return '\n'.join(lines[-5:])


def _is_signing_failure(reason):
    """Selhala úloha validateSigning, nebo build skript při načítání keystoru / jeho properties."""
    lowered = reason.lower()
    return any(marker in lowered for marker in ('validatesigning', 'signing config', 'keystore'))


def verify_android_signing(logger, flavor, env, mode):
    """
    Spustí `validateSigning<Varianta>`. Vrátí None, když je podepisování v pořádku,
    jinak důvod selhání z výstupu Gradlu.

    Když úlohu nejde spustit (chybí gradlew, varianta nemá podepisování, jiná verze AGP),
    kontrola se jen přeskočí — build to pak ověří sám jako dřív.
    """
    gradlew_name = 'gradlew.bat' if os.name == 'nt' else 'gradlew'
    android_dir = 'android'
    if not os.path.isfile(os.path.join(android_dir, gradlew_name)):
        logger.info(f"android/{gradlew_name} nenalezen, podepisování se ověří až při buildu.")
        return None

    variant = variant_name(flavor, env, mode)
    if not variant:
        logger.info("Neznámá varianta, podepisování se ověří až při buildu.")
        return None
    task = f":app:validateSigning{variant[0].upper()}{variant[1:]}"

    gradlew = gradlew_name if os.name == 'nt' else os.path.join('.', gradlew_name)
    ret_code, output = execute_command(
        [gradlew, task, '--console=plain'], logger,
        title=f"Ověřuji podepisování ({variant})",
        working_dir=android_dir, log_stdout=False,
    )
    if ret_code == 0:
        logger.success("Podepisování je v pořádku.")
        return None

    reason = _gradle_failure_reason(output)
    if 'Cannot locate tasks' in reason or 'not found in project' in reason:
        logger.info(f"Úloha {task} neexistuje, podepisování se ověří až při buildu.")
        return None
    if not _is_signing_failure(reason):
        # Kontrola běží před `flutter pub get`, takže Gradle může spadnout i na věcech,
        # které pub get teprve připraví. Ty build nezastavují, řeší je build sám.
        logger.warn(f"Gradle se nepodařilo spustit, podepisování se ověří až při buildu:\n{reason}")
        return None
    return reason
