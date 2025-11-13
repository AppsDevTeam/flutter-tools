# src/logic/build_web.py
import os

from ..constants import KEY_CHECK_SQLITE_WEB

def run_web_tasks_post_build(logger, params, env_vars, actions_performed):
    """Spustí úlohy specifické pro Web po úspěšném buildu (Kontrola SQLite)."""
    
    if params.get(KEY_CHECK_SQLITE_WEB, False):
        logger.header("--- Kontroluji soubory pro Web (SQLite) ---")
        wasm_path = os.path.join('build', 'web', 'sqlite3.wasm')
        sw_path = os.path.join('build', 'web', 'sqlite_sw.js')
        
        if os.path.exists(wasm_path) and os.path.exists(sw_path):
            logger.success("Kontrola souborů pro web: OK. (sqlite3.wasm i sqlite_sw.js nalezeny)")
            actions_performed["web_check"] = True
        else:
            logger.error("Kontrola souborů pro web: CHYBA!")
            if not os.path.exists(wasm_path): logger.error(" - soubor 'build/web/sqlite3.wasm' CHYBÍ!")
            if not os.path.exists(sw_path): logger.error(" - soubor 'build/web/sqlite_sw.js' CHYBÍ!")
            
    return None # Web nemá přejmenování, vrací None