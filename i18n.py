from typing import Dict

DEFAULT_LANG = "ru"

I18N: Dict[str, Dict[str, str]] = {
    # RU, TH, EN bundles are copied at runtime by the main file; for brevity keep minimal here
}


def set_bundles(bundles: Dict[str, Dict[str, str]], default_lang: str = "ru") -> None:
    global I18N, DEFAULT_LANG
    I18N = bundles
    DEFAULT_LANG = default_lang


def t(user_lang: str, key: str, **kwargs):
    lang = (user_lang or DEFAULT_LANG).lower()
    bundle = I18N.get(lang) or I18N[DEFAULT_LANG]
    txt = bundle.get(key) or I18N[DEFAULT_LANG].get(key, key)
    try:
        return txt.format(**kwargs)
    except Exception:
        return txt
