import re
import os
import glob

def run_add_nbsp_logic(target_dir, logger):
    """Analyzuje a upraví JSON soubory pro přidání nezalomitelných mezer."""
    NBSP_CHAR = '\u00A0'
    NBSP_ESCAPE_STRING = r'\\u00A0'
    LANGUAGE_WORDS = {
        "cs": ["a", "i", "k", "o", "s", "u", "v", "z"],
        "sk": ["a", "i", "k", "o", "s", "u", "v", "z"],
        "en": ["a", "I"], "de": ["o", "a"]
    }

    def get_language_from_filename(filename):
        match = re.search(r'(cs|en|de|sk)', os.path.basename(filename), re.IGNORECASE)
        return match.group(1).lower() if match else None

    def build_regex_pattern(words):
        escaped_words = [re.escape(word) for word in words]
        pattern = r'(?<!\S)(' + '|'.join(escaped_words) + r')\s'
        return re.compile(pattern, re.IGNORECASE)

    def process_json_text(text, regex):
        line_regex = re.compile(r'^(\s*".*?"\s*:\s*")(.*?)(",?\s*)$', re.MULTILINE)
        def replace_in_line(match):
            prefix, value, suffix = match.groups()
            if '\n' in value or NBSP_CHAR in value or NBSP_ESCAPE_STRING in value:
                return match.group(0)
            new_value = regex.sub(r'\1' + NBSP_ESCAPE_STRING, value)
            return prefix + new_value + suffix
        return line_regex.sub(replace_in_line, text)

    search_pattern = os.path.join(target_dir, "*.json")
    json_files = glob.glob(search_pattern)
    processed_count = 0
    logger.info(f"Hledání JSON souborů v: {target_dir}\n")
    if not json_files:
        logger.warn("Nenalezeny žádné JSON soubory. Zkontrolujte cestu.\n")
        return

    for filename in json_files:
        lang = get_language_from_filename(filename)
        if lang in LANGUAGE_WORDS:
            words = LANGUAGE_WORDS[lang]
            regex_for_words = build_regex_pattern(words)
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    raw_text = f.read()
                processed_text = process_json_text(raw_text, regex_for_words)
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(processed_text)
                logger.success(f"✅ Zpracováno: '{filename}' (Jazyk: {lang.upper()})\n")
                processed_count += 1
            except Exception as e:
                logger.error(f"❌ CHYBA při zpracování '{filename}': {e}. Přeskočeno.\n")
        else:
            logger.warn(f"⚠️ Přeskočeno: '{os.path.basename(filename)}'. Nebyl detekován podporovaný jazyk.\n")

    if processed_count > 0:
        logger.success(f"\n✨ Celkem {processed_count} souborů bylo upraveno.\n")
    else:
        logger.info("\nŽádné soubory nebyly upraveny.\n")