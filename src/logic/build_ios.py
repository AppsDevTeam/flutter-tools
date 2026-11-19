# src/logic/build_ios.py
import os
import shutil
import glob
import plistlib
import stat
from datetime import timezone

# Importujeme konstanty a funkce
from .build_common import execute_command
from . import build_session
from .crash_reporting import PROVIDER_FIREBASE, PROVIDER_GLITCHTIP, PROVIDER_NONE, GlitchTipSettings, upload_debug_files
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

        # Pod deintegrate / install přepisují projekt Xcode — při přerušení nebo selhání
        # se vrátí. Pods se místo smazání odloží, aby šly vrátit bez nové instalace.
        for path in ('Podfile.lock', os.path.join('Runner.xcodeproj', 'project.pbxproj'),
                     os.path.join('Runner.xcworkspace', 'contents.xcworkspacedata')):
            build_session.snapshot_file(os.path.join(ios_dir, path))
        logger.info("Odkládám složku Pods (vrátí se, když build nedoběhne)...")
        build_session.remove_dir(os.path.join(ios_dir, 'Pods'))

        commands = [
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
    
    # --- 2. GoogleService-Info.plist (jen Firebase) ---
    if params.get("_crash_provider", PROVIDER_FIREBASE) != PROVIDER_FIREBASE:
        logger.info("Projekt nepoužívá Firebase (CRASH_REPORTING) — GoogleService-Info.plist se nekopíruje.")
        return True

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
        build_session.snapshot_file(plist_dst)
        shutil.copy(plist_src, plist_dst)
        logger.success(f"Zkopírováno: '{plist_src}' -> '{plist_dst}'")
    except Exception as e:
        logger.error(f"Chyba při kopírování Plist souboru: {e}")
        return False
    
    return True 

def run_ios_tasks_post_build(logger, params, env_vars, actions_performed):
    """
    Spustí úlohy specifické pro iOS po úspěšném buildu.
    Hlavním úkolem je najít dSYMs v archivu a nahrát je do služby pro hlášení pádů
    (Firebase Crashlytics, nebo GlitchTip i s Dart symboly).
    """
    
    # Kontrola, zda máme nahrávat symboly
    if params.get(KEY_DISABLE_OBFUSCATION, False) or not params.get(KEY_UPLOAD_SYMBOLS, False):
        return None # Nic neděláme

    provider = params.get("_crash_provider", PROVIDER_FIREBASE)
    if provider == PROVIDER_NONE:
        logger.info("CRASH_REPORTING=none — symboly se nenahrávají.")
        return None
    if provider == PROVIDER_GLITCHTIP:
        _upload_ios_symbols_to_glitchtip(logger, params, env_vars, actions_performed)
        return None

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


def _upload_ios_symbols_to_glitchtip(logger, params, env_vars, actions_performed):
    """dSYM z archivu (nativní část) a Dart symboly z --split-debug-info do GlitchTipu."""
    logger.header("--- Nahrávám symboly (iOS dSYM a Dart) do GlitchTipu ---")
    settings = GlitchTipSettings.resolve(logger, params, env_vars)
    if not settings:
        return

    paths = [params.get("_symbols_dir")]
    archive_path = _find_latest_xcarchive(
        logger,
        version_name=params.get("_version_name"),
        build_number=params.get("_build_number"),
    )
    if archive_path:
        paths.append(os.path.join(archive_path, "dSYMs"))
    else:
        logger.warn("Archiv .xcarchive nenalezen — nahrají se jen Dart symboly.")

    if upload_debug_files(logger, settings, paths, "iOS symboly"):
        actions_performed["symbols"] = True


# 'flutter build ipa' exportuje IPA příkazem xcodebuild -exportArchive a ten do výstupní složky
# zapíše i ExportOptions.plist, se kterým exportoval (podepsání pro zvolený flavor).
_FLUTTER_ARCHIVE_DIR = os.path.join('build', 'ios', 'archive')
_FLUTTER_EXPORT_OPTIONS = os.path.join('build', 'ios', 'ipa', 'ExportOptions.plist')
_UPLOAD_DIR = os.path.join('build', 'ios', 'upload')


def upload_to_app_store_connect(logger, params):
    """
    Nahraje archiv z 'flutter build ipa' do App Store Connect stejně jako Distribute App
    v Organizeru Xcode: xcodebuild -exportArchive s destination=upload, pod účtem přihlášeným
    v Xcode (Settings → Accounts), bez API klíče. Vrátí True, když nahrání prošlo.

    Číslo buildu se nemění (manageAppVersionAndBuildNumber=false): jinak Xcode build, jehož
    číslo už v App Store Connect je, potichu nahraje pod vyšším číslem a to pak nesedí
    s pubspec.yaml, gitem ani symboly. Duplicitní build App Store Connect odmítne.
    """
    logger.header("--- Nahrávám do App Store Connect ---")
    version_name = str(params.get("_version_name"))
    build_number = str(params.get("_build_number"))

    archives = glob.glob(os.path.join(_FLUTTER_ARCHIVE_DIR, '*.xcarchive'))
    if not archives:
        logger.error(f"Nahrání selhalo: v '{_FLUTTER_ARCHIVE_DIR}' není archiv .xcarchive.")
        return False
    archive_path = max(archives, key=os.path.getmtime)

    try:
        with open(os.path.join(archive_path, 'Info.plist'), 'rb') as handle:
            archive_info = plistlib.load(handle)
        with open(_FLUTTER_EXPORT_OPTIONS, 'rb') as handle:
            export_options = plistlib.load(handle)
    except Exception as e:
        logger.error(f"Nahrání selhalo: nejde přečíst archiv nebo '{_FLUTTER_EXPORT_OPTIONS}': {e}")
        return False

    properties = archive_info.get('ApplicationProperties') or {}
    archive_version = (properties.get('CFBundleShortVersionString'), properties.get('CFBundleVersion'))
    if archive_version != (version_name, build_number):
        logger.error(
            f"Nahrání selhalo: archiv má verzi {archive_version[0]}+{archive_version[1]}, "
            f"build je {version_name}+{build_number}."
        )
        return False

    # ExportOptions.plist z dřívějšího buildu (jiný flavor) by archiv podepsal jiným profilem.
    created = archive_info.get('CreationDate')
    if created and os.path.getmtime(_FLUTTER_EXPORT_OPTIONS) < created.replace(tzinfo=timezone.utc).timestamp():
        logger.error(
            f"Nahrání selhalo: '{_FLUTTER_EXPORT_OPTIONS}' je starší než archiv, "
            f"Flutter z tohoto buildu IPA neexportoval."
        )
        return False

    export_options['destination'] = 'upload'
    export_options['manageAppVersionAndBuildNumber'] = False

    shutil.rmtree(_UPLOAD_DIR, ignore_errors=True)
    os.makedirs(_UPLOAD_DIR)
    options_path = os.path.join(_UPLOAD_DIR, 'ExportOptions.plist')
    with open(options_path, 'wb') as handle:
        plistlib.dump(export_options, handle)

    bundle_id = properties.get('CFBundleIdentifier', '?')
    logger.info(f"{bundle_id} {version_name} ({build_number}), účet přihlášený v Xcode")

    ret_code, _ = execute_command(
        [
            'xcodebuild', '-exportArchive',
            '-archivePath', archive_path,
            '-exportOptionsPlist', options_path,
            '-exportPath', _UPLOAD_DIR,
        ],
        logger,
    )
    if ret_code != 0:
        logger.error(
            "Nahrání do App Store Connect selhalo. Časté příčiny: build s tímto číslem už v App "
            "Store Connect je, nebo v Xcode (Settings → Accounts) není přihlášený účet týmu."
        )
        return False

    logger.success(f"Nahráno do App Store Connect: {version_name} ({build_number}). Zpracování trvá pár minut.")
    return True
