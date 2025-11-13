# src/logic/build_android.py
import os
import glob
import shutil
import re
import platform

from .build_common import execute_command, resolve_value

from ..constants import KEY_BUILD_TYPE, KEY_FLAVOR, KEY_ENV, KEY_BUILD_MODE, \
    KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS

def _camel_case(s):
    """Převede 'prerelease' na 'Prerelease'."""
    if not s:
        return ""
    return s[0].upper() + s[1:].lower()

def _find_package_name(logger, env_vars):
    """
    Najde packageName v env_vars.
    Původně bráno z build.gradle, nyní z adt_tools_config.env.
    """
    package_name = env_vars.get("PACKAGE_NAME")
    if not package_name:
        logger.error("CHYBA: PACKAGE_NAME nebyl nalezen v adt_tools_config.env.")
        logger.error("   -> Doplňte prosím řádek: PACKAGE_NAME=\"com.vasetvafirma.vasappka\"")
        return None
    
    logger.info(f"Nalezen packageName: {package_name}")
    return package_name

def _find_output_file(logger, candidates):
    """
    Projde seznam glob kandidátů a vrátí první nalezený soubor.
    Respektuje case-insensitivity z původního skriptu.
    """
    logger.info("Hledám výstupní soubor...")
    for pattern in candidates:
        # Použijeme glob.glob s recursive=True pro případné **
        # Python glob je case-sensitive na Linuxu, ale case-insensitive
        # na Windows/macOS (obvykle). Pro jistotu projdeme více variant.
        files = glob.glob(pattern, recursive=True)
        if files:
            logger.info(f"   -> Nalezen přes '{pattern}': {files[0]}")
            return files[0]
            
    # Fallback pro case-insensitive na Linuxu (pomalé, ale robustní)
    if platform.system() == 'Linux':
        logger.info("Hledám case-insensitive (Linux fallback)...")
        for pattern in candidates:
            pattern_lower = pattern.lower()
            # Získáme adresář a zbytek
            dirname, basename = os.path.split(pattern_lower)
            if not os.path.isdir(dirname):
                continue
            
            # Nahradíme znaky pro regex
            regex_pattern = re.compile(re.escape(basename).replace(r'\*', '.*'), re.IGNORECASE)
            
            for root, _, filenames in os.walk(dirname):
                for f in filenames:
                    if regex_pattern.match(f):
                        found_path = os.path.join(root, f)
                        logger.info(f"   -> Nalezen (case-insensitive) přes '{pattern}': {found_path}")
                        return found_path
                        
    return None

def find_and_rename_output(logger, params, env_vars):
    """
    Najde a přejmenuje výstupní soubor (APK/AAB).
    Přepsáno 1:1 z logiky Bash skriptu.
    """
    logger.header("--- Hledám a přejmenovávám výstupní soubor ---")
    
    build_type = params.get(KEY_BUILD_TYPE)
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    mode = params.get(KEY_BUILD_MODE)
    version_name = params.get("_version_name")
    build_number = params.get("_build_number")

    # 1. Najdi PackageName
    package_name = _find_package_name(logger, env_vars)
    if not package_name:
        return None # Chyba byla zalogována uvnitř

    # 2. Sestav varianty názvů (jako v .sh)
    env_camel = _camel_case(env) # např. Prerelease
    env_lc = env.lower() # např. prerelease
    combined_flavor = ""
    
    if flavor and env_camel:
        combined_flavor = f"{flavor}{env_camel}"
    elif flavor:
        combined_flavor = flavor

    # 3. Sestav seznam kandidátů
    candidates = []
    
    if build_type == "apk":
        if combined_flavor:
            candidates.extend([
                f"build/app/outputs/apk/{combined_flavor}/{mode}/app-{combined_flavor}-{mode}.apk",
                f"build/app/outputs/apk/{combined_flavor}/{mode}/app-{combined_flavor}-universal-{mode}.apk",
                f"build/app/outputs/apk/{combined_flavor}/{mode}/app-{flavor}-{env_lc}-{mode}.apk",
                f"build/app/outputs/apk/{combined_flavor}/{mode}/app-{flavor}-{env_lc}-universal-{mode}.apk",
                f"build/app/outputs/apk/{combined_flavor}/{mode}/app-{combined_flavor}-*-{mode}.apk",
                f"build/app/outputs/apk/{combined_flavor}/{mode}/app-{flavor}-{env_lc}-*-{mode}.apk",
                f"build/app/outputs/flutter-apk/app-{combined_flavor}-{mode}.apk",
                f"build/app/outputs/flutter-apk/app-{flavor}-{env_lc}-{mode}.apk"
            ])
        # Fallback bez flavoru
        candidates.extend([
            f"build/app/outputs/apk/{mode}/app-{mode}.apk",
            f"build/app/outputs/flutter-apk/app-{mode}.apk"
        ])

    elif build_type == "aab":
        mode_camel = _camel_case(mode) # např. Release
        if combined_flavor:
            candidates.extend([
                f"build/app/outputs/bundle/{combined_flavor}{mode_camel}/app-{combined_flavor}-{mode}.aab",
                f"build/app/outputs/bundle/{combined_flavor}{mode_camel}/app-{flavor}-{env_lc}-{mode}.aab",
                f"build/app/outputs/bundle/{mode}/app-{combined_flavor}-{mode}.aab",
                f"build/app/outputs/bundle/{mode}/app-{flavor}-{env_lc}-{mode}.aab"
            ])
        # Fallback bez flavoru
        candidates.extend([
            f"build/app/outputs/bundle/{mode}/app-{mode}.aab",
            f"build/app/outputs/bundle/{mode}/app-release.aab" # Častý název pro release
        ])
    
    # 4. Najdi soubor
    output_file = _find_output_file(logger, candidates)
    
    if not output_file or not os.path.exists(output_file):
        logger.error("Nepodařilo se najít výstupní soubor.")
        logger.error(f"   Hledáno pro: BUILD_TYPE={build_type}, BUILD_MODE={mode}, FLAVOR={flavor}, ENV={env}")
        logger.error("   Zkontrolujte, zda build proběhl úspěšně a zda názvy odpovídají.")
        return None

    # 5. Přejmenuj soubor
    output_dir = os.path.dirname(output_file)
    
    # Sestavení nového názvu (jako v .sh)
    file_env_suffix = f"-{env_lc}" if env_lc else ""
    
    if flavor:
        new_file_name = f"{package_name}-v{version_name}({build_number})-{flavor}{file_env_suffix}-{mode}.{build_type}"
    else:
        new_file_name = f"{package_name}-v{version_name}({build_number})-{mode}.{build_type}"
        
    new_path = os.path.join(output_dir, new_file_name)
    
    try:
        shutil.move(output_file, new_path)
        logger.success(f"Soubor přejmenován na: {new_path}")
        return output_dir # Vracíme adresář pro otevření
    except Exception as e:
        logger.error(f"Chyba při přejmenování '{output_file}' na '{new_path}': {e}")
        return None


def run_android_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Spustí úlohy specifické pro Android po úspěšném buildu.
    (Přejmenování, Nahrání symbolů)
    """
    
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    
    # 1. Přejmenování souboru
    # Tato funkce si 'build_type' bere sama z 'params'
    output_dir = find_and_rename_output(logger, params, env_vars)

    # 2. Nahrání symbolů
    if not params.get(KEY_DISABLE_OBFUSCATION, False) and params.get(KEY_UPLOAD_SYMBOLS, False):
        logger.header("--- Nahrávám symboly (Android) na Firebase ---")
        # 'flavor' a 'env' se používají zde:
        firebase_app_id = resolve_value("FIREBASE_APP_ID", flavor, env, env_vars)
        symbols_path = 'build/app/outputs/symbols'
        
        if firebase_app_id:
            # ... (zbytek logiky pro symboly) ...
            if not os.path.isdir(symbols_path):
                    logger.error(f"Adresář se symboly nenalezen: {symbols_path}. Nahrávání přeskočeno.")
            else:
                symbols_cmd = [
                    'flutterfire', 'crashlytics:symbols:upload',
                    f'--app={firebase_app_id}',
                    '--os=android',
                    f'--debug-symbols-path={symbols_path}'
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