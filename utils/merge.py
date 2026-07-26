"""
Единая реализация рекурсивного слияния словарей настроек.

Раньше копий было две — в utils/accounts.py и utils/settings_store.py —
и они разъехались: одна пропускала пустые строки (`v != ""`), другая нет.
Из-за этого пустое поле «прокси» в дашборде никогда не сохранялось:
API отвечал {"ok": true}, а мёртвый прокси оставался в файле.
"""


def deep_merge(base: dict, override: dict) -> dict:
    """
    Рекурсивно накладывает override на base. Аргументы не мутируются.

    Правила:
      - вложенные словари сливаются рекурсивно;
      - None означает «не трогать» (поле не передали) и пропускается;
      - пустая строка/список/0/False — обычные значения, они ЗАПИСЫВАЮТСЯ.
        Именно так поле можно очистить из интерфейса.
    """
    result = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        elif v is not None:
            result[k] = v
    return result
