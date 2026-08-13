# src/logic/android_snapshot_check.py
"""
Kontrola, že zabalené APK/AAB opravdu obsahuje Dart snapshot z právě proběhlého buildu.

Gradle merguje nativní knihovny inkrementálně a `packagingOptions.pickFirst "**/*.so"`
umí způsobit, že se do artefaktu dostane starý `libapp.so` z předchozího buildu, případně
že tam pro některé ABI nebude vůbec. Build v obou případech skončí úspěchem — aplikace
pak ale běží na starém Dart kódu, nebo na daném ABI spadne hned po splash screenu
v `Shell::Create` (chybí snapshot -> Dart VM nevznikne -> null dereference v enginu).

Porovnává se GNU build-id ze sekce `.note.gnu.build-id`, které Dart do snapshotu zapisuje
a které přežije strip (`stripDebugSymbols` mění velikost souboru, build-id ne).
"""
import os
import glob
import shutil
import struct
import zipfile

FLUTTER_INTERMEDIATES = os.path.join("build", "app", "intermediates", "flutter")
NATIVE_LIBS_CACHE_DIRS = [
    os.path.join("build", "app", "intermediates", "merged_native_libs"),
    os.path.join("build", "app", "intermediates", "stripped_native_libs"),
]

_NT_GNU_BUILD_ID = 3
_PT_NOTE = 4


def _camel_case(s):
    """Převede 'release' na 'Release', 'prod' na 'Prod'."""
    if not s:
        return ""
    return s[0].upper() + s[1:].lower()


def variant_name(flavor, env, mode):
    """
    Sestaví název Gradle varianty, pod kterou Flutter i AGP ukládají mezivýstupy.

    Např. flavor 'tapygo' + env 'prod' + mode 'release' -> 'tapygoProdRelease'.
    Bez flavoru je varianta jen 'release' / 'profile' / 'debug'.
    """
    mode_camel = _camel_case(mode)

    if not flavor:
        return mode.lower() if mode else ""

    return f"{flavor}{_camel_case(env)}{mode_camel}"


def _read_build_id(data):
    """
    Vytáhne GNU build-id z ELF souboru v paměti. Vrací hex string, nebo None.

    Čte se přes program headers (PT_NOTE), aby to fungovalo i na stripnutých
    knihovnách, kde nemusí být tabulka sekcí.
    """
    if len(data) < 64 or data[:4] != b"\x7fELF":
        return None

    is_64 = data[4] == 2
    endian = "<" if data[5] == 1 else ">"

    try:
        if is_64:
            e_phoff = struct.unpack_from(endian + "Q", data, 0x20)[0]
            e_phentsize, e_phnum = struct.unpack_from(endian + "HH", data, 0x36)
        else:
            e_phoff = struct.unpack_from(endian + "I", data, 0x1C)[0]
            e_phentsize, e_phnum = struct.unpack_from(endian + "HH", data, 0x2A)
    except struct.error:
        return None

    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize

        try:
            p_type = struct.unpack_from(endian + "I", data, off)[0]

            if p_type != _PT_NOTE:
                continue

            if is_64:
                p_offset = struct.unpack_from(endian + "Q", data, off + 0x08)[0]
                p_filesz = struct.unpack_from(endian + "Q", data, off + 0x20)[0]
            else:
                p_offset = struct.unpack_from(endian + "I", data, off + 0x04)[0]
                p_filesz = struct.unpack_from(endian + "I", data, off + 0x10)[0]
        except struct.error:
            continue

        build_id = _scan_notes(data, endian, p_offset, p_filesz)

        if build_id:
            return build_id

    return None


def _scan_notes(data, endian, offset, size):
    """Projde jeden PT_NOTE segment a vrátí build-id, pokud ho obsahuje."""
    end = min(offset + size, len(data))
    pos = offset

    while pos + 12 <= end:
        try:
            namesz, descsz, ntype = struct.unpack_from(endian + "III", data, pos)
        except struct.error:
            return None

        name_start = pos + 12
        desc_start = name_start + ((namesz + 3) // 4) * 4
        desc_end = desc_start + descsz

        if desc_end > end:
            return None

        if ntype == _NT_GNU_BUILD_ID and data[name_start:name_start + namesz] == b"GNU\x00":
            return data[desc_start:desc_end].hex()

        pos = desc_start + ((descsz + 3) // 4) * 4

    return None


def purge_native_libs_cache(logger, flavor, env, mode):
    """
    Smaže Gradle cache sloučených nativních knihoven, aby se `libapp.so` zabalil znovu.

    Jde o pár set MB, které se stejně regenerují — proti plnému `flutter clean` to stojí
    sekundy a přesně tenhle krok je ten, který si drží starý snapshot.
    """
    variant = variant_name(flavor, env, mode)
    removed = []

    for cache_dir in NATIVE_LIBS_CACHE_DIRS:
        # Cache ostatních variant necháváme být — stará se jen tahle varianta.
        # Bez známé varianty nezbývá než smazat celý adresář.
        if variant:
            targets = [os.path.join(cache_dir, variant)]
        else:
            targets = [cache_dir]

        for target in [t for t in targets if os.path.isdir(t)]:
            try:
                shutil.rmtree(target)
                removed.append(target)
            except Exception as e:
                logger.warn(f"Nepodařilo se smazat '{target}': {e}")

    if removed:
        logger.header("--- Čistím cache nativních knihoven (Gradle merge) ---")

        for target in removed:
            logger.info(f"   ✓ smazáno: {target}")
    else:
        logger.info("Cache nativních knihoven je prázdná, není co mazat.")


def collect_expected_snapshots(logger, flavor, env, mode):
    """
    Načte build-id `libapp.so`, které Flutter v tomhle buildu vyrobil, pro každé ABI.

    Vrací dict {abi: build_id}. Prázdný dict znamená, že se nedá co porovnávat
    (debug build žádný AOT snapshot nemá).
    """
    variant = variant_name(flavor, env, mode)
    jni_dir = os.path.join(FLUTTER_INTERMEDIATES, variant, "jniLibs")

    if not os.path.isdir(jni_dir):
        # Varianta se nemusí trefit (jiné pojmenování flavoru) — vezmeme tu,
        # jejíž snapshoty jsou nejčerstvější, protože build právě doběhl.
        candidates = glob.glob(os.path.join(FLUTTER_INTERMEDIATES, "*", "jniLibs", "*", "libapp.so"))

        if not candidates:
            return {}

        candidates.sort(key=os.path.getmtime, reverse=True)
        jni_dir = os.path.dirname(os.path.dirname(candidates[0]))

        logger.info(f"Varianta '{variant}' nenalezena, používám '{jni_dir}'.")

    expected = {}

    for path in sorted(glob.glob(os.path.join(jni_dir, "*", "libapp.so"))):
        abi = os.path.basename(os.path.dirname(path))

        try:
            with open(path, "rb") as f:
                build_id = _read_build_id(f.read())
        except Exception as e:
            logger.warn(f"Nelze přečíst '{path}': {e}")
            continue

        if build_id:
            expected[abi] = build_id
        else:
            logger.warn(f"V '{path}' není GNU build-id, ABI {abi} nelze ověřit.")

    return expected


def _artifact_snapshots(artifact_path):
    """Vrátí {abi: build_id} pro všechny libapp.so uvnitř APK/AAB."""
    found = {}

    with zipfile.ZipFile(artifact_path) as archive:
        for name in archive.namelist():
            parts = name.split("/")

            # APK: lib/<abi>/libapp.so, AAB: base/lib/<abi>/libapp.so
            if len(parts) < 3 or parts[-1] != "libapp.so" or parts[-3] != "lib":
                continue

            found[parts[-2]] = _read_build_id(archive.read(name))

    return found


def verify_dart_snapshots(logger, artifact_path, flavor, env, mode):
    """
    Ověří, že artefakt obsahuje pro každé ABI ten `libapp.so`, který tenhle build vyrobil.

    Vrací True, pokud je vše v pořádku nebo pokud není co ověřovat (debug build).
    """
    if (mode or "").lower() == "debug":
        return True

    logger.header("--- Ověřuji Dart snapshot v artefaktu ---")

    expected = collect_expected_snapshots(logger, flavor, env, mode)

    if not expected:
        logger.warn("Nenalezen žádný vyrobený libapp.so — snapshot nelze ověřit.")

        return True

    try:
        packaged = _artifact_snapshots(artifact_path)
    except Exception as e:
        logger.error(f"Nepodařilo se přečíst artefakt '{artifact_path}': {e}")

        return False

    problems = []

    for abi, build_id in sorted(expected.items()):
        actual = packaged.get(abi)

        if actual is None:
            problems.append(f"{abi}: libapp.so v artefaktu úplně chybí")
        elif actual != build_id:
            problems.append(f"{abi}: zabalen starý snapshot ({actual[:16]}… místo {build_id[:16]}…)")
        else:
            logger.info(f"   ✓ {abi}: {build_id}")

    for abi in sorted(set(packaged) - set(expected)):
        logger.warn(f"   ? {abi}: libapp.so v artefaktu navíc, tenhle build ho nevyrobil")

    if not problems:
        logger.success(f"Snapshot sedí pro všechna ABI ({', '.join(sorted(expected))}).")

        return True

    logger.error("Artefakt neobsahuje kód z tohoto buildu:")

    for problem in problems:
        logger.error(f"   ✗ {problem}")

    logger.error(
        "Nejčastější příčina je `packagingOptions.pickFirst \"**/*.so\"` v android/app/build.gradle "
        "v kombinaci s inkrementálním buildem. Spusť `flutter clean` a build zopakuj."
    )

    return False
