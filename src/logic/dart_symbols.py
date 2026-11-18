# src/logic/dart_symbols.py
"""
Dart symboly z `--split-debug-info` vznikají jen tehdy, když Flutter opravdu spustí
gen_snapshot. Ten má vlastní cache v `.dart_tool/flutter_build/<hash>/` (hash z defines,
tedy i z cesty pro symboly) a soubory `.symbols` mezi výstupy nesleduje.

Když build se stejnou cestou pro symboly jednou proběhne a složka se symboly pak zmizí
(typicky ji smaže rollback neúspěšného buildu), další build vezme zkompilovaný snapshot
z cache, gen_snapshot nespustí a symboly už nevzniknou. Artefakt je funkčně v pořádku,
pády z něj ale nejde symbolikovat a nahrání symbolů spadne na prázdné složce.

Řešení: před buildem bez symbolů smazat stampy AOT cílů. Chybějící stamp Flutter
bere jako „cíl ještě neběžel“ a gen_snapshot spustí znovu; kompilace do kernelu
(app.dill) zůstává v cache.

Na Androidu to samo nestačí: `flutter assemble` spouští Gradle úloha
`compileFlutterBuild<Varianta>`, jejímž výstupem je depfile `flutter_build.d` a soubory
v něm vyjmenované. Dokud jsou na místě a vstupy se nezměnily, Gradle úlohu přeskočí
jako UP-TO-DATE a Flutter se ke stampům vůbec nedostane. Proto se maže i depfile.
Na iOS Xcode spouští `xcode_backend.sh` při každém buildu, tam stampy stačí.
"""
import glob
import os

FLUTTER_BUILD_CACHE = os.path.join('.dart_tool', 'flutter_build')
ANDROID_FLUTTER_DEPFILES = os.path.join('build', 'app', 'intermediates', 'flutter', '*', 'flutter_build.d')

# Cíle, které spouští gen_snapshot (build_system/targets/android.dart a ios.dart):
# Android `android_aot_<mode>_<abi>` (+ navazující `android_aot_bundle_…`), iOS `aot_assembly_<mode>`.
AOT_STAMP_PATTERNS = ['android_aot_*.stamp', 'aot_assembly_*.stamp']


def has_symbol_files(symbols_dir):
    """True, když složka obsahuje aspoň jeden soubor `.symbols`."""
    return bool(symbols_dir) and bool(glob.glob(os.path.join(symbols_dir, '*.symbols')))


def invalidate_aot_cache(logger):
    """
    Smaže stampy AOT cílů ve všech konfiguracích Flutter build cache, aby gen_snapshot
    proběhl znovu a zapsal symboly. Konfigurace podle hashe nejde spárovat s buildem,
    proto se berou všechny; ostatním release buildům to přidá jen nový běh gen_snapshot.
    """
    stamps = [
        path for pattern in AOT_STAMP_PATTERNS
        for path in glob.glob(os.path.join(FLUTTER_BUILD_CACHE, '*', pattern))
    ]
    depfiles = glob.glob(ANDROID_FLUTTER_DEPFILES)

    removed_stamps = _remove_all(logger, stamps)
    removed_depfiles = _remove_all(logger, depfiles)

    if removed_stamps or removed_depfiles:
        logger.info(f"Složka se symboly je prázdná — vynucuji novou kompilaci Dartu "
                    f"(smazáno {removed_stamps} AOT stampů a {removed_depfiles} Gradle depfilů).")


def _remove_all(logger, paths):
    removed = 0
    for path in paths:
        try:
            os.remove(path)
            removed += 1
        except OSError as e:
            logger.warn(f"Nepodařilo se smazat '{path}': {e}")
    return removed
