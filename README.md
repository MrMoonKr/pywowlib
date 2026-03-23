# pywowlib
[![Build Status](https://travis-ci.org/WowDevTools/pywowlib.svg?branch=master)](https://travis-ci.org/WowDevTools/pywowlib)

**pywowlib** is a Python 3.5+ libary featuring the functionality of reading and writing various World of Warcraft related file formats.
The current codebase targets `WOD+` clients and uses vendored `pycasc` for game data access.
Pre-`WOD` `MPQ` support has been removed.

# Supported formats

| Format | Description  | 1.12.1 | 2.4.3 | 3.3.5a | 4.3.4 | 5.4.8 | 6.2.4 | 7.3.5 | 8.3.5 | 9.0.0 | Comment
|--|--|--|--|--|--|--|--|--|--|--|--|
| M2 | Model | % |  % |  ??|  ??|  ??|  ??|  ??| ??| % | Possibly not handling some changes brought with Shadowlands. Missing names for some key bones.
| Skin | M2 Lod File | DNE |  DNE |  ??|  ??|  ??|  ??|  ??| ??| % | Shadowlands mesh part IDs are not yet mapped. 
| Anim | M2 Low Priority Animation Sequence | DNE |  DNE |  ??|  ??|  ??|  ??|  ??| ??| ??| 
| Skel | M2 Skeleton Data | DNE |  DNE |  DNE |  DNE |  DNE |  DNE |  ??| ??| ??| 
| Phys | M2 Physics | DNE |  DNE |  DNE |  DNE |  TBI |  TBI |  TBI | TBI | TBI | 
| Bone | M2 FacePose Transform Data | DNE |  DNE |  DNE |  DNE |  DNE |  TBI |  TBI | TBI | TBI |
| WMO | World Map Object | ??|  ??|  ??|  ??|  ??|  ??|  ??| ??| ??| Some changes need to be added to reflect WotLK+ changes.
| ADT | Terrain Tile | % |  % |  ??|  TBI |  TBI |  TBI |  TBI | TBI | TBI | By this category, _tex.adt and other additional ADT-related files are implied as well. Support for WotLK was never tested. Likely to be broken and thus reimplemented later.
| WDT | World Terrain Layout | TBI |  TBI |  TBI |  TBI |  TBI |  TBI |  TBI | TBI | TBI |
| WDL | Low Res Terrain | TBI |  TBI |  TBI |  TBI |  TBI |  TBI |  TBI | TBI | TBI |
| MPQ | Mike O'Brien Pack | DNE |  DNE |  DNE |  DNE |  DNE |  DNE |  DNE | DNE | DNE | Removed. Pre-WOD clients are no longer supported.
| CASC | Content Adressable Storage Container | DNE |  DNE |  DNE |  DNE |  DNE | ??| ??| ??| ??| Implemented via vendored `pycasc`. Read-only.
| BLP | Images | ??|  ??|  ??|  ??|  ??| ??| ??| ??| ??| Read-only. Supporting conversion to PNG.
| DBC/DB2 | Client Database Files | ??|  ??|  ??|  TBI |  TBI | TBI | TBI | TBI | TBI | Read/Write support is planned.

# Contribution
Feel free to contribute to the library development by either making a pull request or contacting Skarn directly to gain write access.

# Use
The library comes under MIT license, so feel free to utilize it anywhere you want under MIT license terms.

# Legal note
World of Warcraft is a registered trademark of Blizzard Entertainment and/or other respective owners.
This software is not created by Blizzard Entertainment or its affiliates, and is for purely educational and research purposes.
This software is not intended for the use and production of cheating (hacking) software or modificaitons that can disrupt World of Warcraft's gameplay.
It is your sole responsibility to follow copyright law, game's ToS and EULA. 
The creators hold no responsibility for the consequences of use of this software.
