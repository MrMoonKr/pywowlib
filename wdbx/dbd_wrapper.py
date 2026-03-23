from collections import OrderedDict
from .definitions import get_builtin_definition
from .types import DBCString, DBCLangString
from ..io_utils import types


type_map = {
    'int': lambda entry: getattr(types, "{}{}{}".format(
        'u' if entry.is_unsigned else '', 'int', entry.int_width)),
    'float': lambda x: types.float32,
    'string': lambda x: DBCString,
    'locstring': lambda x: DBCLangString

}


class DBDefinition:
    def __init__(self, name, build):
        self.name = name
        self.build = build
        builtin_definition = get_builtin_definition(name, build)
        if builtin_definition is not None:
            self.definition = OrderedDict(builtin_definition)
            return

        raise NotImplementedError(
            '\nNo built-in definition found for table "{}" for build "{}"'.format(name, build)
        )

    def __getitem__(self, item):
        return self.definition[item]

    def keys(self):
        return self.definition.keys()

    def items(self):
        return self.definition.items()

    def values(self):
        return self.definition.values()





