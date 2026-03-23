`pycasc` is a WoW-focused Python port of the local-storage path from `CASCExplorer/CascLib`.

Current scope:
- Load local WoW CASC storage
- Parse `.build.info`, build config, CDN index files, local idx files
- Load encoding and WoW root tables
- Open files by file data id or encoding key
- Resolve `DBFilesClient\*.db2` / `DBFilesClient\*.dbc` through `WoWDBDefs` file data ids
- Decode BLTE blocks including Salsa20-encrypted payloads
- Parse modern WoW `TSFM` root files and legacy pre-8.2 root files
- Parse raw `vfs-root` manifests and child TVFS metadata from modern WoW builds
- Load extra WoW TACT keys from wowdev `TACTKeys/WoW.txt`

Current limits:
- Online CDN mode is not implemented
- Non-WoW root handlers are not ported
- Listfile and storage tree APIs are not ported
- Full retail path resolution for arbitrary files is still incomplete
- Some encrypted files still require keys that are not present in public key lists

Minimal example:

```python
from pycasc import CASCHandler

handler = CASCHandler.open_local_storage(r"E:\myGames\World of Warcraft")
with handler.open_file_by_name(r"DBFilesClient\Map.dbc") as stream:
    print(stream.read(8).hex())
```
