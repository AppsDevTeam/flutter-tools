# src/logic/build_logic.py
import os
import re

from ..constants import (
    KEY_BUILD_TYPE, KEY_BUILD_MODE, KEY_FLAVOR, KEY_ENV, 
    KEY_BUMP_STRATEGY, BUMP_NONE, KEY_GIT_PUSH, KEY_DISABLE_OBFUSCATION, 
    KEY_INSTALL_COCOAPODS
)
# --- NOVÉ IMPORTY ---
from .build_common import (
    execute_command, parse_env_file, resolve_dart_defines,
    get_version_from_pubspec, bump_version, perform_git_push,
    open_output_folder
)
from .build_android import run_android_tasks_post_build
from .build_ios import run_ios_tasks_pre_build, run_ios_tasks_post_build
from .build_web import run_web_tasks_post_build
# --- KONEC NOVÝCH IMPORTŮ ---


def run_flutter_build_logic(params, logger):
    """
    Hlavní orchestrátor buildu.
    Načte parametry z UI a zavolá platform-specific logiku.
    """
    
    # --------------------------------------------------------------------------
    # 1. Hlavní logika buildu
    # --------------------------------------------------------------------------
    
    # Načtení parametrů z UI
    build_type = params.get(KEY_BUILD_TYPE, "apk")
    build_mode = params.get(KEY_BUILD_MODE, "release")
    flavor = params.get(KEY_FLAVOR)
    
    # Sledování provedených akcí pro commit message
    actions_performed = {
        "version": False,
        "cocoapods": False,
        "symbols": False,
        "web_check": False
    }

    # --- KROK 1: Spuštění flutter pub get ---
    ret_code, _ = execute_command(['flutter', 'pub', 'get'], logger, title="Spouštím flutter pub get")
    if ret_code != 0:
        logger.error("flutter pub get selhal. Build byl přerušen.")
        return

    # --- KROK 2: Načtení verze ---
    _, version_name, build_number = get_version_from_pubspec(logger)
    if not version_name:
        logger.error("Chyba: Nelze pokračovat bez platné verze v pubspec.yaml.")
        return

    # --- KROK 3: Povýšení verze ---
    strategy = params.get(KEY_BUMP_STRATEGY, BUMP_NONE)
    if strategy != BUMP_NONE:
        # Voláme novou funkci s parametrem strategie
        new_name, new_build = bump_version(logger, strategy)
        if new_name:
            version_name = new_name
            build_number = new_build
            actions_performed["version"] = True
        else:
            logger.error("Povýšení verze selhalo. Pokračuji s původní verzí.")
    else:
        logger.info("Povýšení verze přeskočeno (dle nastavení).")

    params["_version_name"] = version_name
    params["_build_number"] = build_number

    # --- KROK 4: Platform-specific úkoly PŘED buildem ---
    if build_type == 'ipa':
        success = run_ios_tasks_pre_build(logger, params)
        if not success:
            return # Build přerušen
        if params.get(KEY_INSTALL_COCOAPODS, False):
            actions_performed["cocoapods"] = True

    # --- KROK 5: Sestavení Flutter příkazu ---
    
    env_vars = parse_env_file(logger)
    dart_defines = resolve_dart_defines(logger, flavor, params.get(KEY_ENV), env_vars)
    
    build_command = ['flutter', 'build', build_type, f'--{build_mode}']

    if flavor:
        build_command.extend(['--flavor', flavor])
    
    build_command.extend([f'--build-name={version_name}', f'--build-number={build_number}'])
    
    if not params.get(KEY_DISABLE_OBFUSCATION, False):
        build_command.append('--obfuscate')
        build_command.append('--split-debug-info=build/app/outputs/symbols')
    
    build_command.extend(dart_defines)
    
    # Spuštění buildu
    ret_code, _ = execute_command(build_command, logger, f"Spouštím Flutter Build ({build_type} - {build_mode})")
    
    if ret_code != 0:
        logger.error(f"Build selhal s chybovým kódem: {ret_code}")
        return # Ukončíme

    # --- KROK 6: Platform-specific úkoly PO buildu ---
    
    output_dir = None
    if build_type in ['apk', 'appbundle']:
        output_dir = run_android_tasks_post_build(logger, params, env_vars, actions_performed)
    elif build_type == 'ipa':
        output_dir = run_ios_tasks_post_build(logger, params, env_vars, actions_performed)
    elif build_type == 'web':
        output_dir = run_web_tasks_post_build(logger, params, env_vars, actions_performed)

    # --- KROK 7: Nahrání na Git ---
    # Předáme parametry, verzi a slovník provedených akcí
    if params.get(KEY_GIT_PUSH, False):
        perform_git_push(logger, params, version_name, build_number, actions_performed)
        
    # --- KROK 8: Otevření složky ---
    open_output_folder(logger, build_type, output_dir)
    
    logger.success("\n✅ Proces buildu úspěšně dokončen!")