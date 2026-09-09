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

Kromě snapshotu se u každého ABI kontroluje ještě přítomnost `libflutter.so` a to, že
`libapp.so` i `libflutter.so` mají architekturu odpovídající názvu ABI adresáře. `pickFirst`
totiž sáhne po prvním souboru daného jména napříč ABI a umí uložit arm64 binárku do
`lib/x86_64/`. Instalace projde, `dlopen` ji ale odmítne ("is for EM_AARCH64 (183) instead
of EM_X86_64 (62)") a aplikace spadne při startu ve `FlutterLoader`.
"""
import os
import glob
import shutil
import struct
import zipfile

FLUTTER_INTERMEDIATES = os.path.join("build", "app", "intermediates", "flutter")

# Řetěz, kterým `libapp.so` putuje do APK:
#   flutter/<varianta>/<abi>/app.so   (výstup Flutteru — zdroj pravdy, NEMAZAT)
#     -> merged_jni_libs/<varianta>
#     -> merged_native_libs/<varianta>
#     -> stripped_native_libs/<varianta>
#     -> APK
#
# Vyčistit se musí všechny tři mezikroky. `merged_jni_libs` tady dřív chybělo a
# stačilo to na to, aby se do release APK protáhl `libapp.so` z předchozího buildu:
# `merged_native_libs` se přegenerovalo, ale obsah si vzalo z neaktualizovaného
# `merged_jni_libs`, takže artefakt nesl Dart kód ze starého commitu.
NATIVE_LIBS_CACHE_DIRS = [
    os.path.join("build", "app", "intermediates", "merged_jni_libs"),
    os.path.join("build", "app", "intermediates", "merged_native_libs"),
    os.path.join("build", "app", "intermediates", "stripped_native_libs"),
]

_NT_GNU_BUILD_ID = 3
_PT_NOTE = 4

_LIBAPP = "libapp.so"
_LIBFLUTTER = "libflutter.so"

# ELF `e_machine` očekávané v jednotlivých ABI adresářích. ABI, které tady není,
# se na architekturu nekontroluje — mapování by se muselo vymyslet.
_ABI_MACHINES = {
    "armeabi": 40,
    "armeabi-v7a": 40,
    "arm64-v8a": 183,
    "x86": 3,
    "x86_64": 62,
    "riscv64": 243,
}

_MACHINE_NAMES = {3: "x86", 40: "arm", 62: "x86_64", 183: "arm64", 243: "riscv64"}


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


def _read_elf_machine(data):
    """
    Vytáhne `e_machine` z ELF hlavičky. Vrací int, nebo None, pokud to není ELF.

    Stačí prvních 20 bajtů souboru, takže se nemusí načítat celý engine.
    """
    if len(data) < 20 or data[:4] != b"\x7fELF":
        return None

    endian = "<" if data[5] == 1 else ">"

    try:
        return struct.unpack_from(endian + "H", data, 0x12)[0]
    except struct.error:
        return None


def _machine_name(machine):
    """Popis architektury pro chybovou hlášku."""
    if machine is None:
        return "neznámou architekturu (není to ELF?)"

    return _MACHINE_NAMES.get(machine, f"e_machine {machine}")


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


def normalized_name(name):
    """'tapygoPreReleaseRelease' -> 'tapygoprereleaserelease'."""
    return "".join(c for c in name.lower() if c.isalnum())


def _snapshot_paths(variant_dir):
    """
    Vrátí cesty k AOT snapshotům, které Flutter vyrobil pro jednotlivá ABI.

    Kanonický layout je `<varianta>/<abi>/app.so` — prefix `lib` přidává až Gradle task,
    který snapshot kopíruje do artefaktu (viz `AndroidAot.outputs` v build_system/targets/
    android.dart). Druhý vzor je tu pro layout `<varianta>/jniLibs/<abi>/libapp.so`,
    aby check nepřestal fungovat, kdyby ho jiná verze Flutteru ukládala takhle.
    """
    paths = []

    for pattern in (os.path.join("*", "app.so"), os.path.join("jniLibs", "*", "libapp.so")):
        paths += glob.glob(os.path.join(variant_dir, pattern))

    return sorted(paths)


def _resolve_variant_dir(logger, variant):
    """
    Najde adresář, kam Flutter v tomhle buildu uložil AOT snapshoty. Vrací cestu, nebo None.

    `variant_name()` skládá jméno varianty z flavoru, env a modu, ale pořadí
    `flavorDimensions` ani zápis jmen v Gradle nemáme jak zjistit, takže se nemusí trefit.
    Dohledává se proto ve třech krocích, z nichž každý dá výsledek jen tam, kde je
    jednoznačný — nikdy se nesáhne po snapshotu cizí varianty. Ten by se od právě
    vyrobeného lišil a build by se zamítl, přesto že je v pořádku.
    """
    exact = os.path.join(FLUTTER_INTERMEDIATES, variant)

    if variant and _snapshot_paths(exact):
        return exact

    # Varianty bez snapshotu (debug buildy) se nepočítají, jinak by rozhodování níž
    # kazily adresáře, ve kterých není co porovnávat.
    available = sorted(
        d for d in glob.glob(os.path.join(FLUTTER_INTERMEDIATES, "*"))
        if os.path.isdir(d) and _snapshot_paths(d)
    )

    if not available:
        return None

    # 2) Stejné jméno jiným zápisem — 'preRelease' vs. 'prerelease' apod.
    if variant:
        matches = [d for d in available if normalized_name(os.path.basename(d)) == normalized_name(variant)]

        if len(matches) == 1:
            logger.info(f"Varianta '{variant}' odpovídá '{os.path.basename(matches[0])}'.")

            return matches[0]

    # 3) Jediná varianta se snapshotem musí být ta právě vyrobená.
    if len(available) == 1:
        logger.info(f"Používám jedinou variantu v buildu: '{os.path.basename(available[0])}'.")

        return available[0]

    logger.warn(
        f"Variantu '{variant}' se nepodařilo přiřadit k žádné z "
        f"[{', '.join(os.path.basename(d) for d in available)}] — snapshot neověřuji."
    )

    return None


def collect_expected_snapshots(logger, flavor, env, mode):
    """
    Načte build-id snapshotů, které Flutter v tomhle buildu vyrobil, pro každé ABI.

    Vrací dict {abi: build_id}. Prázdný dict znamená, že se nedá co porovnávat
    (debug build žádný AOT snapshot nemá).
    """
    variant_dir = _resolve_variant_dir(logger, variant_name(flavor, env, mode))

    if not variant_dir:
        return {}

    expected = {}

    for path in _snapshot_paths(variant_dir):
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


def _artifact_native_libs(artifact_path):
    """
    Projde APK/AAB a vrátí `(libs, abis)`.

    `libs` je {abi: {jméno: {"build_id": ..., "machine": ...}}} pro `libapp.so`
    a `libflutter.so`; build-id se čte jen u `libapp.so`, u enginu není co porovnávat.

    `abis` je množina VŠECH ABI, pro která artefakt nese jakoukoli nativní knihovnu.
    Podle ní se rozliší ABI vyfiltrované `abiFilters` nebo `--split-per-abi` (v artefaktu
    není celý `lib/<abi>/`, což je záměr) od ABI rozbitého mergem (adresář tam je,
    ale chybí v něm právě `libapp.so`).

    Obojí je omezené na jeden modul. AAB může vedle `base/` nést dynamic feature moduly
    a asset packy s vlastním `lib/<abi>/`; jejich ABI se do `abis` počítat nesmí, protože
    Dart snapshot je vždycky jen v základním modulu a chybějící `base/lib/<abi>/libapp.so`
    by se pak hlásilo i pro ABI, které do artefaktu přinesl jen feature modul.
    """
    modules = {}
    module_abis = {}

    with zipfile.ZipFile(artifact_path) as archive:
        for entry in archive.infolist():
            parts = entry.filename.split("/")

            # APK: lib/<abi>/<jméno>, AAB: <modul>/lib/<abi>/<jméno>
            if len(parts) < 3 or parts[-3] != "lib" or not parts[-1].endswith(".so"):
                continue

            module = "/".join(parts[:-3])
            abi = parts[-2]
            lib_name = parts[-1]

            modules.setdefault(module, {})
            module_abis.setdefault(module, set()).add(abi)

            if lib_name not in (_LIBAPP, _LIBFLUTTER):
                continue

            if lib_name == _LIBAPP:
                data = archive.read(entry)
                info = {"build_id": _read_build_id(data), "machine": _read_elf_machine(data)}
            else:
                with archive.open(entry) as f:
                    info = {"build_id": None, "machine": _read_elf_machine(f.read(64))}

            modules[module].setdefault(abi, {})[lib_name] = info

    target = _base_module(modules)

    if target is None:
        return {}, set()

    return modules[target], module_abis.get(target, set())


def _base_module(modules):
    """
    Vybere modul, ve kterém je Dart snapshot — u APK je to '', u AAB 'base'.

    Vrací None, pokud `libapp.so` nenese žádný modul.
    """
    with_snapshot = [
        module for module, abis in modules.items()
        if any(_LIBAPP in libs for libs in abis.values())
    ]

    if not with_snapshot:
        return None

    # Kdyby `libapp.so` bylo ve víc modulech, základní je ten s nejkratší cestou ('' < 'base').
    return sorted(with_snapshot, key=lambda m: (len(m), m))[0]


def _check_abi(abi, build_id, libs):
    """
    Ověří jedno ABI a vrátí `(problems, warnings)`.

    `problems` build zamítnou, `warnings` se jen zaloguje. Zamítá se jen to, co je
    prokazatelně rozbité: chybějící nebo starý snapshot, chybějící engine a doložený
    rozpor architektury. Cokoli, co se nepodařilo přečíst, jde do `warnings` — na
    nesnadno předvídatelném artefaktu cizího projektu se nesmí zamítnout správný build.
    """
    app = libs.get(_LIBAPP)

    if app is None:
        return [f"{abi}: libapp.so v artefaktu úplně chybí"], []

    if app.get("build_id") != build_id:
        actual = app.get("build_id") or "chybí build-id"

        return [f"{abi}: zabalen starý snapshot ({actual[:16]}… místo {build_id[:16]}…)"], []

    problems = []
    warnings = []
    engine = libs.get(_LIBFLUTTER)

    if engine is None:
        problems.append(f"{abi}: libflutter.so v artefaktu chybí, engine se nenačte")

    # Neznámé ABI (nové v NDK, nebo vlastní adresář) na architekturu nekontrolujeme —
    # mapování na e_machine bychom si museli vymyslet.
    wanted = _ABI_MACHINES.get(abi)

    if wanted is None:
        warnings.append(f"{abi}: neznámé ABI, architekturu neověřuji")

        return problems, warnings

    for lib_name, info in ((_LIBAPP, app), (_LIBFLUTTER, engine)):
        if info is None:
            continue

        machine = info.get("machine")

        if machine is None:
            warnings.append(f"{abi}: {lib_name} není čitelný ELF, architekturu neověřuji")
        elif machine != wanted:
            problems.append(f"{abi}: {lib_name} je pro {_machine_name(machine)}")

    return problems, warnings


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
        packaged, artifact_abis = _artifact_native_libs(artifact_path)
    except Exception as e:
        logger.error(f"Nepodařilo se přečíst artefakt '{artifact_path}': {e}")

        return False

    problems = []
    checked = []

    for abi, build_id in sorted(expected.items()):
        # Flutter staví pro android-arm, android-arm64 a android-x64, ale projekt může mít
        # užší `abiFilters` nebo `--split-per-abi`. Pak v artefaktu není celý `lib/<abi>/`
        # a je to záměr, ne rozbitý merge — takový build se nesmí zamítnout.
        if abi not in artifact_abis:
            logger.warn(f"   – {abi}: v artefaktu není (abiFilters / split-per-abi), nekontroluji")
            continue

        abi_problems, abi_warnings = _check_abi(abi, build_id, packaged.get(abi, {}))

        for warning in abi_warnings:
            logger.warn(f"   ! {warning}")

        if abi_problems:
            problems.extend(abi_problems)
        else:
            logger.info(f"   ✓ {abi}: {build_id}")
            checked.append(abi)

    for abi in sorted(set(packaged) - set(expected)):
        logger.warn(f"   ? {abi}: libapp.so v artefaktu navíc, tenhle build ho nevyrobil")

    if not problems:
        if checked:
            logger.success(f"Snapshot i engine sedí pro všechna ABI ({', '.join(checked)}).")
        else:
            logger.warn("Žádné ABI z tohohle buildu v artefaktu není — nebylo co ověřit.")

        return True

    logger.error("Artefakt není v pořádku:")

    for problem in problems:
        logger.error(f"   ✗ {problem}")

    logger.error(
        "Nejčastější příčina je `packagingOptions.pickFirst \"**/*.so\"` v android/app/build.gradle: "
        "vezme první soubor daného jména napříč ABI, takže do artefaktu propadne starý snapshot "
        "z předchozího buildu nebo binárka pro cizí architekturu. Zužte vzor jen na knihovny, "
        "které kolidují, spusťte `flutter clean` a build zopakujte."
    )

    return False
