"""Facility-local CSV pronunciations, applied only to speech input."""
import csv
import re


class ReadingDictionaryError(ValueError):
    pass


def apply_readings(text, path):
    if not path.exists():
        return text
    if path.stat().st_size > 200000:
        raise ReadingDictionaryError('読み辞書は200KB以内にしてください。')
    words = {}
    try:
        with path.open(encoding='utf-8-sig', newline='') as file:
            rows = csv.DictReader(file)
            if rows.fieldnames != ['表記', '読み']:
                raise ReadingDictionaryError('読み辞書の先頭行は「表記,読み」にしてください。')
            for line, row in enumerate(rows, 2):
                surface, reading = row.get('表記', ''), row.get('読み', '')
                if not isinstance(surface, str) or not isinstance(reading, str) or None in row:
                    raise ReadingDictionaryError(f'読み辞書の{line}行目の列数を確認してください。')
                surface, reading = surface.strip(), reading.strip()
                if not surface and not reading:
                    continue
                if not surface or not reading or len(surface) > 80 or len(reading) > 160:
                    raise ReadingDictionaryError(f'読み辞書の{line}行目の表記・読みを確認してください。')
                if surface.casefold() in words:
                    raise ReadingDictionaryError(f'読み辞書の{line}行目に重複した表記があります。')
                words[surface.casefold()] = (surface, reading)
                if len(words) > 500:
                    raise ReadingDictionaryError('読み辞書は500語以内にしてください。')
    except (UnicodeError, csv.Error) as error:
        raise ReadingDictionaryError('読み辞書をUTF-8のCSVで保存してください。') from error
    if not words:
        return text
    alternatives = []
    for surface, _ in sorted(words.values(), key=lambda item: -len(item[0])):
        before = r'(?<![A-Za-z0-9_])' if surface[0].isascii() and surface[0].isalnum() else ''
        after = r'(?![A-Za-z0-9_])' if surface[-1].isascii() and surface[-1].isalnum() else ''
        alternatives.append(before + re.escape(surface) + after)
    # Single pass: replacement readings never trigger other dictionary entries.
    return re.sub('|'.join(alternatives), lambda match: words[match.group().casefold()][1], text, flags=re.IGNORECASE)
