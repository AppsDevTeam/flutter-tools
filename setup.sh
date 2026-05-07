#!/bin/bash

# ADT Flutter Tools — interaktivní setup.
# Spusťte před prvním použitím aplikace: ./setup.sh
# Detekuje OS + dostupné package managery a nabídne instalaci toho, co chybí.
# Když je víc možností (např. brew + npm pro firebase), zeptá se, kterou chcete.

set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
DIM='\033[2m'
NC='\033[0m'

MISSING=()
INSTALLED=()
SKIPPED=()

# ---------------------------------------------------------------------------
# Detekce OS a distribuce
# ---------------------------------------------------------------------------
OS_TYPE="unknown"
LINUX_DISTRO=""
case "$OSTYPE" in
    linux-gnu*) OS_TYPE="linux" ;;
    darwin*)    OS_TYPE="macos" ;;
    cygwin|msys|win32) OS_TYPE="windows" ;;
esac

if [ "$OS_TYPE" = "linux" ] && [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    LINUX_DISTRO="${ID:-}"
fi

echo -e "${BLUE}=== ADT Flutter Tools — setup ===${NC}"
echo -e "Systém: ${YELLOW}$OS_TYPE${NC}${LINUX_DISTRO:+ (${LINUX_DISTRO})}"

# ---------------------------------------------------------------------------
# Detekce dostupných package managerů
# ---------------------------------------------------------------------------
has() { command -v "$1" &> /dev/null; }

HAS_BREW=0;   has brew   && HAS_BREW=1
HAS_NPM=0;    has npm    && HAS_NPM=1
HAS_GEM=0;    has gem    && HAS_GEM=1
HAS_APT=0;    has apt-get && HAS_APT=1
HAS_DNF=0;    has dnf    && HAS_DNF=1
HAS_PACMAN=0; has pacman && HAS_PACMAN=1
HAS_ZYPPER=0; has zypper && HAS_ZYPPER=1
HAS_SNAP=0;   has snap   && HAS_SNAP=1
HAS_WINGET=0; has winget && HAS_WINGET=1
HAS_SCOOP=0;  has scoop  && HAS_SCOOP=1
HAS_CHOCO=0;  has choco  && HAS_CHOCO=1
HAS_GIT=0;    has git    && HAS_GIT=1
HAS_DART=0;   has dart   && HAS_DART=1

AVAILABLE_MGRS=()
[ $HAS_BREW   -eq 1 ] && AVAILABLE_MGRS+=("brew")
[ $HAS_NPM    -eq 1 ] && AVAILABLE_MGRS+=("npm")
[ $HAS_GEM    -eq 1 ] && AVAILABLE_MGRS+=("gem")
[ $HAS_APT    -eq 1 ] && AVAILABLE_MGRS+=("apt")
[ $HAS_DNF    -eq 1 ] && AVAILABLE_MGRS+=("dnf")
[ $HAS_PACMAN -eq 1 ] && AVAILABLE_MGRS+=("pacman")
[ $HAS_ZYPPER -eq 1 ] && AVAILABLE_MGRS+=("zypper")
[ $HAS_SNAP   -eq 1 ] && AVAILABLE_MGRS+=("snap")
[ $HAS_WINGET -eq 1 ] && AVAILABLE_MGRS+=("winget")
[ $HAS_SCOOP  -eq 1 ] && AVAILABLE_MGRS+=("scoop")
[ $HAS_CHOCO  -eq 1 ] && AVAILABLE_MGRS+=("choco")

if [ ${#AVAILABLE_MGRS[@]} -gt 0 ]; then
    echo -e "Dostupné nástroje: ${DIM}${AVAILABLE_MGRS[*]}${NC}"
fi
echo

# ---------------------------------------------------------------------------
# Interaktivní helpery (čtou z /dev/tty, aby šlo skript pipe-ovat)
# ---------------------------------------------------------------------------
ask_yn() {
    # ask_yn "Otázka" [default_y|default_n]
    local prompt="$1"
    local default="${2:-default_n}"
    local hint="[y/N]"
    [ "$default" = "default_y" ] && hint="[Y/n]"
    local ans
    echo -ne "${BLUE}${prompt} ${hint}: ${NC}"
    read -r ans < /dev/tty || ans=""
    if [ -z "$ans" ]; then
        [ "$default" = "default_y" ] && return 0 || return 1
    fi
    [[ "$ans" =~ ^[YyAa]$ ]]
}

choose_one() {
    # choose_one "Otázka" "opt1" "opt2" ...
    # Vrací zvolenou hodnotu přes globální REPLY_CHOICE.
    local prompt="$1"; shift
    local opts=("$@")
    local i
    echo -e "${BLUE}${prompt}${NC}"
    for i in "${!opts[@]}"; do
        echo -e "  ${YELLOW}$((i+1)))${NC} ${opts[$i]}"
    done
    echo -e "  ${YELLOW}0)${NC} přeskočit"
    local ans
    while true; do
        echo -ne "${BLUE}Volba [1-${#opts[@]}, 0=přeskočit]: ${NC}"
        read -r ans < /dev/tty || ans=""
        if [[ "$ans" =~ ^[0-9]+$ ]]; then
            if [ "$ans" -eq 0 ]; then
                REPLY_CHOICE=""
                return 1
            fi
            if [ "$ans" -ge 1 ] && [ "$ans" -le "${#opts[@]}" ]; then
                REPLY_CHOICE="${opts[$((ans-1))]}"
                return 0
            fi
        fi
        echo -e "${YELLOW}Neplatná volba.${NC}"
    done
}

run_cmd() {
    # run_cmd "popis" cmd args...
    local desc="$1"; shift
    echo -e "${DIM}\$ $*${NC}"
    if "$@"; then
        echo -e "${GREEN}✓ $desc${NC}"
        return 0
    else
        echo -e "${RED}✗ $desc selhalo${NC}"
        return 1
    fi
}

run_shell() {
    # run_shell "popis" "shell expression"  — pro pipe / sudo / složené příkazy
    local desc="$1"; shift
    echo -e "${DIM}\$ $*${NC}"
    if bash -c "$*"; then
        echo -e "${GREEN}✓ $desc${NC}"
        return 0
    else
        echo -e "${RED}✗ $desc selhalo${NC}"
        return 1
    fi
}

needs_sudo_for_npm_global() {
    [ $HAS_NPM -eq 1 ] || return 1
    [ "$OS_TYPE" = "windows" ] && return 1
    local prefix
    prefix=$(npm config get prefix 2>/dev/null || echo "")
    [ -n "$prefix" ] && [ ! -w "$prefix/lib/node_modules" ] && [ ! -w "$prefix/lib" ]
}

# ---------------------------------------------------------------------------
# Generická per-dep instalace
# Každá fce vrací 0 pokud je nakonec nainstalováno, 1 jinak.
# ---------------------------------------------------------------------------

# --- GIT ---
check_git() {
    echo -n "Git... "
    if has git; then
        echo -e "${GREEN}OK${NC} ($(git --version))"
        return 0
    fi
    echo -e "${RED}CHYBÍ${NC}"
    return 1
}

install_git() {
    local opts=()
    case "$OS_TYPE" in
        macos)
            opts+=("xcode-select --install (Apple Command Line Tools)")
            [ $HAS_BREW -eq 1 ] && opts+=("brew install git")
            ;;
        linux)
            [ $HAS_APT    -eq 1 ] && opts+=("sudo apt-get install -y git")
            [ $HAS_DNF    -eq 1 ] && opts+=("sudo dnf install -y git")
            [ $HAS_PACMAN -eq 1 ] && opts+=("sudo pacman -S --noconfirm git")
            [ $HAS_ZYPPER -eq 1 ] && opts+=("sudo zypper install -y git")
            ;;
        windows)
            [ $HAS_WINGET -eq 1 ] && opts+=("winget install --id Git.Git -e --silent")
            [ $HAS_SCOOP  -eq 1 ] && opts+=("scoop install git")
            [ $HAS_CHOCO  -eq 1 ] && opts+=("choco install -y git")
            ;;
    esac
    if [ ${#opts[@]} -eq 0 ]; then
        echo -e "${YELLOW}Žádný známý package manager není dostupný.${NC}"
        echo -e "${YELLOW}-> Stáhněte ručně: https://git-scm.com/downloads${NC}"
        return 1
    fi
    if ! choose_one "Jak nainstalovat Git?" "${opts[@]}"; then
        return 1
    fi
    run_shell "Instalace Git" "$REPLY_CHOICE" || return 1
    has git
}

# --- FLUTTER ---
check_flutter() {
    echo -n "Flutter SDK... "
    if has flutter; then
        local ver
        ver=$(flutter --version 2>/dev/null | head -n 1)
        echo -e "${GREEN}OK${NC} ($ver)"
        return 0
    fi
    echo -e "${RED}CHYBÍ${NC}"
    return 1
}

install_flutter_via_git() {
    local target="$HOME/flutter"
    if [ -d "$target" ]; then
        echo -e "${YELLOW}$target už existuje. Přeskakuji klonování.${NC}"
    else
        run_cmd "Klonování Flutter SDK do $target" \
            git clone --depth 1 -b stable https://github.com/flutter/flutter.git "$target" || return 1
    fi
    # Přidání do PATH (pro aktuální session i shell rc)
    export PATH="$target/bin:$PATH"
    local rc=""
    case "${SHELL##*/}" in
        zsh)  rc="$HOME/.zshrc" ;;
        bash) rc="$HOME/.bashrc" ;;
    esac
    if [ -n "$rc" ] && [ -f "$rc" ] && ! grep -q "flutter/bin" "$rc"; then
        if ask_yn "Přidat 'export PATH=\"$target/bin:\$PATH\"' do $rc?" default_y; then
            echo "" >> "$rc"
            echo "# Flutter SDK (přidáno ADT Flutter Tools setup)" >> "$rc"
            echo "export PATH=\"$target/bin:\$PATH\"" >> "$rc"
            echo -e "${GREEN}✓ Přidáno do $rc${NC}"
            echo -e "${YELLOW}Otevřete nový terminál nebo: source $rc${NC}"
        fi
    fi
    has flutter
}

install_flutter() {
    local opts=()
    case "$OS_TYPE" in
        macos)
            [ $HAS_BREW -eq 1 ] && opts+=("brew install --cask flutter")
            ;;
        linux)
            [ $HAS_SNAP -eq 1 ] && opts+=("sudo snap install flutter --classic")
            ;;
        windows)
            [ $HAS_WINGET -eq 1 ] && opts+=("winget install --id Google.Flutter -e --silent")
            [ $HAS_SCOOP  -eq 1 ] && opts+=("scoop bucket add extras; scoop install flutter")
            [ $HAS_CHOCO  -eq 1 ] && opts+=("choco install -y flutter")
            ;;
    esac
    # Univerzální fallback: git clone (vyžaduje git)
    if [ $HAS_GIT -eq 1 ] || has git; then
        opts+=("git clone do ~/flutter (oficiální postup, ~1 GB)")
    fi
    if [ ${#opts[@]} -eq 0 ]; then
        echo -e "${YELLOW}Není dostupný žádný způsob instalace.${NC}"
        echo -e "${YELLOW}-> Návod: https://docs.flutter.dev/get-started/install${NC}"
        return 1
    fi
    if ! choose_one "Jak nainstalovat Flutter SDK? (~1 GB stažení)" "${opts[@]}"; then
        return 1
    fi
    if [[ "$REPLY_CHOICE" == git\ clone* ]]; then
        install_flutter_via_git
    else
        run_shell "Instalace Flutter" "$REPLY_CHOICE" || return 1
        has flutter
    fi
}

# --- FIREBASE CLI ---
check_firebase() {
    echo -n "Firebase CLI... "
    if has firebase; then
        echo -e "${GREEN}OK${NC} ($(firebase --version))"
        return 0
    fi
    echo -e "${YELLOW}NENALEZENO${NC}"
    return 1
}

install_firebase() {
    local opts=()
    if [ $HAS_BREW -eq 1 ] && [ "$OS_TYPE" = "macos" ]; then
        opts+=("brew install firebase-cli")
    fi
    if [ $HAS_NPM -eq 1 ]; then
        if needs_sudo_for_npm_global; then
            opts+=("sudo npm install -g firebase-tools")
        else
            opts+=("npm install -g firebase-tools")
        fi
    fi
    case "$OS_TYPE" in
        windows)
            [ $HAS_WINGET -eq 1 ] && opts+=("winget install --id Google.FirebaseCLI -e --silent")
            [ $HAS_SCOOP  -eq 1 ] && opts+=("scoop install firebase-cli")
            [ $HAS_CHOCO  -eq 1 ] && opts+=("choco install -y firebase-tools")
            ;;
    esac
    if [ ${#opts[@]} -eq 0 ]; then
        echo -e "${YELLOW}-> Pro instalaci nejdřív Node.js (npm): https://nodejs.org/${NC}"
        return 1
    fi
    echo -e "${DIM}Firebase CLI je potřeba jen pro nahrávání symbolů na Crashlytics. Bez něj build funguje.${NC}"
    if ! choose_one "Jak nainstalovat Firebase CLI?" "${opts[@]}"; then
        return 1
    fi
    run_shell "Instalace Firebase CLI" "$REPLY_CHOICE" || return 1
    has firebase
}

# --- PYTHON 3 ---
PYTHON_CMD=""
detect_python() {
    if has python3; then
        PYTHON_CMD="python3"
    elif has python; then
        local ver
        ver=$(python --version 2>&1 | awk '{print $2}' | cut -d. -f1)
        [ "$ver" = "3" ] && PYTHON_CMD="python"
    fi
}

check_python() {
    echo -n "Python 3... "
    detect_python
    if [ -n "$PYTHON_CMD" ]; then
        echo -e "${GREEN}OK${NC} ($($PYTHON_CMD --version 2>&1))"
        return 0
    fi
    echo -e "${RED}CHYBÍ${NC}"
    return 1
}

install_python() {
    local opts=()
    case "$OS_TYPE" in
        macos)
            [ $HAS_BREW -eq 1 ] && opts+=("brew install python")
            ;;
        linux)
            [ $HAS_APT    -eq 1 ] && opts+=("sudo apt-get install -y python3 python3-tk")
            [ $HAS_DNF    -eq 1 ] && opts+=("sudo dnf install -y python3 python3-tkinter")
            [ $HAS_PACMAN -eq 1 ] && opts+=("sudo pacman -S --noconfirm python tk")
            [ $HAS_ZYPPER -eq 1 ] && opts+=("sudo zypper install -y python3 python3-tk")
            ;;
        windows)
            [ $HAS_WINGET -eq 1 ] && opts+=("winget install --id Python.Python.3.12 -e --silent")
            [ $HAS_SCOOP  -eq 1 ] && opts+=("scoop install python")
            [ $HAS_CHOCO  -eq 1 ] && opts+=("choco install -y python")
            ;;
    esac
    if [ ${#opts[@]} -eq 0 ]; then
        echo -e "${YELLOW}-> Stáhněte Python 3: https://www.python.org/downloads/${NC}"
        return 1
    fi
    if ! choose_one "Jak nainstalovat Python 3?" "${opts[@]}"; then
        return 1
    fi
    run_shell "Instalace Python 3" "$REPLY_CHOICE" || return 1
    detect_python
    [ -n "$PYTHON_CMD" ]
}

# --- TKINTER ---
check_tkinter() {
    echo -n "Tkinter (GUI modul)... "
    if [ -z "$PYTHON_CMD" ]; then
        echo -e "${YELLOW}přeskočeno (chybí Python)${NC}"
        return 1
    fi
    if $PYTHON_CMD -c "import tkinter" &> /dev/null; then
        echo -e "${GREEN}OK${NC}"
        return 0
    fi
    echo -e "${RED}CHYBÍ${NC}"
    return 1
}

install_tkinter() {
    local opts=()
    case "$OS_TYPE" in
        macos)
            [ $HAS_BREW -eq 1 ] && opts+=("brew install python-tk")
            ;;
        linux)
            [ $HAS_APT    -eq 1 ] && opts+=("sudo apt-get install -y python3-tk")
            [ $HAS_DNF    -eq 1 ] && opts+=("sudo dnf install -y python3-tkinter")
            [ $HAS_PACMAN -eq 1 ] && opts+=("sudo pacman -S --noconfirm tk")
            [ $HAS_ZYPPER -eq 1 ] && opts+=("sudo zypper install -y python3-tk")
            ;;
        windows)
            echo -e "${YELLOW}Na Windows je tkinter součástí python.org installeru — přeinstalujte Python a zaškrtněte 'tcl/tk and IDLE'.${NC}"
            return 1
            ;;
    esac
    if [ ${#opts[@]} -eq 0 ]; then
        echo -e "${YELLOW}Žádná známá cesta instalace. Reinstall Pythonu z balíčku obsahujícího tk.${NC}"
        return 1
    fi
    if ! choose_one "Jak nainstalovat Tkinter?" "${opts[@]}"; then
        return 1
    fi
    run_shell "Instalace Tkinter" "$REPLY_CHOICE" || return 1
    $PYTHON_CMD -c "import tkinter" &> /dev/null
}

# --- COCOAPODS (jen macOS) ---
check_cocoapods() {
    echo -n "CocoaPods... "
    if has pod; then
        echo -e "${GREEN}OK${NC} ($(pod --version))"
        return 0
    fi
    echo -e "${YELLOW}NENALEZENO${NC}"
    return 1
}

install_cocoapods() {
    local opts=()
    [ $HAS_BREW -eq 1 ] && opts+=("brew install cocoapods")
    [ $HAS_GEM  -eq 1 ] && opts+=("sudo gem install cocoapods")
    if [ ${#opts[@]} -eq 0 ]; then
        echo -e "${YELLOW}-> Návod: https://guides.cocoapods.org/using/getting-started.html${NC}"
        return 1
    fi
    echo -e "${DIM}CocoaPods je potřeba jen pro iOS buildy.${NC}"
    if ! choose_one "Jak nainstalovat CocoaPods?" "${opts[@]}"; then
        return 1
    fi
    run_shell "Instalace CocoaPods" "$REPLY_CHOICE" || return 1
    has pod
}

# ---------------------------------------------------------------------------
# Spojovací logika: check + případná instalace
# ---------------------------------------------------------------------------
ensure() {
    # ensure <name> <check_fn> <install_fn>
    local name="$1" check_fn="$2" install_fn="$3"
    if $check_fn; then
        return 0
    fi
    if ask_yn "Nainstalovat $name nyní?" default_y; then
        if $install_fn; then
            INSTALLED+=("$name")
            return 0
        else
            MISSING+=("$name")
            return 1
        fi
    else
        SKIPPED+=("$name")
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Hlavní průchod
# ---------------------------------------------------------------------------
ensure "Git"          check_git       install_git
ensure "Flutter SDK"  check_flutter   install_flutter
ensure "Firebase CLI" check_firebase  install_firebase
ensure "Python 3"     check_python    install_python
ensure "Tkinter"      check_tkinter   install_tkinter
if [ "$OS_TYPE" = "macos" ]; then
    ensure "CocoaPods" check_cocoapods install_cocoapods
fi

echo
echo -e "${BLUE}=== Souhrn ===${NC}"
[ ${#INSTALLED[@]} -gt 0 ] && echo -e "${GREEN}Nainstalováno:${NC} ${INSTALLED[*]}"
[ ${#SKIPPED[@]}   -gt 0 ] && echo -e "${YELLOW}Přeskočeno:${NC} ${SKIPPED[*]}"
[ ${#MISSING[@]}   -gt 0 ] && echo -e "${RED}Stále chybí:${NC} ${MISSING[*]}"

# Kritické závislosti pro běh aplikace: Python 3 + Tkinter.
# Flutter je potřeba pro buildy. Firebase / CocoaPods jen pro některé funkce.
CRITICAL_MISSING=0
for dep in "${MISSING[@]:-}" "${SKIPPED[@]:-}"; do
    case "$dep" in
        "Python 3"|"Tkinter") CRITICAL_MISSING=1 ;;
    esac
done

if [ $CRITICAL_MISSING -eq 1 ]; then
    echo -e "${RED}Bez Pythonu 3 + Tkinteru aplikace nepoběží.${NC}"
    exit 1
fi

echo -e "${GREEN}Hotovo. Aplikaci můžete spustit.${NC}"
exit 0
