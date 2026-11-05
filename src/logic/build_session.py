# src/logic/build_session.py
"""
Přerušení běžícího buildu a návrat projektu do stavu před ním.

UI založí BuildSession a předá ji buildu v parametrech (PARAM_BUILD_SESSION). Build ji
aktivuje, takže execute_command i běh Claude přes ni registrují své procesy. cancel()
z UI vlákna ukončí běžící proces i s potomky (flutter → gradle / xcodebuild, pod)
a build na nejbližší kontrole vyhodí BuildCancelled.

Soubory a složky, které build mění, se před změnou zapíšou do žurnálu (snapshot_file,
track_new_dir, move_aside) a restore() je vrátí — při přerušení i při selhání buildu.
Před commitem a pushem build vstoupí do nevratné fáze (enter_irreversible): od té
chvíle už přerušit nejde, protože commit a push na server vrátit nelze.
"""
import os
import shutil
import signal
import subprocess
import threading
import time

PARAM_BUILD_SESSION = "_build_session"

# Odložené původní složky (Pods, build/web). build/ je ve Flutter projektech v .gitignore
# a leží na stejném disku jako projekt, takže přesun je okamžitý a nic se nekopíruje.
ROLLBACK_DIR = os.path.join('build', '.adt_rollback')

# Jak dlouho dostane přerušený proces na ukončení po SIGTERM, než dostane SIGKILL.
_KILL_GRACE_S = 5

_ENTRY_FILE = "file"
_ENTRY_NEW_DIR = "new_dir"
_ENTRY_MOVED = "moved"
_ENTRY_STAGED = "staged"


class BuildCancelled(BaseException):
    """
    Build přerušil uživatel. BaseException, aby ji nespolklo `except Exception`
    v jednotlivých krocích buildu a doputovala až do run_flutter_build_logic.
    """


class BuildSession:
    """Stav jednoho běhu buildu: přerušení, běžící procesy a žurnál změn k vrácení."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cancel_requested = False
        self._irreversible = False
        self._processes = set()
        self._journal = []
        self._journaled_paths = set()

    # --- Přerušení -----------------------------------------------------------

    @property
    def cancel_requested(self):
        with self._lock:
            return self._cancel_requested

    @property
    def irreversible(self):
        with self._lock:
            return self._irreversible

    def cancel(self):
        """
        Požádá o přerušení a ukončí běžící procesy. Vrací False, když už build
        přerušit nejde (nevratná fáze) nebo přerušení už běží.
        """
        with self._lock:
            if self._irreversible or self._cancel_requested:
                return False
            self._cancel_requested = True
            processes = list(self._processes)
        for process in processes:
            _terminate_in_background(process)
        return True

    def check(self):
        """Kontrolní bod mezi kroky buildu: po přerušení vyhodí BuildCancelled."""
        if self.cancel_requested:
            raise BuildCancelled()

    def enter_irreversible(self):
        """
        Začíná commit / push: od teď se build nepřerušuje a nic se nevrací, takže
        se zahodí i odložené složky. Přišlo-li přerušení těsně předtím, vyhodí
        BuildCancelled a build se ještě vrátí.
        """
        with self._lock:
            if self._cancel_requested:
                raise BuildCancelled()
            self._irreversible = True
        self.discard_backups()

    def popen_kwargs(self):
        """Parametry Popen: vlastní skupina procesů, aby šel ukončit i s potomky."""
        if os.name == 'nt':
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def register_process(self, process):
        """Proces spuštěný po přerušení (souběh s cancel()) se ukončí hned."""
        with self._lock:
            self._processes.add(process)
            cancelled = self._cancel_requested
        if cancelled:
            _terminate_in_background(process)

    def unregister_process(self, process):
        with self._lock:
            self._processes.discard(process)

    # --- Žurnál změn ---------------------------------------------------------

    def snapshot_file(self, path, unstage=False):
        """
        Zapamatuje si obsah souboru před změnou (nebo že neexistoval). Při vrácení
        se obsah obnoví, nový soubor smaže; unstage=True ho navíc odebere z indexu gitu.
        Opakované volání pro stejnou cestu nic nedělá — platí první, původní stav.
        """
        if path in self._journaled_paths:
            return
        content = None
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                content = f.read()
        self._add_entry((_ENTRY_FILE, path, content, unstage))

    def track_new_dir(self, path):
        """Složka, kterou build založí: při vrácení se smaže. Existující se nesleduje."""
        if path in self._journaled_paths or os.path.exists(path):
            return
        self._add_entry((_ENTRY_NEW_DIR, path, None, False))

    def move_aside(self, path, unstage=False):
        """
        Místo smazání složku odloží do ROLLBACK_DIR; při vrácení se nová složka smaže
        a původní vrátí. Neexistující složka se jen sleduje jako nová.
        """
        if path in self._journaled_paths:
            return
        if not os.path.exists(path):
            self._add_entry((_ENTRY_NEW_DIR, path, None, unstage))
            return
        backup = os.path.join(ROLLBACK_DIR, path.replace(os.sep, '__').replace('/', '__'))
        os.makedirs(ROLLBACK_DIR, exist_ok=True)
        if os.path.exists(backup):
            shutil.rmtree(backup)
        os.rename(path, backup)
        self._add_entry((_ENTRY_MOVED, path, backup, unstage))

    def track_staged(self, path):
        """Cesta, kterou build přidá do indexu gitu: při vrácení se z indexu odebere."""
        if path in self._journaled_paths:
            return
        self._add_entry((_ENTRY_STAGED, path, None, True))

    def restore(self, logger):
        """Vrátí všechny zaznamenané změny v obráceném pořadí."""
        if not self._journal:
            return
        logger.header("--- Vracím soubory do stavu před buildem ---")
        unstage_paths = []
        for kind, path, data, unstage in reversed(self._journal):
            try:
                _restore_entry(logger, kind, path, data)
            except Exception as e:
                logger.error(f"Nepodařilo se vrátit '{path}': {e}")
            if unstage:
                unstage_paths.append(path)
        if unstage_paths:
            # Mimo execute_command: vrácení musí proběhnout i po přerušení buildu.
            subprocess.run(['git', 'reset', '-q', '--', *unstage_paths], capture_output=True)
        self._journal.clear()
        self._journaled_paths.clear()

    def discard_backups(self):
        """Zahodí odložené složky — po úspěchu, po nevratné fázi i po vrácení."""
        self._journal.clear()
        self._journaled_paths.clear()
        if os.path.isdir(ROLLBACK_DIR):
            shutil.rmtree(ROLLBACK_DIR, ignore_errors=True)

    def _add_entry(self, entry):
        self._journal.append(entry)
        self._journaled_paths.add(entry[1])


# --- Aktivní session ----------------------------------------------------------
# Build běží vždy jen jeden (UI během něj spouštění zakáže), takže stačí jedna
# aktivní session pro celý proces. Bez ní (NBSP, JsonSerializable) se nic nemění.

_active = None


def activate(session):
    global _active
    _active = session


def deactivate():
    """Po deaktivaci execute_command nepřerušuje — vracení změn potřebuje git."""
    global _active
    _active = None


def current():
    return _active


def checkpoint():
    if _active:
        _active.check()


def snapshot_file(path, unstage=False):
    if _active:
        _active.snapshot_file(path, unstage)


def track_new_dir(path):
    if _active:
        _active.track_new_dir(path)


def track_staged(path):
    if _active:
        _active.track_staged(path)


def remove_dir(path, unstage=False):
    """Smaže složku před buildem; s aktivní session ji jen odloží, aby šla vrátit."""
    if _active:
        _active.move_aside(path, unstage)
    elif os.path.exists(path):
        shutil.rmtree(path)


# --- Pomocné funkce -----------------------------------------------------------

def _restore_entry(logger, kind, path, data):
    if kind == _ENTRY_FILE:
        if data is None:
            if os.path.isfile(path):
                os.remove(path)
                logger.warn(f"Smazán soubor vytvořený buildem: {path}")
            return
        with open(path, 'wb') as f:
            f.write(data)
        logger.warn(f"Vrácen soubor: {path}")
    elif kind == _ENTRY_NEW_DIR:
        if os.path.isdir(path):
            shutil.rmtree(path)
            logger.warn(f"Smazána složka vytvořená buildem: {path}")
    elif kind == _ENTRY_MOVED:
        if os.path.isdir(path):
            shutil.rmtree(path)
        os.rename(data, path)
        logger.warn(f"Vrácena původní složka: {path}")


def _terminate_in_background(process):
    """Ukončení čeká až _KILL_GRACE_S, proto mimo volající (UI) vlákno."""
    threading.Thread(target=_terminate, args=(process,), daemon=True).start()


def _terminate(process):
    """Ukončí proces i s potomky: nejdřív SIGTERM celé skupině, po prodlevě SIGKILL."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
        return

    # Proces běží ve vlastní session (start_new_session), takže pgid == pid.
    pgid = process.pid
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return

    deadline = time.monotonic() + _KILL_GRACE_S
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)

    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
