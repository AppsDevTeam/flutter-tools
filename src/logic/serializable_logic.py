import os
import subprocess
import glob

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
                return
        except FileNotFoundError:
            logger.error(f"CHYBA: Příkaz '{command[0]}' nebyl nalezen. Ujistěte se, že je Flutter/Dart správně nainstalován a je v systémové cestě (PATH).\n")
            return
        except Exception as e:
            logger.error(f"Nastala neočekávaná chyba: {e}\n")
            return

    _format_generated_files(logger, startupinfo)

    logger.success("\n✨ Všechny příkazy dokončeny.\n")


def _format_generated_files(logger, startupinfo):
    """Spustí `dart format` pouze na vygenerovaných souborech (*.g.dart, *.freezed.dart)
    v lib/ a test/. Cross-platform; soubory dělíme do chunků kvůli omezení délky
    argv (zejména Windows ARG_MAX ~32 kB)."""
    logger.header("--- Formátuji vygenerované soubory ---")

    patterns = [
        'lib/**/*.g.dart', 'lib/**/*.freezed.dart',
        'test/**/*.g.dart', 'test/**/*.freezed.dart',
    ]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern, recursive=True))
    files = sorted(set(files))

    if not files:
        logger.info("Žádné vygenerované soubory nenalezeny — přeskakuji.")
        return

    logger.info(f"Nalezeno {len(files)} vygenerovaných souborů.")

    # Chunk po 100 souborech: typická cesta ~50 znaků → ~5 kB na chunk, bezpečné i pro Windows.
    chunk_size = 100
    failed_chunks = 0
    formatted_count = 0
    for i in range(0, len(files), chunk_size):
        chunk = files[i:i + chunk_size]
        try:
            process = subprocess.run(
                ['dart', 'format'] + chunk,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', startupinfo=startupinfo,
            )
            if process.returncode == 0:
                formatted_count += len(chunk)
            else:
                failed_chunks += 1
                logger.warn(f"dart format chunk {i // chunk_size + 1} skončil s kódem {process.returncode}:")
                if process.stdout:
                    logger.warn(process.stdout)
        except FileNotFoundError:
            logger.error("CHYBA: Příkaz 'dart' nebyl nalezen v PATH.")
            return
        except Exception as e:
            logger.error(f"Chyba při formátování: {e}")
            return

    if failed_chunks == 0:
        logger.success(f"✅ Naformátováno {formatted_count} vygenerovaných souborů.")
    else:
        logger.warn(f"⚠️ {failed_chunks} chunků selhalo, naformátováno {formatted_count} z {len(files)}.")