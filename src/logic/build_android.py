# src/logic/build_android.py
import os
import glob
import shutil
import re
import platform

from .build_common import execute_command, resolve_value, get_package_name
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
        return None 

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

        # Obecný fallback
        candidates.append(f"build/app/outputs/bundle/{mode}/*.aab")
        candidates.append(f"build/app/outputs/bundle/{mode_camel}/*.aab")
    
    # Hledání
    output_file = _find_output_file(logger, candidates)
    
    if not output_file or not os.path.exists(output_file):
        logger.error("Nepodařilo se najít výstupní soubor.")
        return None

    # Přejmenování
    output_dir = os.path.dirname(output_file)
    file_env_suffix = f"-{env_lc}" if env_lc else ""
    
    # Přípona se vezme ze skutečného souboru (bude .aab nebo .apk)
    extension = output_file.split('.')[-1]
    
    if flavor:
        new_file_name = f"{package_name}-v{version_name}({build_number})-{flavor}{file_env_suffix}-{mode}.{extension}"
    else:
        new_file_name = f"{package_name}-v{version_name}({build_number})-{mode}.{extension}"
        
    new_path = os.path.join(output_dir, new_file_name)
    
    try:
        if os.path.abspath(output_file) != os.path.abspath(new_path):
            shutil.move(output_file, new_path)
            logger.success(f"Soubor přejmenován na: {new_file_name}")
        else:
            logger.info(f"Soubor již má správný název: {new_file_name}")
            
        return output_dir
    except Exception as e:
        logger.error(f"Chyba při přejmenování '{output_file}' na '{new_path}': {e}")
        return None


def run_android_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Spustí úlohy specifické pro Android po úspěšném buildu.
    """
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    
    output_dir = find_and_rename_output(logger, params, env_vars)

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