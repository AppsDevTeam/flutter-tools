# src/logic/build_common.py
import os
import subprocess
import re
import platform
import shutil
from ..constants import ADT_PROJECT_CONFIG_FILENAME

def execute_command(command, logger, title="", working_dir=None, log_stdout=True):
    """Spustí externí příkaz a loguje jeho výstup."""
    if title:
        logger.header(f"\n--- {title} ---")
    
    logger.info(f"🔧 Spouštím v '{working_dir or os.getcwd()}': {' '.join(command)}")
    
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', bufsize=1, startupinfo=startupinfo,
            cwd=working_dir
        )
        
        output_lines = []
        for line in iter(process.stdout.readline, ''):
            if log_stdout:
                logger.raw(line)
            output_lines.append(line)
            
        process.stdout.close()
        process.wait()
        return process.returncode, "".join(output_lines)
        
    except FileNotFoundError:
        logger.error(f"PŘÍKAZ NENALEZEN: Příkaz '{command[0]}' nebyl nalezen.")
        return -1, f"PŘÍKAZ NENALEZEN: {command[0]}"
    except Exception as e:
        logger.error(f"CHYBA PŘI VYKONÁNÍ: {e}")
        return -1, str(e)

def parse_env_file(logger, filepath=ADT_PROJECT_CONFIG_FILENAME):
    """
    Načte .env soubor a vrátí slovník.
    Ignoruje komentáře a prázdné řádky.
    """
    env_vars = {}
    if not os.path.exists(filepath):
        logger.warn(f"Soubor {filepath} nenalezen, nelze načíst env proměnné.")
        return env_vars
        
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                match = re.match(r'^\s*([\w.-]+)\s*=\s*(.*)\s*$', line)
                if match:
                    key, value = match.groups()
                    if (value.startswith('"') and value.endswith('"')) or \
                       (value.startswith("'") and value.endswith("'")):
                        value = value[1:-1]
                    env_vars[key] = value
    except Exception as e:
        logger.error(f"Chyba při čtení {filepath}: {e}")
    
    return env_vars

def resolve_value(base_key, flavor, env, env_vars):
    """
    Najde hodnotu s nejvyšší prioritou.
    """
    key_fe = f"{base_key}_{flavor}_{env}"
    if flavor and env and key_fe in env_vars:
        return env_vars[key_fe]
        
    key_f = f"{base_key}_{flavor}"
    if flavor and key_f in env_vars:
        return env_vars[key_f]
    
    key_e = f"{base_key}_{env}"
    if env and key_e in env_vars:
        return env_vars[key_e]
        
    if base_key in env_vars:
        return env_vars[base_key]
        
    return None

def resolve_dart_defines(logger, flavor, env, env_vars):
    """
    Sestaví seznam --dart-define na základě priorit.
    """
    logger.info("--- Zpracovávám DART DEFINES ---")
    dart_defines = []
    
    define_keys = set()
    firebase_keys = set()
    
    for key in env_vars.keys():
        if key.startswith("DART_DEFINES_"):
            parts = key.split('_', 2) 
            if len(parts) > 1:
                define_keys.add(parts[1])
        elif key.startswith("FIREBASE_APP_ID_"):
            firebase_keys.add("FIREBASE_APP_ID")

    for base_key in define_keys:
        value = resolve_value(f"DART_DEFINES_{base_key}", flavor, env, env_vars)
        if value is not None:
            logger.info(f"   -> {base_key} = {value}")
            dart_defines.append(f"--dart-define={base_key}={value}")
    
    for base_key in firebase_keys:
        value = resolve_value(base_key, flavor, env, env_vars)
        if value is not None:
            logger.info(f"   -> {base_key} = {value}")
            dart_defines.append(f"--dart-define={base_key}={value}")
            
    return dart_defines

def get_version_from_pubspec(logger, log=True):
    """Načte verzi z pubspec.yaml pomocí regexu."""
    try:
        with open('pubspec.yaml', 'r', encoding='utf-8') as f:
            content = f.read()
        
        match = re.search(r'^(version:\s*)(\d+\.\d+\.\d+)\+(\d+)', content, re.MULTILINE)
        
        if not match:
            logger.error("Verze v pubspec.yaml nemá očekávaný formát (např. 'version: 1.2.3+4').")
            return None, None, None

        full_prefix = match.group(1)   # "version: "
        version_name = match.group(2)  # "1.2.3"
        build_number = match.group(3)  # "4"
        
        if log:
            logger.info(f"ℹ️ Nalezena verze v pubspec.yaml: {version_name}+{build_number}")
            
        return f"{full_prefix}{version_name}+{build_number}", version_name, build_number
        
    except FileNotFoundError:
        if log: logger.warn("⚠️ Soubor 'pubspec.yaml' nenalezen.")
    except Exception as e:
        if log: logger.error(f"❌ Chyba při čtení pubspec.yaml: {e}")
        
    return None, None, None

def bump_version(logger):
    """Najde, povýší a zapíše novou verzi do pubspec.yaml."""
    logger.header("--- Povyšuji verzi (Build Number) ---")
    
    current_version_line, version_name, build_number = get_version_from_pubspec(logger, log=False)
    if not current_version_line:
        logger.error("Povýšení verze selhalo: nelze načíst aktuální verzi.")
        return None, None 

    try:
        new_build_number = int(build_number) + 1
        new_version_line = current_version_line.replace(f"+{build_number}", f"+{new_build_number}", 1)
        
        with open('pubspec.yaml', 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace(current_version_line, new_version_line, 1)
        
        with open('pubspec.yaml', 'w', encoding='utf-8') as f:
            f.write(content)
            
        logger.success(f"Verze povýšena z {version_name}+{build_number} na {version_name}+{new_build_number}")
        return version_name, str(new_build_number)
        
    except Exception as e:
        logger.error(f"Chyba při povyšování verze: {e}")
        return None, None

def perform_git_push(logger, params, version_name, build_number, actions_performed):
    """
    Provede git commit a push s dynamickou zprávou.
    """
    logger.header("--- Nahrávám změny na Git ---")

    ret_code, status_output = execute_command(['git', 'status', '-s'], logger, log_stdout=False)
    if ret_code != 0:
        logger.error("Chyba při kontrole stavu Gitu. Push přeskočen.")
        return

    if not any(actions_performed.values()) and not status_output.strip():
        logger.info("Nebyly nalezeny žádné změny v Gitu ani provedeny žádné akce. Commit přeskočen.")
        return

    commit_prefix = ""
    if actions_performed["version"]:
        commit_prefix = "Version"
    elif actions_performed["symbols"]:
        commit_prefix = "Symbols"
    elif actions_performed["cocoapods"]:
        commit_prefix = "Cocoapods"
    else:
        commit_prefix = "Build"
    
    commit_env = f" -{params.get('env')}" if params.get('env') else ""
    version_name_clean = version_name.split('+')[0]
    commit_message = f"{commit_prefix} {params.get('build_type')} {version_name_clean} ({build_number}){commit_env}"
    
    logger.info(f"Commituji: {commit_message}")
    execute_command(['git', 'add', '.'], logger)
    ret_code, _ = execute_command(['git', 'commit', '-m', commit_message], logger)
    
    if ret_code == 0:
        logger.info("Provádím git push...")
        ret_code, _ = execute_command(['git', 'push'], logger)
        if ret_code == 0:
            logger.success("Git push úspěšný.")
        else:
            logger.error("Git push selhal.")
    else:
        logger.warn("Git commit selhal (možná nebyly žádné změny k commitu).")

def open_output_folder(logger, build_type, output_dir=None):
    """Otevře složku s výstupem v průzkumníku."""
    path_to_open = output_dir
    os_name = platform.system()
    
    if not path_to_open:
        if build_type == 'apk': path_to_open = 'build/app/outputs/flutter-apk'
        elif build_type == 'appbundle': path_to_open = 'build/app/outputs/bundle'
        elif build_type == 'ipa': path_to_open = 'build/ios/archive'
        elif build_type == 'web': path_to_open = 'build/web'
    
    if not os.path.isdir(path_to_open):
        logger.error(f"Adresář pro otevření neexistuje: {path_to_open}")
        return

    logger.info(f"Otevírám složku: {path_to_open}")
    try:
        if os_name == 'Darwin':
            if build_type == 'ipa' and os.path.exists(os.path.join(path_to_open, 'Runner.xcarchive')):
                 archive_path = os.path.join(path_to_open, 'Runner.xcarchive')
                 logger.info("Nalezen .xcarchive, otevírám v Xcode Organizer...")
                 execute_command(['open', archive_path], logger)
            else:
                execute_command(['open', path_to_open], logger)
        elif os_name == 'Windows':
            os.startfile(os.path.abspath(path_to_open))
        elif os_name == 'Linux':
            execute_command(['xdg-open', path_to_open], logger)
    except Exception as e:
        logger.error(f"Nepodařilo se otevřít složku: {e}")