"""ISO country identities with CLDR Chinese/English display names and known aliases."""
import unicodedata

from babel import Locale
from babel.core import get_global
import pycountry


def _key(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).replace('’', "'").replace('&', 'and').casefold().split())


_ISO = {}
for country in pycountry.countries:
    for attribute in ('alpha_2', 'alpha_3', 'name', 'official_name', 'common_name'):
        value = getattr(country, attribute, None)
        if value:
            _ISO[_key(value)] = country.alpha_2
for locale in ('en', 'zh_Hans', 'zh_Hant'):
    for code, name in Locale.parse(locale).territories.items():
        if code.casefold() in _ISO:
            _ISO[_key(name)] = code
for alias, targets in get_global('territory_aliases').items():
    if len(targets) == 1 and targets[0].casefold() in _ISO:
        _ISO[_key(alias)] = targets[0]
_ISO.update({_key(name): code for name, code in {
    'UK': 'GB', 'USA': 'US', 'UAE': 'AE', 'England': 'GB', 'Korea': 'KR',
    'Ivory Coast': 'CI', '中国香港': 'HK', '香港': 'HK', '中国台湾': 'TW',
    '台湾': 'TW', '中国澳门': 'MO', '澳门': 'MO', '俄罗斯': 'RU', '韩国': 'KR',
}.items()})


def country_code(value):
    return _ISO.get(_key(value))
