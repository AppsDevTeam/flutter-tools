# src/logic/build_desktop.py
import os
import shutil
import tarfile
import zipfile
import hashlib

from .build_common import get_pubspec_name, execute_command, wait_for_glob, wait_for_paths
from ..constants import (
    KEY_GIT_PUSH, KEY_CREATE_INSTALLER, 
    KEY_INNO_PUBLISHER, KEY_INNO_URL, KEY_INNO_LICENSE,
    KEY_INNO_WIZARD_IMAGE, KEY_INNO_WIZARD_SMALL_IMAGE,
    KEY_INNO_WIZARD_STYLE, KEY_INNO_COMPRESSION,
    KEY_INNO_TASK_DESKTOP, KEY_INNO_LANGUAGES, KEY_INNO_ICON
)

def _get_desktop_app_name(env_vars):
    """Načte DESKTOP_APP_NAME z proměnných prostředí."""
    # Logger zde není potřeba, jen vracíme hodnotu
    return env_vars.get("DESKTOP_APP_NAME", "")

def _generate_app_id(app_name):
    """Vygeneruje unikátní GUID na základě názvu aplikace."""
    # To zajistí, že stejná aplikace bude mít vždy stejné ID a instalátor ji přepíše/aktualizuje
    hash_object = hashlib.md5(app_name.encode())
    return f"{{{{ {hash_object.hexdigest().upper()} }}}}"

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

def _create_windows_installer(logger, build_dir, app_name, version, output_dir, params):
    """Generuje .iss a spouští build."""
    logger.header("--- Vytvářím Windows Installer (Inno Setup) ---")
    
    # 1. Najít ISCC (stejné jako minule)
    iscc_path = shutil.which("iscc")
    if not iscc_path:
        # ... (standardní cesty) ...
        # Pokud nenajde:
        logger.error("Nástroj Inno Setup (ISCC.exe) nebyl nalezen.")
        return None

    # 2. Získání hodnot z UI (params)
    publisher = params.get(KEY_INNO_PUBLISHER, "")
    url = params.get(KEY_INNO_URL, "")
    license_file = params.get(KEY_INNO_LICENSE, "")
    wizard_image = params.get(KEY_INNO_WIZARD_IMAGE, "")
    wizard_small_image = params.get(KEY_INNO_WIZARD_SMALL_IMAGE, "")
    wizard_style = params.get(KEY_INNO_WIZARD_STYLE, "modern")
    compression = params.get(KEY_INNO_COMPRESSION, "lzma")
    create_desktop_icon = params.get(KEY_INNO_TASK_DESKTOP, True)
    languages_str = params.get(KEY_INNO_LANGUAGES, "english")
    icon_path = params.get(KEY_INNO_ICON, "")

    # 3. Sestavení sekcí pro .iss
    
    # Ikona
    setup_icon_line = ""
    if icon_path and os.path.exists(icon_path):
        setup_icon_line = f"SetupIconFile={os.path.abspath(icon_path)}"

    # Licence
    license_line = ""
    if license_file and os.path.exists(license_file):
        license_line = f"LicenseFile={os.path.abspath(license_file)}"

    # Obrázky
    wizard_image_line = ""
    if wizard_image and os.path.exists(wizard_image):
        wizard_image_line = f"WizardImageFile={os.path.abspath(wizard_image)}"
        
    wizard_small_image_line = ""
    if wizard_small_image and os.path.exists(wizard_small_image):
        wizard_small_image_line = f"WizardSmallImageFile={os.path.abspath(wizard_small_image)}"

    # Jazyky
    languages_list = [l.strip().lower() for l in languages_str.split(',')]
    languages_section = "[Languages]\n"
    for lang in languages_list:
        if lang == "english":
            languages_section += 'Name: "english"; MessagesFile: "compiler:Default.isl"\n'
        else:
            lang_file = lang.capitalize()
            languages_section += f'Name: "{lang}"; MessagesFile: "compiler:Languages\\{lang_file}.isl"\n'

    # Tasks (Desktop icon)
    tasks_section = "[Tasks]\n"
    if create_desktop_icon:
        tasks_section += 'Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked'

    # 4. Finální šablona (sestavená v Pythonu)
    abs_build_dir = os.path.abspath(build_dir)
    abs_output_dir = os.path.abspath(output_dir)
    setup_filename = f"{app_name}_setup"
    app_id = _generate_app_id(app_name)

    iss_content = f"""
[Setup]
AppId={app_id}
AppName={app_name}
AppVersion={version}
AppPublisher={publisher}
AppPublisherURL={url}
AppSupportURL={url}
AppUpdatesURL={url}
DefaultDirName={{autopf}}\\{app_name}
DefaultGroupName={app_name}
OutputBaseFilename={setup_filename}
OutputDir={abs_output_dir}
Compression={compression}
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle={wizard_style}
{setup_icon_line}
{license_line}
{wizard_image_line}
{wizard_small_image_line}

{languages_section}

{tasks_section}

[Files]
Source: "{abs_build_dir}\\{app_name}.exe"; DestDir: "{{app}}"; Flags: ignoreversion
Source: "{abs_build_dir}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{{group}}\\{app_name}"; Filename: "{{app}}\\{app_name}.exe"
Name: "{{commondesktop}}\\{app_name}"; Filename: "{{app}}\\{app_name}.exe"; Tasks: desktopicon

[Run]
Filename: "{{app}}\\{app_name}.exe"; Description: "{{cm:LaunchProgram,{app_name}}}"; Flags: nowait postinstall skipifsilent
"""

    # 5. Uložení a kompilace
    iss_file_path = "temp_installer_script.iss"
    try:
        with open(iss_file_path, "w", encoding="utf-8") as f:
            f.write(iss_content)
    except Exception as e:
        logger.error(f"Nepodařilo se vytvořit .iss soubor: {e}")
        return None

    logger.info(f"Spouštím Inno Setup kompilátor...")
    ret_code, output = execute_command([iscc_path, iss_file_path], logger)
    
    if os.path.exists(iss_file_path):
        os.remove(iss_file_path)

    if ret_code == 0:
        installer_path = os.path.join(abs_output_dir, setup_filename + ".exe")
        logger.success(f"Instalátor vytvořen: {installer_path}")
        return installer_path
    else:
        logger.error("Vytváření instalátoru selhalo.")
        return None

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
    should_create_installer = params.get(KEY_CREATE_INSTALLER, False)

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
                
                if should_create_installer:
                    full_version = f"{version_name}+{build_number}"
                    
                    installer_path = _create_windows_installer(
                        logger, build_path, app_name, full_version, build_path, params
                    )

                    if installer_path and should_git_add:
                         if _stage_desktop_artifact_to_git(logger, installer_path):
                             actions_performed["desktop_added"] = True

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