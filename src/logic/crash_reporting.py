# src/logic/crash_reporting.py
"""
Hlášení pádů a nahrávání symbolů podle služby projektu (CRASH_REPORTING v adt_tools_config.env):

- firebase (výchozí, chování jako dřív): GoogleService-Info.plist, Crashlytics, Firebase CLI.
- glitchtip: symboly a source mapy přes sentry-cli (GlitchTip je kompatibilní se Sentry API).
- none: žádná služba; nic se nenahrává a iOS build nevyžaduje GoogleService-Info.plist.

GlitchTip se nastavuje klíči GLITCHTIP_URL, GLITCHTIP_ORG a GLITCHTIP_PROJECT (i s příponou
_<flavor>_<env> jako ostatní klíče). Token je osobní a do repozitáře
nepatří: zadává se v UI (lokální config.json nástroje), záložně z proměnné prostředí
SENTRY_AUTH_TOKEN (nebo GLITCHTIP_AUTH_TOKEN), případně z ~/.sentryclirc vývojáře.
"""
import glob
import os

from ..constants import KEY_FLAVOR, KEY_ENV
from .build_common import execute_command, resolve_value

PROVIDER_FIREBASE = "firebase"
PROVIDER_GLITCHTIP = "glitchtip"
PROVIDER_NONE = "none"
PROVIDERS = (PROVIDER_FIREBASE, PROVIDER_GLITCHTIP, PROVIDER_NONE)

# Dart define s názvem vydání: aplikace ho předá Sentry SDK (SentryFlutter.init, options.release),
# aby chyby a nahrané symboly měly stejné vydání. Výchozí release SDK na webu nesedí
# (package_info tam vrací název Dart balíčku, ne package name aplikace).
RELEASE_DART_DEFINE = "SENTRY_RELEASE"

# Parametr buildu s tokenem z UI; do presetu se neukládá.
PARAM_GLITCHTIP_TOKEN = "_glitchtip_token"

_GLITCHTIP_KEYS = ("GLITCHTIP_URL", "GLITCHTIP_ORG", "GLITCHTIP_PROJECT")


def read_provider(flavor, env, env_vars):
    """(služba, neznámá hodnota nebo None); neznámá hodnota znamená výchozí firebase."""
    value = (resolve_value("CRASH_REPORTING", flavor, env, env_vars) or PROVIDER_FIREBASE).strip().lower()
    if value not in PROVIDERS:
        return PROVIDER_FIREBASE, value
    return value, None


def get_provider(logger, flavor, env, env_vars):
    """Služba pro hlášení pádů; neznámá hodnota se hlásí a bere se výchozí firebase."""
    provider, unknown = read_provider(flavor, env, env_vars)
    if unknown:
        logger.warn(
            f"Neznámá hodnota CRASH_REPORTING='{unknown}' (povolené: {', '.join(PROVIDERS)}). Používám firebase."
        )
    return provider


def read_glitchtip_config(flavor, env, env_vars):
    """({klíč: hodnota}, [chybějící klíče]) pro GLITCHTIP_URL / _ORG / _PROJECT."""
    values = {key: (resolve_value(key, flavor, env, env_vars) or "").strip() for key in _GLITCHTIP_KEYS}
    return values, [key for key in _GLITCHTIP_KEYS if not values[key]]


def release_name(package_name, version_name, build_number):
    """Název vydání: cz.firma.aplikace@1.2.3+45 (stejný tvar jako výchozí v Sentry SDK)."""
    version = version_name.split('+')[0]
    return f"{package_name}@{version}+{build_number}"


def release_dart_define(package_name, version_name, build_number):
    return f"--dart-define={RELEASE_DART_DEFINE}={release_name(package_name, version_name, build_number)}"


class GlitchTipSettings:
    """Připojení k GlitchTipu pro sentry-cli. Token jde do proměnných prostředí, ne do příkazu."""

    def __init__(self, url, org, project, token):
        self.url = url
        self.org = org
        self.project = project
        self.token = token

    @classmethod
    def resolve(cls, logger, params, env_vars):
        values, missing = read_glitchtip_config(params.get(KEY_FLAVOR), params.get(KEY_ENV), env_vars)
        if missing:
            logger.error(f"Pro GlitchTip chybí v adt_tools_config.env: {', '.join(missing)}. Nahrávání přeskočeno.")
            return None

        token = ((params.get(PARAM_GLITCHTIP_TOKEN) or "").strip()
                 or os.environ.get("SENTRY_AUTH_TOKEN") or os.environ.get("GLITCHTIP_AUTH_TOKEN"))
        if not token:
            logger.warn("GlitchTip token není vyplněný v ADT tools ani v SENTRY_AUTH_TOKEN; sentry-cli zkusí ~/.sentryclirc.")
        return cls(values["GLITCHTIP_URL"].rstrip('/'), values["GLITCHTIP_ORG"], values["GLITCHTIP_PROJECT"], token)

    def env(self):
        values = {"SENTRY_URL": self.url, "SENTRY_ORG": self.org, "SENTRY_PROJECT": self.project}
        if self.token:
            values["SENTRY_AUTH_TOKEN"] = self.token
        return values


def _sentry_cli(logger, settings, args, title=None):
    ret_code, _ = execute_command(['sentry-cli', *args], logger, title=title or "", extra_env=settings.env())
    return ret_code == 0


def upload_debug_files(logger, settings, paths, label):
    """
    Nahraje ladicí soubory (Dart symboly z --split-debug-info, dSYM) do GlitchTipu. Vrátí True,
    když se nahrálo vše, co existovalo.
    """
    existing = [path for path in paths if path and os.path.exists(path)]
    if not existing:
        logger.warn(f"{label}: nic k nahrání (cesty neexistují: {paths}).")
        return False

    ok = True
    for path in existing:
        logger.info(f"{label}: nahrávám {path}...")
        if not _sentry_cli(logger, settings, ['debug-files', 'upload', path]):
            logger.error(f"{label}: nahrání {path} selhalo.")
            ok = False
    if ok:
        logger.success(f"{label}: nahráno do GlitchTipu.")
    return ok


def upload_proguard_mapping(logger, settings):
    """
    Mapa R8/ProGuard (Kotlin/Java část Androidu), pokud ji build vytvořil (minifyEnabled).
    Bez ní je jen Dart část čitelná; chybějící mapa není chyba.
    """
    mappings = glob.glob(os.path.join('build', 'app', 'outputs', 'mapping', '**', 'mapping.txt'), recursive=True)
    if not mappings:
        logger.info("Mapa R8 (mapping.txt) nenalezena — Android build není minifikovaný, přeskočeno.")
        return True

    newest = max(mappings, key=os.path.getmtime)
    logger.info(f"Nahrávám mapu R8: {newest}")
    if _sentry_cli(logger, settings, ['upload-proguard', newest]):
        logger.success("Mapa R8 nahrána.")
        return True
    logger.error("Nahrání mapy R8 selhalo.")
    return False


def upload_web_source_maps(logger, settings, release, web_dir):
    """
    Source mapy webu (flutter build web --source-maps) k vydání [release]. Cesty v mapách se
    párují s URL přes prefix '~/' (libovolná doména), web tedy může běžet na kterékoli adrese.
    """
    logger.info(f"Nahrávám source mapy z '{web_dir}' k vydání {release}...")
    ok = (
        _sentry_cli(logger, settings, ['releases', 'new', release])
        and _sentry_cli(logger, settings, ['releases', 'files', release, 'upload-sourcemaps', web_dir,
                                           '--url-prefix', '~/', '--ext', 'js', '--ext', 'map'])
        and _sentry_cli(logger, settings, ['releases', 'finalize', release])
    )
    if ok:
        logger.success("Source mapy nahrány do GlitchTipu.")
    else:
        logger.error("Nahrání source map selhalo.")
    return ok


def remove_web_source_maps(logger, web_dir):
    """
    Smaže .map soubory z výstupu webu: na veřejném serveru by z nich šel přečíst zdrojový kód.
    Volá se vždy, když se mapy generovaly, i když nahrání selhalo.
    """
    removed = 0
    for path in glob.glob(os.path.join(web_dir, '**', '*.map'), recursive=True):
        try:
            os.remove(path)
            removed += 1
        except OSError as e:
            logger.warn(f"Nepodařilo se smazat {path}: {e}")
    if removed:
        logger.info(f"Z '{web_dir}' smazáno {removed} souborů .map (nebudou na serveru).")
