# src/logic/build_logic.py
import os
import re

from ..constants import (
    ADT_PROJECT_CONFIG_FILENAME, PRESET_MANUAL,
    KEY_BUILD_TYPE, KEY_BUILD_MODE, KEY_FLAVOR, KEY_ENV, 
    KEY_BUMP_STRATEGY, BUMP_NONE,
    KEY_GIT_PUSH, KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, 
    KEY_INSTALL_COCOAPODS, KEY_CHECK_SQLITE_WEB
)
from .build_common import (
    execute_command, parse_env_file, resolve_dart_defines,
    get_version_from_pubspec, bump_version, perform_git_push,
    open_output_folder, revert_pubspec_version, 
    to_camel_case, get_version_parts # <-- NOVÉ IMPORTY
)
from .build_android import run_android_tasks_post_build
from .build_ios import run_ios_tasks_pre_build, run_ios_tasks_post_build
from .build_web import run_web_tasks_pre_build, run_web_tasks_post_build, restore_web_build_from_git
from .build_desktop import run_desktop_tasks_post_build


def run_flutter_build_logic(params, logger):
    """
    Hlavní orchestrátor buildu.
    """
    
    # --- Definice záchranné funkce ---
    original_version_line = None 
    build_type = params.get(KEY_BUILD_TYPE, "apk")

    def _handle_failure(message):
        """Zpracuje chybu buildu a provede rollback, pokud je třeba."""
        logger.error(f"\n❌ {message}")
        
        bump_strategy = params.get(KEY_BUMP_STRATEGY, BUMP_NONE)
        if bump_strategy != BUMP_NONE and original_version_line:
            revert_pubspec_version(logger, original_version_line)
        
        if build_type == 'web':
            restore_web_build_from_git(logger)
            
        logger.error("Build byl ukončen s chybou.")

    # --------------------------------------------------------------------------
    # 1. Příprava proměnných
    # --------------------------------------------------------------------------
    
    build_mode = params.get(KEY_BUILD_MODE, "release")
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    
    actions_performed = { "version": False, "cocoapods": False, "symbols": False, "web_check": False, "web_added": False, "desktop_added": False }

    # Načtení environment proměnných HNED, protože je potřebujeme pro iOS pre-build
    env_vars = parse_env_file(logger)

    # --- KROK 1: Spuštění flutter pub get ---
    ret_code, _ = execute_command(['flutter', 'pub', 'get'], logger, title="Spouštím flutter pub get")
    if ret_code != 0:
        logger.error("flutter pub get selhal. Build byl přerušen.")
        return

    # --- KROK 2: Načtení verze ---
    full_ver_line, version_name, build_number = get_version_from_pubspec(logger)
    if not full_ver_line:
        logger.error("Chyba: Nelze pokračovat bez platné verze v pubspec.yaml.")
        return
    
    original_version_line = full_ver_line 

    # --- KROK 3: Povýšení verze ---
    strategy = params.get(KEY_BUMP_STRATEGY, BUMP_NONE)
    if strategy != BUMP_NONE:
        new_name, new_build = bump_version(logger, strategy)
        if new_name:
            version_name = new_name
            build_number = new_build
            actions_performed["version"] = True
        else:
            logger.error("Povýšení verze selhalo. Pokračuji s původní verzí.")

    params["_version_name"] = version_name
    params["_build_number"] = build_number

    # --- KROK 4: Platform-specific úkoly PŘED buildem ---
    if build_type == 'ipa':
        # Zde se řeší CocoaPods a Plist
        success = run_ios_tasks_pre_build(logger, params, env_vars)
        if not success:
            _handle_failure("Příprava iOS selhala.")
            return
        if params.get(KEY_INSTALL_COCOAPODS, False):
            actions_performed["cocoapods"] = True
    elif build_type == 'web':
        run_web_tasks_pre_build(logger)

    # --- KROK 5: Sestavení Flutter příkazu (NOVÁ LOGIKA) ---
    
    dart_defines = resolve_dart_defines(logger, flavor, env, env_vars)
    
    build_command = ['flutter', 'build', build_type, f'--{build_mode}']

    # 5.1 Logika pro Target (-t)
    # Pokud je vybrán flavor, hledáme lib/main_flavor.dart
    target_file = "lib/main.dart" # Default
    if flavor:
        potential_target = f"lib/main_{flavor}.dart"
        if os.path.exists(potential_target):
            target_file = potential_target
            logger.info(f"Používám target: {target_file}")
        else:
            logger.warn(f"Target '{potential_target}' nenalezen, používám default 'lib/main.dart'")
    
    build_command.extend(['-t', target_file])

    # 5.2 Logika pro Flavor string (flavor + env camelcase)
    if flavor:
        env_camel = to_camel_case(env) # např. "Prerelease"
        
        # Web a desktop obvykle nepoužívají kombinované flavor názvy stejným způsobem jako Android/iOS
        # Ale pokud skript říká, že se má použít, tak ho použijeme.
        # Podle skriptu: if web or no env -> flavor, else -> flavorEnvCamel
        
        final_flavor_string = flavor
        if build_type != "web" and env:
             final_flavor_string = f"{flavor}{env_camel}"
             
        build_command.extend(['--flavor', final_flavor_string])
    
    # 5.3 Ostatní parametry
    # build_command.extend([f'--build-name={version_name}', f'--build-number={build_number}'])
    
    # 5.4 Logika pro Symboly a Obfuskaci (Dynamická cesta)
    if not params.get(KEY_DISABLE_OBFUSCATION, False):
        build_command.append('--obfuscate')
        
        # Výpočet cesty k symbolům (crashlytics/...)
        major, minor, patch = get_version_parts(version_name)
        
        symbols_flavor_part = ""
        if flavor:
            if build_type == "web" or not env:
                symbols_flavor_part = f"_{flavor}"
            else:
                symbols_flavor_part = f"_{flavor}_{env}"
        
        symbols_dir = f"crashlytics/{build_type}{symbols_flavor_part}_{major}_{minor}_{patch}"
        
        # Vytvoření složky (pro jistotu)
        if not os.path.exists(symbols_dir):
            try:
                os.makedirs(symbols_dir)
            except Exception as e:
                logger.warn(f"Nepodařilo se vytvořit složku pro symboly: {e}")

        build_command.append(f'--split-debug-info={symbols_dir}')
        logger.info(f"Symboly budou uloženy do: {symbols_dir}")
    
    build_command.extend(dart_defines)
    
    # Spuštění buildu
    ret_code, _ = execute_command(build_command, logger, f"Spouštím Flutter Build ({build_type} - {build_mode})")
    
    if ret_code != 0:
        _handle_failure(f"Build selhal s chybovým kódem: {ret_code}")
        return 

    # --- KROK 6: Platform-specific úkoly PO buildu ---
    output_dir = None
    
    try:
        if build_type in ['apk', 'appbundle']:
            output_dir = run_android_tasks_post_build(logger, params, env_vars, actions_performed)
        elif build_type == 'ipa':
            output_dir = run_ios_tasks_post_build(logger, params, env_vars, actions_performed)
        elif build_type == 'web':
            output_dir = run_web_tasks_post_build(logger, params, env_vars, actions_performed)
            if output_dir is None: # Web verifikace selhala
                 _handle_failure("Web build zamítnut nebo selhal.")
                 return
        elif build_type in ['macos', 'linux', 'windows']:
            output_dir = run_desktop_tasks_post_build(logger, params, env_vars, actions_performed)
    except Exception as e:
        _handle_failure(f"Chyba při post-build úlohách: {e}")
        return

    # --- KROK 7: Nahrání na Git ---
    if params.get(KEY_GIT_PUSH, False):
        perform_git_push(logger, params, version_name, build_number, actions_performed)
        
    # --- KROK 8: Otevření složky ---
    open_output_folder(logger, build_type, output_dir)
    
    logger.success("\n✅ Proces buildu úspěšně dokončen!")