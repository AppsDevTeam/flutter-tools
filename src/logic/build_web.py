# src/logic/build_web.py
import os
import shutil
import re
import json
import subprocess
import time
import webbrowser
from tkinter import messagebox

from .build_common import get_package_name, execute_command, wait_for_paths
from ..constants import KEY_FLAVOR, KEY_ENV, KEY_BUILD_MODE, KEY_CHECK_SQLITE_WEB

def run_web_tasks_pre_build(logger):
    """
    Úkoly před buildem webu:
    1. Smazání staré složky build/web (Clean)
    """
    web_build_dir = os.path.join('build', 'web')
    if os.path.exists(web_build_dir):
        logger.info(f"Mazání staré složky '{web_build_dir}'...")
        try:
            shutil.rmtree(web_build_dir)
        except Exception as e:
            logger.warn(f"Nepodařilo se smazat '{web_build_dir}': {e}")
    return True

def _add_version_query_to_assets(logger, build_number):
    """
    Implementace funkce add_version_query_to_assets přesně podle Bash skriptu.
    """
    index_path = os.path.join('build', 'web', 'index.html')
    backup_path = index_path + ".bak"
    version_param = f"?v={build_number}"

    if not os.path.exists(index_path):
        logger.error(f"Soubor {index_path} nenalezen - verze assetů nebude upravena.")
        return

    logger.info(f"Přidávám version tag ({version_param}) k assetům v index.html...")

    try:
        shutil.copy(index_path, backup_path)
    except Exception as e:
        logger.error(f"Nepodařilo se vytvořit zálohu index.html: {e}")
        return

    try:
        with open(index_path, 'r', encoding='utf-8') as f:
            content = f.read()

        targets = re.findall(r'(?:href|src)=["\']([^"\'?#]+\.[a-zA-Z0-9]+)["\']', content)
        logger.info(f"Nalezené targety pro verzování: {targets}")
        for target in targets:
            content = content.replace(target, f"{target}{version_param}")

        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        os.remove(backup_path)
        logger.success("Verze úspěšně přidána do index.html a záloha odstraněna.")

    except Exception as e:
        logger.error(f"Nastala chyba při úpravě index.html: {e}")
        if os.path.exists(backup_path):
            try:
                shutil.move(backup_path, index_path)
                logger.warn("Původní index.html byl obnoven ze zálohy.")
            except Exception as restore_error:
                logger.error(f"Kritická chyba: Nepodařilo se obnovit zálohu! {restore_error}")

def _verify_manifest(logger):
    """Ověří existenci a neprázdnost manifest.json."""
    manifest_path = os.path.join('build', 'web', 'manifest.json')
    if not os.path.exists(manifest_path) or os.path.getsize(manifest_path) == 0:
        logger.error("Chyba: manifest.json chybí nebo je prázdný!")
        return False
    logger.info("manifest.json je v pořádku.")
    return True

def _verify_version_json(logger, expected_version):
    """Ověří, zda version.json existuje a odpovídá verzi."""
    version_file_path = os.path.join('build', 'web', 'version.json')
    if os.path.exists(version_file_path):
        try:
            with open(version_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            match = re.search(r'(\d+\.\d+\.\d+)', content)
            file_version = match.group(1) if match else "unknown"
            expected_clean = expected_version.split('+')[0]
            if file_version != expected_clean:
                logger.warn(f"Upozornění: version.json ({file_version}) neodpovídá pubspec verzi ({expected_clean})")
            else:
                logger.info("version.json verze odpovídá.")
        except Exception as e:
            logger.warn(f"Chyba při čtení version.json: {e}")
    else:
        logger.warn("version.json nebyl nalezen (přeskočeno).")

def _prompt_web_verification(logger):
    """
    Spustí lokální server, otevře prohlížeč a zeptá se uživatele.
    """
    web_dir = os.path.join('build', 'web')
    if not os.path.isdir(web_dir):
        logger.error(f"Složka {web_dir} neexistuje, nelze spustit server.")
        return False

    logger.header("--- Spouštím testovací web server ---")
    port = 8000
    url = f"http://localhost:{port}"
    server_process = None

    try:
        cmd = ["python3", "-m", "http.server", str(port)]
        if os.name == 'nt': cmd[0] = "python"
        logger.info(f"Spouštím: {' '.join(cmd)} v {web_dir}")
        server_process = subprocess.Popen(
            cmd, cwd=web_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        logger.info(f"Server běží na {url} (PID: {server_process.pid})")
        time.sleep(1)
        webbrowser.open(url)
        response = messagebox.askyesno(
            "Ověření Web Buildu",
            f"Testovací server běží na {url}.\n\nOtevřela se stránka v prohlížeči? Funguje vše správně?\n\nANO = Pokračovat v balení\nNE = Zrušit build",
            icon='question'
        )
        return response
    except FileNotFoundError:
        logger.error("Python pro spuštění serveru nebyl nalezen.")
        return messagebox.askyesno("Chybí Python", "Nepodařilo se spustit server. Pokračovat?", icon='warning')
    except Exception as e:
        logger.error(f"Chyba při spouštění serveru: {e}")
        return False
    finally:
        if server_process:
            try:
                server_process.terminate()
                server_process.wait()
            except Exception as e:
                logger.warn(f"Problém při ukončování serveru: {e}")

def _stage_web_build_to_git(logger):
    """Přidá build/web do gitu (vynuceně, protože je v .gitignore)."""
    logger.info("Přidávám web build do git (git add -f build/web)...")
    execute_command(['git', 'add', '-f', 'build/web'], logger)

def _archive_web_build(logger, params, env_vars):
    """Zabalí složku build/web do ZIP archivu."""
    logger.header("--- Balím Web Build do ZIP ---")
    package_name = get_package_name(logger, env_vars)
    if not package_name: return None
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    mode = params.get(KEY_BUILD_MODE)
    version_name = params.get("_version_name")
    build_number = params.get("_build_number")
    source_dir = os.path.join('build', 'web')
    env_lc = env.lower() if env else ""
    file_env_suffix = f"-{env_lc}" if env_lc else ""
    flavor_part = f"-{flavor}" if flavor else ""
    archive_name = f"{package_name}-v{version_name}({build_number}){flavor_part}{file_env_suffix}-{mode}.web"
    output_path = os.path.join(os.getcwd(), archive_name)
    try:
        logger.info(f"Vytvářím archiv z '{source_dir}'...")
        shutil.make_archive(output_path, 'zip', source_dir)
        final_filename = output_path + ".zip"
        logger.success(f"Web build zabalen do: {final_filename}")
        return os.path.dirname(final_filename)
    except Exception as e:
        logger.error(f"Chyba při balení webu: {e}")
        return None

def restore_web_build_from_git(logger):
    logger.warn("Obnovuji build/web do původního stavu z Gitu...")
    ret_code, _ = execute_command(['git', 'ls-files', '--error-unmatch', 'build/web'], logger, log_stdout=False)
    if ret_code == 0:
        execute_command(['git', 'restore', '--staged', 'build/web'], logger)
        execute_command(['git', 'restore', 'build/web'], logger)
        logger.success("Složka build/web byla úspěšně obnovena ze stavu v gitu.")
    else:
        logger.error("Složka build/web není verzovaná - nelze obnovit přes git.")

def run_web_tasks_post_build(logger, params, env_vars, actions_performed):
    """Kompletní sada úloh po buildu webu."""
    logger.header("--- Kontrola a úprava Web Buildu ---")

    # 1. Ověřit manifest.json
    # Přidána malá prodleva pro souborový systém
    if not wait_for_paths(logger, [os.path.join('build', 'web', 'manifest.json')], timeout=3):
        logger.error("Timeout: manifest.json nebyl nalezen ani po čekání.")
        return None
        
    if not _verify_manifest(logger): return None 

    # 2. Zkontrolovat SQLite
    if params.get(KEY_CHECK_SQLITE_WEB, False):
        logger.info("Kontroluji SQLite soubory (čekám max 5s)...")
        wasm_path = os.path.join('build', 'web', 'sqlite3.wasm')
        sw_path = os.path.join('build', 'web', 'sqflite_sw.js')
        
        # --- ZMĚNA: Používáme retry logiku ---
        files_ok = wait_for_paths(logger, [wasm_path, sw_path], timeout=5)
        
        if files_ok:
            logger.success("sqlite3.wasm a sqflite_sw.js nalezeny.")
            actions_performed["web_check"] = True
        else:
            logger.error("Chybí sqlite3.wasm nebo sqflite_sw.js!")
            if not messagebox.askyesno("Chyba SQLite", "Chybí SQLite soubory! Chcete přesto pokračovat?", icon='warning'):
                return None

    version_name = params.get("_version_name")
    _verify_version_json(logger, version_name)

    build_number = params.get("_build_number")
    _add_version_query_to_assets(logger, build_number)

    logger.info("Čekám na manuální verifikaci uživatelem...")
    if not _prompt_web_verification(logger):
        logger.error("Verifikace webu zamítnuta uživatelem.")
        return None

    logger.success("Verifikace OK.")
    _stage_web_build_to_git(logger)
    actions_performed["web_added"] = True

    output_dir = _archive_web_build(logger, params, env_vars)
            
    return output_dir