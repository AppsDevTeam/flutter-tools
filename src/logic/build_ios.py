# src/logic/build_ios.py
from .build_common import execute_command, resolve_value

from ..constants import KEY_FLAVOR, KEY_ENV, KEY_DISABLE_OBFUSCATION, KEY_UPLOAD_SYMBOLS, KEY_INSTALL_COCOAPODS

def run_ios_tasks_pre_build(logger, params):
    """Spustí úlohy specifické pro iOS před buildem (Cocoapods)."""
    
    if params.get(KEY_INSTALL_COCOAPODS, False):
        ret_code, _ = execute_command(['pod', 'install', '--repo-update'], logger, 
                                      title="Instaluji Cocoapods", working_dir='ios')
        if ret_code != 0:
            logger.error("Instalace Cocoapods selhala. Build byl přerušen.")
            return False # Označuje selhání
        
        return True # Označuje úspěch
    
    return True # Nic se nedělalo, úspěch

def run_ios_tasks_post_build(logger, params, env_vars, actions_performed):
    """Spustí úlohy specifické pro iOS po úspěšném buildu (Nahrání symbolů)."""
    
    flavor = params.get(KEY_FLAVOR)
    env = params.get(KEY_ENV)

    # 1. Nahrání symbolů
    if not params.get(KEY_DISABLE_OBFUSCATION, False) and params.get(KEY_UPLOAD_SYMBOLS, False):
        logger.header("--- Nahrávám symboly (iOS) na Firebase ---")
        firebase_app_id = resolve_value("FIREBASE_APP_ID", flavor, env, env_vars)
        
        if firebase_app_id:
            symbols_cmd = [
                'flutterfire', 'crashlytics:symbols:upload',
                f'--app={firebase_app_id}',
                '--os=ios'
            ]
            ret_code, _ = execute_command(symbols_cmd, logger)
            if ret_code == 0:
                logger.success("Symboly úspěšně nahrány.")
                actions_performed["symbols"] = True
            else:
                logger.error("Nahrání symbolů selhalo.")
        else:
            logger.warn("FIREBASE_APP_ID nenalezen v adt_tools_config.env. Nelze nahrát symboly.")
            
    return None # iOS nemá přejmenování, vrací None