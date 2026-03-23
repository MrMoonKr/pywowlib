from collections import OrderedDict

from . import wotlk


def _collect_tables(module):
    return {
        name: value
        for name, value in vars(module).items()
        if isinstance(value, OrderedDict)
    }


BUILTIN_DEFINITIONS = {
    "3.3.5.12340": _collect_tables(wotlk),
}


def get_builtin_definition(name, build):
    build_tables = BUILTIN_DEFINITIONS.get(build)
    if not build_tables:
        return None

    return build_tables.get(name)
