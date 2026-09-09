# src/logic/build_android.py
import os
import glob
import shutil
import re
import platform

from .build_common import execute_command, resolve_value, get_package_name
from .android_snapshot_check import verify_dart_snapshots, normalized_name
from ..constants import KEY_BUILD_TYPE, KEY_FLAVOR, KEY_ENV, KEY_BUILD_MODE, \
    KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS

def _camel_case(s):
    """Převede 'release' na 'Release', 'prod' na 'Prod'."""
    if not s: return ""
    return s[0].upper() + s[1:].lower()

def _find_output_file(logger, candidates):
    """
    Projde seznam glob kandidátů a vrátí první nalezený soubor.
    """
    logger.info("Hledám výstupní soubor v těchto cestách:")
    for c in candidates:
        logger.info(f"   ? {c}") # Výpis pro kontrolu

    for pattern in candidates:
        files = glob.glob(pattern, recursive=True)
        if files:
            files.sort(key=os.path.getmtime, reverse=True)
            found_file = files[0]
            logger.info(f"   -> Nalezen přes '{pattern}': {found_file}")
            return found_file
            
    # Fallback pro Linux
    if platform.system() == 'Linux':
        logger.info("Hledám case-insensitive (Linux fallback)...")
        for pattern in candidates:
            pattern_lower = pattern.lower()
            dirname, basename = os.path.split(pattern_lower)
            if not os.path.isdir(dirname): continue
            
            regex_pattern = re.compile(re.escape(basename).replace(r'\*', '.*'), re.IGNORECASE)
            
            for root, _, filenames in os.walk(dirname):
                for f in filenames:
                    if regex_pattern.match(f):
                         found_file = os.path.join(root, f)
                         logger.info(f"   -> Nalezen (case-insensitive): {found_file}")
                         return found_file
                        
    return None

OUTPUTS_DIR = os.path.join("build", "app", "outputs")

# Široké vzory, které se použijí jen tehdy, když se varianta nedá poskládat (chybí mode).
# Bez nich by v takovém případě ochrana proti strip-checku zmizela úplně.
FALLBACK_ARTIFACT_GLOBS = {
    "appbundle": [os.path.join(OUTPUTS_DIR, "bundle", "**", "*.aab")],
    "aab": [os.path.join(OUTPUTS_DIR, "bundle", "**", "*.aab")],
    "apk": [
        os.path.join(OUTPUTS_DIR, "apk", "**", "*.apk"),
        os.path.join(OUTPUTS_DIR, "flutter-apk", "*.apk"),
    ],
}


def _matching_dirs(parent, name):
    """
    Podadresáře `parent`, jejichž jméno odpovídá `name` bez ohledu na zápis.

    AGP jméno varianty občas zapíše jinak, než ho složíme (`tapygoprodRelease`
    vs. `tapygoProdRelease`), a na case-insensitive filesystému se to chová ještě jinak
    než na Linuxu. Porovnání po normalizaci je proti obojímu imunní.
    """
    if not name or not os.path.isdir(parent):
        return []

    target = normalized_name(name)

    return [
        d for d in sorted(glob.glob(os.path.join(parent, "*")))
        if os.path.isdir(d) and normalized_name(os.path.basename(d)) == target
    ]


def _stale_artifact_globs(build_type, flavor, env, mode):
    """
    Vrátí glob vzory pro artefakty PŘEDCHOZÍCH buildů téže varianty.

    Maže se výhradně to, co by se s výstupem tohohle buildu dalo zaměnit — tedy adresář
    aktuální varianty. Artefakty jiných flavorů jsou platný výstup, na který se nesahá:
    `findBundleFile` matchuje podle jména nadřazeného adresáře (`<flavor><mode>`), takže
    na cizí variantu nikdy nesáhne, a `_find_output_file` řadí kandidáty podle mtime.
    Výjimkou je plochý `flutter-apk/`, společný pro všechny varianty — tam se filtruje
    podle jména souboru.
    """
    mode_lc = (mode or "").lower()

    if not mode_lc:
        return FALLBACK_ARTIFACT_GLOBS.get(build_type, [])

    combined = f"{flavor}{_camel_case(env)}" if flavor else ""

    if build_type in ("appbundle", "aab"):
        variant = f"{combined}{_camel_case(mode_lc)}" if combined else mode_lc

        return [
            os.path.join(d, "*.aab")
            for d in _matching_dirs(os.path.join(OUTPUTS_DIR, "bundle"), variant)
        ]

    if build_type == "apk":
        patterns = []
        apk_dir = os.path.join(OUTPUTS_DIR, "apk")

        # AGP v3+ vkládá flavor do cesty, bez flavoru je tam jen build type.
        for flavor_dir in _matching_dirs(apk_dir, combined) or [apk_dir]:
            patterns += [
                os.path.join(d, "*.apk") for d in _matching_dirs(flavor_dir, mode_lc)
            ]

        # Flutter kopíruje do flutter-apk/ jako `app-<flavor>-<mode>.apk` (listApkPaths),
        # adt to přejmenuje na `<package>-v…-<flavor>-<env>-<mode>.apk`. Oba vzory mají
        # flavor uvnitř jména a končí modem, proto se matchuje na příponu.
        suffix = f"*{flavor.lower()}*-{mode_lc}.apk" if flavor else f"*-{mode_lc}.apk"
        patterns.append(os.path.join(OUTPUTS_DIR, "flutter-apk", suffix))

        return patterns

    return []


def purge_stale_artifacts(logger, build_type, flavor=None, env=None, mode=None):
    """
    Smaže artefakty předchozích buildů TÉŽE varianty, aby v output adresáři zůstal
    po buildu jen ten právě vyrobený. Výstupy ostatních flavorů zůstávají.

    Důvod, proč to nestačí nechat na Flutteru: Flutter 3.44+ u release appbundle ověřuje,
    že AGP odstripoval debug symboly, a AAB si k tomu najde přes `findBundleFile`
    (gradle.dart) — ta prochází výpis adresáře a vezme první *release.aab, bez ohledu na
    čas vzniku. Na přejmenovaném artefaktu ze staršího toolchainu, který v BUNDLE-METADATA
    nemá libapp.so.sym, build skončí na "Release app bundle failed to strip debug symbols",
    přesto že právě vyrobený AAB je v pořádku. U APK Flutter tenhle problém nemá,
    `findApkFilesModule` sahá na přesné jméno souboru; tam jde jen o to, aby v adresáři
    nezůstávala hromada starých buildů.

    Volá se před spuštěním Flutter buildu. Neúspěšné mazání se jen zaloguje,
    build kvůli němu padat nemá.
    """
    removed = []

    for pattern in _stale_artifact_globs(build_type, flavor, env, mode):
        for path in sorted(glob.glob(pattern, recursive=True)):
            if not os.path.isfile(path):
                continue

            try:
                os.remove(path)
                removed.append(path)
            except Exception as e:
                logger.warn(f"Nepodařilo se smazat '{path}': {e}")

    if removed:
        logger.header("--- Čistím artefakty z předchozích buildů ---")

        for path in removed:
            logger.info(f"   ✓ smazáno: {path}")
    else:
        logger.info("Žádné artefakty z předchozích buildů, není co mazat.")


def find_and_rename_output(logger, params, env_vars):
    logger.header("--- Hledám a přejmenovávám výstupní soubor ---")
    
    build_type = params.get(KEY_BUILD_TYPE)
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    mode = params.get(KEY_BUILD_MODE)
    version_name = params.get("_version_name")
    build_number = params.get("_build_number")

    package_name = get_package_name(logger, env_vars)
    if not package_name:
        return None, None

    env_camel = _camel_case(env) 
    env_lc = env.lower() if env else ""
    
    combined_flavor = ""
    if flavor and env_camel:
        combined_flavor = f"{flavor}{env_camel}"
    elif flavor:
        combined_flavor = flavor

    candidates = []
    
    # --- APK ---
    if build_type == "apk":
        if combined_flavor:
            candidates.append(f"build/app/outputs/apk/{combined_flavor}/{mode}/*.apk")
            candidates.append(f"build/app/outputs/apk/{combined_flavor}/{mode}/app-*.apk")
        
        candidates.append(f"build/app/outputs/apk/{mode}/*.apk")
        candidates.append(f"build/app/outputs/flutter-apk/*.apk")

    # --- AAB (App Bundle) ---
    # ZMĚNA: Kontrolujeme 'aab' I 'appbundle' (UI posílá 'appbundle')
    elif build_type in ["aab", "appbundle"]:
        mode_camel = _camel_case(mode) 
        
        if combined_flavor:
            # Cesta: build/app/outputs/bundle/tapygoProdRelease/*.aab
            candidates.append(f"build/app/outputs/bundle/{combined_flavor}{mode_camel}/*.aab")
            candidates.append(f"build/app/outputs/bundle/{combined_flavor}/*.aab")
            candidates.append(f"build/app/outputs/bundle/{combined_flavor.lower()}{mode_camel}/*.aab")

        # Obecný fallback
        candidates.append(f"build/app/outputs/bundle/{mode}/*.aab")
        candidates.append(f"build/app/outputs/bundle/{mode_camel}/*.aab")
        candidates.append("build/app/outputs/bundle/**/*.aab")
    
    # Hledání
    logger.info(f"Hledám kandidáty: {candidates}")
    output_file = _find_output_file(logger, candidates)
    
    if not output_file or not os.path.exists(output_file):
        logger.error("Nepodařilo se najít výstupní soubor.")
        return None, None

    # Přejmenování
    output_dir = os.path.dirname(output_file)
    flavor_part = f"-{flavor}" if flavor else ""
    file_env_suffix = f"-{env_lc}" if env_lc else ""

    # Přípona se vezme ze skutečného souboru (bude .aab nebo .apk)
    extension = output_file.split('.')[-1]

    new_file_name = f"{package_name}-v{version_name}({build_number}){flavor_part}{file_env_suffix}-{mode}.{extension}"
        
    new_path = os.path.join(output_dir, new_file_name)
    
    try:
        if os.path.abspath(output_file) != os.path.abspath(new_path):
            shutil.move(output_file, new_path)
            logger.success(f"Soubor přejmenován na: {new_file_name}")
        else:
            logger.info(f"Soubor již má správný název: {new_file_name}")

        return output_dir, new_path
    except Exception as e:
        logger.error(f"Chyba při přejmenování '{output_file}' na '{new_path}': {e}")
        return None, None


def run_android_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Spustí úlohy specifické pro Android po úspěšném buildu.

    Vyhazuje RuntimeError, pokud artefakt neobsahuje Dart snapshot z tohohle buildu —
    takový artefakt se nesmí dostat ven ani se pro něj nemají nahrávat symboly.
    """
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    mode = params.get(KEY_BUILD_MODE)

    output_dir, artifact_path = find_and_rename_output(logger, params, env_vars)

    if artifact_path and not verify_dart_snapshots(logger, artifact_path, flavor, env, mode):
        raise RuntimeError("Artefakt neobsahuje Dart kód z tohoto buildu.")

    if not params.get(KEY_DISABLE_OBFUSCATION, False) and params.get(KEY_UPLOAD_SYMBOLS, False):
        logger.header("--- Nahrávám symboly (Android) na Firebase ---")
        firebase_app_id = resolve_value("FIREBASE_APP_ID", flavor, env, env_vars)
        
        symbols_path = params.get("_symbols_dir", "") 
        
        if firebase_app_id:
            if not symbols_path or not os.path.isdir(symbols_path):
                    logger.error(f"Adresář se symboly nenalezen: '{symbols_path}'. Nahrávání přeskočeno.")
            else:
                logger.info(f"Používám App ID: {firebase_app_id}")
                symbols_cmd = [
                    'firebase', 'crashlytics:symbols:upload',
                    f'--app={firebase_app_id}',
                    symbols_path
                ]
                
                ret_code, _ = execute_command(symbols_cmd, logger)
                if ret_code == 0:
                    logger.success("Symboly úspěšně nahrány.")
                    actions_performed["symbols"] = True
                else:
                    logger.error("Nahrání symbolů selhalo.")
        else:
            logger.warn("FIREBASE_APP_ID nenalezen v adt_tools_config.env. Nelze nahrát symboly.")
            
    return output_dir