# src/logic/build_common.py
import os
import subprocess
import re
import platform
import time
import glob

from ..constants import ADT_PROJECT_CONFIG_FILENAME

def to_camel_case(s):
    """Převede string (např. 'prerelease') na CamelCase ('Prerelease')."""
    if not s: return ""
    return s[0].upper() + s[1:].lower()

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
    """Načte .env soubor a vrátí slovník."""
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
    key_fe = f"{base_key}_{flavor}_{env}"
    if flavor and env and key_fe in env_vars: return env_vars[key_fe]
    key_f = f"{base_key}_{flavor}"
    if flavor and key_f in env_vars: return env_vars[key_f]
    key_e = f"{base_key}_{env}"
    if env and key_e in env_vars: return env_vars[key_e]
    if base_key in env_vars: return env_vars[base_key]
    return None

def resolve_dart_defines(logger, flavor, env, env_vars):
    logger.info("--- Zpracovávám DART DEFINES ---")
    dart_defines = []
    define_keys = set()
    firebase_keys = set()
    for key in env_vars.keys():
        if key.startswith("DART_DEFINES_"):
            rest = key[len("DART_DEFINES_"):]
            base_name = rest
            if flavor and env and rest.endswith(f"_{flavor}_{env}"):
                base_name = rest[:-len(f"_{flavor}_{env}")]
            elif flavor and rest.endswith(f"_{flavor}"):
                base_name = rest[:-len(f"_{flavor}")]
            elif env and rest.endswith(f"_{env}"):
                base_name = rest[:-len(f"_{env}")]
            define_keys.add(base_name)
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
    try:
        with open('pubspec.yaml', 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(r'^(version:\s*)(\d+\.\d+\.\d+)\+(\d+)', content, re.MULTILINE)
        if not match:
            if log: logger.error("Verze v pubspec.yaml nemá očekávaný formát.")
            return None, None, None
        full_prefix = match.group(1)
        version_name = match.group(2)
        build_number = match.group(3)
        if log: logger.info(f"ℹ️ Nalezena verze v pubspec.yaml: {version_name}+{build_number}")
        return f"{full_prefix}{version_name}+{build_number}", version_name, build_number
    except FileNotFoundError:
        if log: logger.warn("⚠️ Soubor 'pubspec.yaml' nenalezen.")
    except Exception as e:
        if log: logger.error(f"❌ Chyba při čtení pubspec.yaml: {e}")
    return None, None, None

def get_version_parts(version_name):
    """Rozdělí verzi (1.2.3) na major, minor, patch."""
    try:
        parts = version_name.split('.')
        return parts[0], parts[1], parts[2]
    except:
        return "0", "0", "0"

def calculate_bump(version_name_str, build_number_str, strategy):
    from ..constants import BUMP_MAJOR, BUMP_MINOR, BUMP_PATCH, BUMP_BUILD, BUMP_NONE
    try:
        major, minor, patch = [int(p) for p in version_name_str.split('.')]
        new_build_number = int(build_number_str) + 1

        if strategy == BUMP_MAJOR:
            major += 1; minor = 0; patch = 0
        elif strategy == BUMP_MINOR:
            minor += 1; patch = 0
        elif strategy == BUMP_PATCH:
            patch += 1
        elif strategy == BUMP_BUILD:
            pass
        elif strategy == BUMP_NONE:
            return version_name_str, build_number_str

        # Kaskádové překlopení (99 -> 0 a +1 výše)
        if patch >= 100:
            patch = 0
            minor += 1
        if minor >= 100:
            minor = 0
            major += 1

        new_version_name = f"{major}.{minor}.{patch}"
        return new_version_name, str(new_build_number)
    except Exception:
        return version_name_str, build_number_str

def bump_version(logger, strategy):
    logger.header(f"--- Povyšuji verzi (Strategie: {strategy}) ---")
    current_version_line, version_name, build_number = get_version_from_pubspec(logger, log=False)
    if not current_version_line:
        logger.error("Povýšení verze selhalo: nelze načíst aktuální verzi.")
        return None, None 

    try:
        new_version_name, new_build_number = calculate_bump(version_name, build_number, strategy)
        
        if (version_name, build_number) == (new_version_name, new_build_number):
            logger.info("Strategie 'Nepovyšovat', verze zůstává stejná.")
            return version_name, build_number

        prefix = current_version_line.split(version_name)[0]
        new_version_line = f"{prefix}{new_version_name}+{new_build_number}"
        
        with open('pubspec.yaml', 'r', encoding='utf-8') as f: content = f.read()
        content = content.replace(current_version_line, new_version_line, 1)
        with open('pubspec.yaml', 'w', encoding='utf-8') as f: f.write(content)
            
        logger.success(f"Verze povýšena z {version_name}+{build_number} na {new_version_name}+{new_build_number}")
        return new_version_name, new_build_number
    except Exception as e:
        logger.error(f"Chyba při povyšování verze: {e}")
        return None, None
    
def revert_pubspec_version(logger, original_version_line):
    """Vrátí pubspec.yaml na původní verzi v případě chyby."""
    logger.warn(f"Vracím původní verzi do pubspec.yaml: {original_version_line.strip()}")
    try:
        # Přečteme aktuální (povýšenou) verzi, abychom ji mohli najít a nahradit
        current_version_line, _, _ = get_version_from_pubspec(logger, log=False)
        if not current_version_line:
            logger.error("Rollback selhal: nelze najít aktuální řádek verze.")
            return

        with open('pubspec.yaml', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Nahradíme aktuální (špatnou) verzi původní (dobrou) verzí
        content = content.replace(current_version_line, original_version_line, 1)
        
        with open('pubspec.yaml', 'w', encoding='utf-8') as f:
            f.write(content)
            
        logger.success("Pubspec.yaml byl úspěšně vrácen do původního stavu.")
        
    except Exception as e:
        logger.error(f"Kritická chyba při rollbacku verze: {e}")

def perform_git_push(logger, params, version_name, build_number, actions_performed):
    logger.header("--- Nahrávám změny na Git ---")
    ret_code, status_output = execute_command(['git', 'status', '-s'], logger, log_stdout=False)
    if ret_code != 0:
        logger.error("Chyba při kontrole stavu Gitu. Push přeskočen.")
        return
    if not any(actions_performed.values()) and not status_output.strip():
        logger.info("Nebyly nalezeny žádné změny v Gitu ani provedeny žádné akce. Commit přeskočen.")
        return
    
    commit_prefix = ""
    if actions_performed["version"]: commit_prefix = "Version"
    elif actions_performed.get("web_added"): commit_prefix = "Web Build" 
    elif actions_performed.get("desktop_added"): commit_prefix = "Desktop Build"
    elif actions_performed["symbols"]: commit_prefix = "Symbols"
    elif actions_performed["cocoapods"]: commit_prefix = "Cocoapods"
    else: commit_prefix = "Build"

    commit_env = f" -{params.get('env')}" if params.get('env') else ""
    version_name_clean = version_name.split('+')[0]
    commit_message = f"{commit_prefix} {params.get('build_type')} {version_name_clean} ({build_number}){commit_env}"
    
    logger.info(f"Commituji: {commit_message}")
    execute_command(['git', 'add', '.'], logger)
    ret_code, _ = execute_command(['git', 'commit', '-m', commit_message], logger)
    
    if ret_code == 0:
        logger.info("Provádím git push...")
        ret_code, _ = execute_command(['git', 'push'], logger)
        if ret_code == 0: logger.success("Git push úspěšný.")
        else: logger.error("Git push selhal.")
    else:
        logger.warn("Git commit selhal (možná nebyly žádné změny k commitu).")

# --- NOVÁ FUNKCE (přesunuta z android a zobecněna) ---
def get_package_name(logger, env_vars):
    """Najde packageName v env_vars (z adt_tools_config.env)."""
    package_name = env_vars.get("PACKAGE_NAME")
    if not package_name:
        logger.error("CHYBA: PACKAGE_NAME nebyl nalezen v adt_tools_config.env.")
        logger.error("   -> Doplňte prosím řádek: PACKAGE_NAME=\"com.vasetvafirma.vasappka\"")
        return None
    logger.info(f"Nalezen packageName: {package_name}")
    return package_name

def open_output_folder(logger, build_type, output_dir=None):
    """Otevře složku s výstupem v průzkumníku."""
    path_to_open = output_dir
    os_name = platform.system()
    
    if not path_to_open:
        # Výchozí cesty
        if build_type == 'apk': path_to_open = 'build/app/outputs/flutter-apk'
        elif build_type == 'appbundle': path_to_open = 'build/app/outputs/bundle'
        elif build_type == 'ipa': path_to_open = 'build/ios/archive'
        elif build_type == 'web': path_to_open = 'build/web'
        elif build_type == 'windows': path_to_open = 'build/windows'
        elif build_type == 'linux': path_to_open = 'build/linux' 
        elif build_type == 'macos': path_to_open = 'build/macos/Build/Products'
    
    if not os.path.isdir(path_to_open):
        logger.error(f"Adresář pro otevření neexistuje: {path_to_open}")
        return

    logger.info(f"Otevírám složku: {path_to_open}")
    try:
        if os_name == 'Darwin':
            if build_type == 'ipa' and os.path.exists(os.path.join(path_to_open, 'Runner.xcarchive')):
                 archive_path = os.path.join(path_to_open, 'Runner.xcarchive')
                 execute_command(['open', archive_path], logger)
            else:
                execute_command(['open', path_to_open], logger)
        elif os_name == 'Windows':
            os.startfile(os.path.abspath(path_to_open))
        elif os_name == 'Linux':
            execute_command(['xdg-open', path_to_open], logger)
    except Exception as e:
        logger.error(f"Nepodařilo se otevřít složku: {e}")

def wait_for_paths(logger, files, timeout=5):
    """
    Čeká, dokud soubory (dané absolutní nebo relativní cestou) neexistují.
    """
    logger.info(f"Čekám na soubory (timeout {timeout}s)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        missing = [f for f in files if not os.path.exists(f)]
        if not missing:
            return True
        time.sleep(0.5)
    return False

def wait_for_glob(logger, pattern, timeout=5):
    """
    Čeká, dokud glob pattern nenajde alespoň jeden soubor.
    """
    logger.info(f"Čekám na soubory podle vzoru '{pattern}' (timeout {timeout}s)...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        files = glob.glob(pattern, recursive=True)
        if files:
            return files # Vrátí seznam nalezených
        time.sleep(0.5)
    return []

def get_pubspec_name(logger):
    """
    Přečte název aplikace ze souboru pubspec.yaml (řádek 'name: ...').
    """
    try:
        with open('pubspec.yaml', 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('name:'):
                    # name: moje_aplikace -> moje_aplikace
                    return line.split(':')[1].strip()
    except Exception as e:
        logger.error(f"Chyba při čtení názvu z pubspec.yaml: {e}")
    return None