# src/logic/build_desktop.py
import os
import glob
import shutil
import tarfile
import zipfile

from .build_common import get_pubspec_name, execute_command, wait_for_glob, wait_for_paths
from ..constants import KEY_GIT_PUSH

def _get_desktop_app_name(env_vars):
    """Načte DESKTOP_APP_NAME z proměnných prostředí."""
    # Logger zde není potřeba, jen vracíme hodnotu
    return env_vars.get("DESKTOP_APP_NAME", "")

def _stage_desktop_artifact_to_git(logger, archive_path):
    """
    Přidá vytvořený archiv do Gitu (force add).
    """
    if os.path.exists(archive_path):
        logger.info(f"Přidávám desktop build artefakt do gitu: {archive_path}")
        # git add -f, protože build složka je v .gitignore
        execute_command(['git', 'add', '-f', archive_path], logger)
        return True
    return False

def run_desktop_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Logika pro Desktop: Přejmenování binárky, vytvoření archivu a git add.
    """
    logger.header("--- Zpracování výstupu (Desktop) ---")
    
    app_name = _get_desktop_app_name(env_vars)
    if not app_name:
        logger.warn("DESKTOP_APP_NAME není nastaven v adt_tools_config.env, ponechávám původní názvy a nearchivuji.")
        return None

    logger.info(f"Přejmenovávám desktop binary na: {app_name}...")

    build_type = params.get("build_type")
    mode = params.get("build_mode", "release") 
    version_name = params.get("_version_name")
    build_number = params.get("_build_number")
    
    # Zjistíme, zda máme provádět git operace
    should_git_add = params.get(KEY_GIT_PUSH, False)

    # --- MACOS ---
    if build_type == 'macos':
        build_path = "build/macos/Build/Products/Release"
        if not os.path.exists(build_path):
             logger.error(f"Složka {build_path} neexistuje.")
             return None

        candidates = wait_for_glob(logger, os.path.join(build_path, "*.app"))

        if candidates:
            app_bundle = candidates[0]
            new_app_path = os.path.join(build_path, f"{app_name}.app")
            
            try:
                shutil.move(app_bundle, new_app_path)
                logger.success(f"macOS app přejmenována na: {new_app_path}")
                
                zip_name = f"{app_name}-v{version_name}({build_number})-macos.zip"
                output_archive_path = os.path.join(build_path, zip_name)
                
                logger.info(f"Vytvářím zip: {zip_name}...")
                with zipfile.ZipFile(output_archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    root_len = len(build_path) + 1
                    for root, dirs, files in os.walk(new_app_path):
                        for file in files:
                            fn = os.path.join(root, file)
                            zipf.write(fn, fn[root_len:])
                            
                logger.success(f"Vytvořen zip: {output_archive_path}")
                
                # --- GIT ADD ---
                if should_git_add:
                    if _stage_desktop_artifact_to_git(logger, output_archive_path):
                        actions_performed["desktop_added"] = True

                return build_path
                
            except Exception as e:
                logger.error(f"Chyba při zpracování macOS: {e}")
                return None
        else:
            logger.error(f"macOS .app bundle nebyl nalezen v {build_path}")
            return None

    # --- LINUX ---
    elif build_type == 'linux':
        build_path = f"build/linux/x64/{mode.lower()}/bundle"
        if not os.path.exists(build_path):
             search_glob = f"build/linux/*/{mode.lower()}/bundle"
             found = wait_for_glob(logger, search_glob)

             if found: build_path = found[0]
             else:
                 logger.error(f"Složka {build_path} neexistuje.")
                 return None
             
        pubspec_name = get_pubspec_name(logger)
        if not pubspec_name: return None
        
        exec_file = os.path.join(build_path, pubspec_name)
        
        if wait_for_paths(logger, [exec_file]):
            new_exec_path = os.path.join(build_path, app_name)
            try:
                shutil.move(exec_file, new_exec_path)
                os.chmod(new_exec_path, 0o755)
                logger.success(f"Linux binary přejmenován na: {new_exec_path}")
                
                tar_name = f"{app_name}-v{version_name}({build_number})-linux.tar.gz"
                output_archive_path = os.path.join(build_path, tar_name)
                
                logger.info(f"Vytvářím archiv: {tar_name}...")
                with tarfile.open(output_archive_path, "w:gz") as tar:
                    tar.add(build_path, arcname=os.path.basename(build_path))
                
                logger.success(f"Vytvořen archiv: {output_archive_path}")

                # --- GIT ADD ---
                if should_git_add:
                    if _stage_desktop_artifact_to_git(logger, output_archive_path):
                        actions_performed["desktop_added"] = True

                return build_path
                
            except Exception as e:
                logger.error(f"Chyba při zpracování Linux: {e}")
                return None
        else:
            logger.error(f"Linux binary nebyl nalezen: {exec_file}")
            return None

    # --- WINDOWS ---
    elif build_type == 'windows':
        build_path = f"build/windows/x64/runner/{mode.capitalize()}"
        if not os.path.exists(build_path):
             search_glob = f"build/windows/*/*/runner/{mode.capitalize()}"
             found = wait_for_glob(logger,search_glob)
             if found: build_path = found[0]
             else:
                 search_glob_lower = f"build/windows/*/*/runner/{mode.lower()}"
                 found_lower = wait_for_glob(logger,search_glob_lower)
                 if found_lower: build_path = found_lower[0]
                 else:
                     logger.error(f"Složka {build_path} neexistuje.")
                     return None
             
        pubspec_name = get_pubspec_name(logger)
        if not pubspec_name: return None
        
        exe_file = os.path.join(build_path, f"{pubspec_name}.exe")
        
        if os.path.exists(exe_file):
            new_exe_path = os.path.join(build_path, f"{app_name}.exe")
            try:
                shutil.move(exe_file, new_exe_path)
                logger.success(f"Windows executable přejmenován na: {new_exe_path}")
                
                data_dir = os.path.join(build_path, "data")
                if not wait_for_paths(logger, [data_dir]):
                    logger.error(f"❌ Složka 'data/' nebyla nalezena v {build_path} – build bude nefunkční!")
                    return None
                
                zip_name = f"{app_name}-v{version_name}({build_number})-windows.zip"
                output_archive_path = os.path.join(build_path, zip_name)
                
                logger.info(f"Balím aplikaci (včetně data/)...")
                with zipfile.ZipFile(output_archive_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in os.listdir(build_path):
                        if file.endswith(".exe") or file.endswith(".dll"):
                            zipf.write(os.path.join(build_path, file), file)
                    for root, dirs, files in os.walk(data_dir):
                        for file in files:
                            abs_path = os.path.join(root, file)
                            rel_path = os.path.relpath(abs_path, build_path)
                            zipf.write(abs_path, rel_path)
                            
                logger.success(f"Vytvořen zip: {output_archive_path}")

                # --- GIT ADD ---
                if should_git_add:
                    if _stage_desktop_artifact_to_git(logger, output_archive_path):
                        actions_performed["desktop_added"] = True

                return build_path
                
            except Exception as e:
                logger.error(f"Chyba při zpracování Windows: {e}")
                return None
        else:
            logger.error(f"Windows executable nebyl nalezen: {exe_file}")
            return None

    return None