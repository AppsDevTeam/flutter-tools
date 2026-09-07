# src/logic/build_ios.py
import os
import shutil
import glob
import plistlib
import stat

# Importujeme konstanty a funkce
from .build_common import execute_command
from ..constants import KEY_FLAVOR, KEY_ENV, KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, KEY_INSTALL_COCOAPODS

def _resolve_ios_plist_path(flavor, env, env_vars):
    """
    Vyřeší cestu k GoogleService-Info.plist podle priority.
    """
    key = f"IOS_PLIST_{flavor}_{env}"
    if flavor and env and key in env_vars:
        return env_vars[key]
    
    key = f"IOS_PLIST_{flavor}"
    if flavor and key in env_vars:
        return env_vars[key]
        
    return env_vars.get("IOS_PLIST_DEFAULT")

# Cesta k upload-symbols uvnitř SPM checkoutu firebase-ios-sdk. Na rozdíl od
# CocoaPods, kde binárka leží na pevném místě v projektu, se u SPM checkouty
# vytvářejí dynamicky - buď v build adresáři, který si řídí Flutter, nebo
# v Xcode DerivedData.
_SPM_SCRIPT_SUFFIX = os.path.join(
    'SourcePackages', 'checkouts', 'firebase-ios-sdk', 'Crashlytics', 'upload-symbols'
)


def _xcode_project_name():
    """Jméno Xcode projektu v 'ios' bez přípony, nebo None když žádný není."""
    candidates = sorted(glob.glob(os.path.join('ios', '*.xcodeproj')))

    if not candidates:
        return None

    return os.path.splitext(os.path.basename(candidates[0]))[0]


def _upload_symbols_search_paths():
    """Cesty a globy, ve kterých se hledá upload-symbols, od nejspolehlivější."""
    paths = [
        # CocoaPods - pevná cesta v projektu.
        os.path.join('ios', 'Pods', 'FirebaseCrashlytics', 'upload-symbols'),
        # SPM - checkouts v build adresáři pod správou Flutteru.
        os.path.join('build', 'ios', '*', _SPM_SCRIPT_SUFFIX),
        os.path.join('build', 'ios', _SPM_SCRIPT_SUFFIX),
        os.path.join('build', _SPM_SCRIPT_SUFFIX),
    ]

    # DerivedData je poslední záchrana a leží mimo projekt, proto ji zužujeme na
    # adresáře tohoto projektu (Runner-<hash>). Bez toho by se v projektu bez
    # Firebase vzala binárka z cizího projektu, který ve DerivedData zrovna leží.
    project_name = _xcode_project_name()

    if project_name:
        paths.append(
            os.path.join(
                os.path.expanduser('~'), 'Library', 'Developer', 'Xcode', 'DerivedData',
                f'{project_name}-*', _SPM_SCRIPT_SUFFIX,
            )
        )

    return paths


def _find_upload_symbols_script(logger):
    """
    Najde binárku upload-symbols v CocoaPods i v SPM layoutu.

    Dřív se koukalo jen do 'ios/Pods', takže po přechodu projektu na SPM se
    symboly tiše přestaly nahrávat a iOS crashe se v Crashlytics neobjevily -
    bez dSYM je Crashlytics neumí zpracovat a issue vůbec nezaloží.
    """
    search_paths = _upload_symbols_search_paths()

    for pattern in search_paths:
        # Nejnovější první: po přechodu mezi Pods a SPM nebo po víc buildech
        # může na disku zbýt několik checkoutů a ten starý by nahrál symboly
        # k jiné verzi SDK.
        matches = sorted(
            (path for path in glob.glob(pattern) if os.path.isfile(path)),
            key=os.path.getmtime,
            reverse=True,
        )

        if matches:
            logger.info(f"Nalezena binárka upload-symbols: {matches[0]}")
            return matches[0]

    logger.error(
        "Binárka 'upload-symbols' nebyla nalezena v CocoaPods ani v SPM checkouts, "
        "symboly se NEnahrají a iOS crashe se v Crashlytics neobjeví. Prohledáno:\n  "
        + "\n  ".join(search_paths)
    )
    return None

def _read_archive_version(archive_path):
    """Vrátí (verze, build) z Info.plist archivu, nebo (None, None)."""
    try:
        with open(os.path.join(archive_path, 'Info.plist'), 'rb') as handle:
            info = plistlib.load(handle)
    except Exception:
        return None, None

    properties = info.get('ApplicationProperties') or {}

    return properties.get('CFBundleShortVersionString'), properties.get('CFBundleVersion')


def _find_latest_xcarchive(logger, version_name=None, build_number=None):
    """
    Najde archiv právě dokončeného buildu.

    Prioritně v 'build/ios/archive', kam ho ukládá 'flutter build ipa'. Když tam
    není - typicky protože se archivovalo z Xcode - zkusí Xcode Archives. Tam
    ale leží archivy všech projektů, takže se berou jen ty, které odpovídají
    buildované verzi; bez znalosti verze se tahle záloha přeskočí.
    """
    flutter_candidates = glob.glob(os.path.join('build', 'ios', 'archive', '*.xcarchive'))

    if flutter_candidates:
        return max(flutter_candidates, key=os.path.getmtime)

    if not version_name or not build_number:
        return None

    xcode_pattern = os.path.join(
        os.path.expanduser('~'), 'Library', 'Developer', 'Xcode', 'Archives', '*', '*.xcarchive'
    )

    matching = [
        candidate for candidate in glob.glob(xcode_pattern)
        if _read_archive_version(candidate) == (str(version_name), str(build_number))
    ]

    if not matching:
        return None

    newest = max(matching, key=os.path.getmtime)

    logger.info(
        f"V 'build/ios/archive' archiv není, použit z Xcode Archives "
        f"({version_name}+{build_number}): {newest}"
    )

    return newest

def run_ios_tasks_pre_build(logger, params, env_vars):
    """
    Spustí úlohy specifické pro iOS před buildem.
    """
    # --- 1. CocoaPods ---
    if params.get(KEY_INSTALL_COCOAPODS, False):
        logger.header("--- Spouštím CocoaPods úklid a instalaci ---")
        ios_dir = 'ios'
        if not os.path.isdir(ios_dir):
            logger.error(f"Složka '{ios_dir}' neexistuje. Nelze spustit pod install.")
            return False

        commands = [
            (['rm', '-rf', 'Pods'], "Mazání složky Pods"),
            (['pod', 'cache', 'clean', '--all'], "Čištění cache"),
            (['pod', 'deintegrate'], "Pod deintegrate"),
            (['pod', 'setup'], "Pod setup"),
            (['pod', 'install', '--repo-update'], "Pod install")
        ]

        for cmd, title in commands:
            ret_code, _ = execute_command(cmd, logger, title=title, working_dir=ios_dir)
            if cmd[0] == 'pod' and cmd[1] == 'install' and ret_code != 0:
                logger.error("Instalace Cocoapods selhala. Build byl přerušen.")
                return False
    
    # --- 2. GoogleService-Info.plist ---
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)
    
    plist_src = _resolve_ios_plist_path(flavor, env, env_vars)
    plist_dst = "ios/Runner/GoogleService-Info.plist"
    
    logger.info(f"Hledám konfiguraci pro Plist (flavor={flavor}, env={env})...")
    
    if not plist_src:
        logger.error("Nebyla nalezena žádná cesta k GoogleService-Info.plist v konfiguraci.")
        return False
        
    if not os.path.exists(plist_src):
        logger.error(f"Zdrojový soubor '{plist_src}' neexistuje.")
        return False
        
    try:
        shutil.copy(plist_src, plist_dst)
        logger.success(f"Zkopírováno: '{plist_src}' -> '{plist_dst}'")
    except Exception as e:
        logger.error(f"Chyba při kopírování Plist souboru: {e}")
        return False
    
    return True 

def run_ios_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Spustí úlohy specifické pro iOS po úspěšném buildu.
    Hlavním úkolem je najít dSYMs v archivu a nahrát je na Firebase.
    """
    
    # Kontrola, zda máme nahrávat symboly
    if params.get(KEY_DISABLE_OBFUSCATION, False) or not params.get(KEY_UPLOAD_SYMBOLS, False):
        return None # Nic neděláme

    logger.header("--- Nahrávám symboly (iOS dSYM) na Firebase ---")

    # 1. Najít skript upload-symbols
    upload_script = _find_upload_symbols_script(logger)
    if not upload_script:
        logger.error("Nahrání symbolů selhalo: Skript 'upload-symbols' nenalezen.")
        return None
    
    # Ujistíme se, že je skript spustitelný. SPM checkouty bývají read-only,
    # ale binárka v nich už executable je - chmod by tam jen zbytečně selhal.
    if not os.access(upload_script, os.X_OK):
        try:
            st = os.stat(upload_script)
            os.chmod(upload_script, st.st_mode | stat.S_IEXEC)
        except Exception as e:
            logger.warn(f"Nepodařilo se nastavit executable flag pro skript: {e}")

    # 2. Najít nejnovější archiv
    archive_path = _find_latest_xcarchive(
        logger,
        version_name=params.get("_version_name"),
        build_number=params.get("_build_number"),
    )
    if not archive_path:
        logger.error(
            "Nahrání symbolů selhalo: žádný .xcarchive nenalezen v 'build/ios/archive/' "
            "ani mezi Xcode Archives pro buildovanou verzi."
        )
        return None
    
    logger.info(f"Nalezen archiv: {archive_path}")

    # 3. Cesty k dSYMs a Plist
    dsyms_dir = os.path.join(archive_path, "dSYMs")
    gsp_path = os.path.join("ios", "Runner", "GoogleService-Info.plist")

    if not os.path.isdir(dsyms_dir):
        logger.error(f"Složka dSYMs nenalezena v archivu: {dsyms_dir}")
        return None
    
    if not os.path.exists(gsp_path):
        logger.error(f"GoogleService-Info.plist nenalezen: {gsp_path}")
        return None

    # 4. Najít všechny .dSYM soubory a nahrát je
    # Ekvivalent bash: find "$DSYMS" -name "*.dSYM" -type d ... | xargs ...
    
    dsym_found = False
    # Projdeme složku dSYMs
    for item_name in os.listdir(dsyms_dir):
        if item_name.endswith(".dSYM"):
            dsym_path = os.path.join(dsyms_dir, item_name)
            if os.path.isdir(dsym_path):
                dsym_found = True
                logger.info(f"Nahrávám: {item_name}...")
                
                cmd = [
                    upload_script,
                    '-gsp', gsp_path,
                    '-p', 'ios',
                    dsym_path
                ]
                
                ret_code, _ = execute_command(cmd, logger, log_stdout=True)
                
                if ret_code != 0:
                    logger.error(f"Chyba při nahrávání {item_name}")
                else:
                    logger.success(f"Nahráno: {item_name}")

    if dsym_found:
        actions_performed["symbols"] = True
        logger.success("Proces nahrávání symbolů dokončen.")
    else:
        logger.warn("V archivu nebyly nalezeny žádné soubory .dSYM.")
            
    return None # iOS nemá přejmenování souboru jako Android, vrací None