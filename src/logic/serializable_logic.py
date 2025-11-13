import os
import subprocess

def run_json_serializable_logic(logger):
    """Spouští příkazy pro flutter clean, pub get a build_runner."""
    commands = {
        "Spouštím flutter clean...": ['flutter', 'clean'],
        "Spouštím flutter package get...": ['flutter', 'packages', 'pub', 'get'],
        "Spouštím generování kódu...": ['dart', 'run', 'build_runner', 'build', '--delete-conflicting-outputs']
    }

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    for title, command in commands.items():
        logger.header(f"--- {title} ---")
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding='utf-8', bufsize=1, startupinfo=startupinfo
            )
            for line in iter(process.stdout.readline, ''):
                logger.raw(line)
            process.stdout.close()
            process.wait()
            if process.returncode != 0:
                logger.error(f"\n❌ Příkaz skončil s chybovým kódem: {process.returncode}\n")
                break
        except FileNotFoundError:
            logger.error(f"CHYBA: Příkaz '{command[0]}' nebyl nalezen. Ujistěte se, že je Flutter/Dart správně nainstalován a je v systémové cestě (PATH).\n")
            return
        except Exception as e:
            logger.error(f"Nastala neočekávaná chyba: {e}\n")
            return
    logger.success("\n✨ Všechny příkazy dokončeny.\n")