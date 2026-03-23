"""Legacy DBD parser entry points.

pywowlib now uses built-in table definitions and no longer parses external
`.dbd` files at runtime.
"""


class build_version_raw:
    def __init__(self, major, minor, patch, build):
        self.major = major
        self.minor = minor
        self.patch = patch
        self.build = build

    def __str__(self):
        return "{}.{}".format(self.version(), self.build)

    def version(self):
        return "{}.{}.{}".format(self.major, self.minor, self.patch)


def _unsupported():
    raise NotImplementedError(
        "\nExternal DBD parsing was removed. pywowlib now uses built-in table definitions only."
    )


def parse_dbd(content):
    _unsupported()


def parse_dbd_file(path):
    _unsupported()


def parse_dbd_directory(path):
    _unsupported()
