#!/bin/bash

# Barvy pro výpis
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Kontrola prostředí pro ADT Flutter Tools ===${NC}\n"

OS_TYPE="unknown"
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    OS_TYPE="macos"
elif [[ "$OSTYPE" == "cygwin" ]]; then
    OS_TYPE="windows"
elif [[ "$OSTYPE" == "msys" ]]; then
    OS_TYPE="windows"
elif [[ "$OSTYPE" == "win32" ]]; then
    OS_TYPE="windows"
fi

echo -e "Detekován systém: ${YELLOW}$OS_TYPE${NC}"

# --- 1. Kontrola GIT ---
echo -n "Kontrola Git... "
if command -v git &> /dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}CHYBÍ!${NC}"
    echo -e "${YELLOW}-> Nainstalujte Git a přidejte ho do PATH.${NC}"
    exit 1
fi

# --- 2. Kontrola FLUTTER ---
echo -n "Kontrola Flutter... "
if command -v flutter &> /dev/null; then
    FLUTTER_VERSION=$(flutter --version | head -n 1)
    echo -e "${GREEN}OK${NC} ($FLUTTER_VERSION)"
else
    echo -e "${RED}CHYBÍ!${NC}"
    echo -e "${YELLOW}-> Flutter SDK nebyl nalezen v PATH. Aplikace nebude schopna provádět buildy.${NC}"
    # Neukončujeme, aplikace se může spustit, ale nebude fungovat build
fi

# --- 3. Kontrola FLUTTERFIRE (NOVÉ) ---
echo -n "Kontrola FlutterFire CLI... "
if command -v flutterfire &> /dev/null; then
    FF_VERSION=$(flutterfire --version)
    echo -e "${GREEN}OK${NC} ($FF_VERSION)"
else
    echo -e "${YELLOW}NENALEZENO${NC}"
    echo -e "${YELLOW}-> 'flutterfire' chybí. Nebude fungovat nahrávání symbolů na Crashlytics.${NC}"
    echo -e "   -> Instalace: ${BLUE}dart pub global activate flutterfire_cli${NC}"
    echo -e "   -> Ujistěte se, že máte PATH nastavenou pro Dart Pub cache."
    exit 1
fi

# --- 4. Kontrola PYTHON ---
echo -n "Kontrola Python 3... "
PYTHON_CMD=""

if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    # Ověříme, že je to verze 3
    VER=$(python --version 2>&1 | awk '{print $2}' | cut -d. -f1)
    if [ "$VER" == "3" ]; then
        PYTHON_CMD="python"
    fi
fi

if [ -n "$PYTHON_CMD" ]; then
    PY_VER=$($PYTHON_CMD --version)
    echo -e "${GREEN}OK${NC} ($PY_VER)"
else
    echo -e "${RED}CHYBÍ!${NC}"
    echo -e "${YELLOW}-> Nainstalujte Python 3: https://www.python.org/downloads/${NC}"
    exit 1
fi

# --- 5. Kontrola TKINTER ---
echo -n "Kontrola Tkinter (GUI)... "
if $PYTHON_CMD -c "import tkinter" &> /dev/null; then
    echo -e "${GREEN}OK${NC}"
else
    echo -e "${RED}CHYBÍ!${NC}"
    echo -e "${YELLOW}-> Modul 'tkinter' není nainstalovaný nebo propojený s Pythonem.${NC}"
    
    if [[ "$OS_TYPE" == "macos" ]]; then
        echo -e "   macOS (Homebrew): ${BLUE}brew install python-tk${NC} (nebo reinstall python)"
    elif [[ "$OS_TYPE" == "linux" ]]; then
        echo -e "   Linux (Ubuntu/Debian): ${BLUE}sudo apt-get install python3-tk${NC}"
        echo -e "   Linux (Fedora): ${BLUE}sudo dnf install python3-tkinter${NC}"
    elif [[ "$OS_TYPE" == "windows" ]]; then
        echo -e "   Windows: Při instalaci Pythonu zaškrtněte 'tcl/tk and IDLE'."
    fi

exit 0