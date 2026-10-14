# src/logic/env_file.py
"""
Zápis hodnot do adt_tools_config.env projektu z UI (nastavení projektu, které patří do gitu a platí
pro všechny, kdo projekt buildí). Komentáře, pořadí a ostatní řádky zůstanou.
"""
import os
import re

from ..constants import ADT_PROJECT_CONFIG_FILENAME


def set_env_values(values, filepath=ADT_PROJECT_CONFIG_FILENAME):
    """
    Zapíše {klíč: hodnota}. Aktivní řádek klíče přepíše, zakomentovaný vzor (# KLÍČ=…) odkomentuje
    a přepíše, jinak řádek přidá na konec. Hodnota None klíč zakomentuje (vrátí výchozí chování).
    """
    lines = []
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.read().splitlines()

    for key, value in values.items():
        active = re.compile(rf'^\s*{re.escape(key)}\s*=')
        commented = re.compile(rf'^\s*#\s*{re.escape(key)}\s*=')
        new_line = f"{key}={_quote(value)}" if value is not None else None

        index = next((i for i, line in enumerate(lines) if active.match(line)), None)
        if index is not None:
            if new_line is None:
                lines[index] = f"# {lines[index].lstrip()}"
            else:
                lines[index] = new_line
            continue

        if new_line is None:
            continue

        index = next((i for i, line in enumerate(lines) if commented.match(line)), None)
        if index is not None:
            lines[index] = new_line
        else:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(new_line)

    with open(filepath, 'w', encoding='utf-8', newline='\n') as f:
        f.write("\n".join(lines) + "\n")


def _quote(value):
    """Uvozovky jen tam, kde by hodnota bez nich nešla přečíst (mezera, #)."""
    value = str(value)
    return f'"{value}"' if re.search(r'[\s#"]', value) else value
