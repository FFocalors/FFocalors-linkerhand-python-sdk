"""Reproducible Windows PyInstaller spec for the real LinkerHand SDK bridge.

The SDK root is supplied by ``LINKERHAND_SDK_ROOT`` (or defaults to this
checkout). There are no machine-specific paths in this file; this matters for
checkouts under Chinese or space-containing Windows paths.
"""
from pathlib import Path
import os
import sys

spec_root = Path(SPECPATH).resolve()
repo_root = spec_root.parents[3]
sdk_root = Path(os.environ.get("LINKERHAND_SDK_ROOT", str(repo_root))).expanduser().resolve()
sdk_package = sdk_root / "LinkerHand"
if not sdk_package.is_dir():
    raise SystemExit(
        "LINKERHAND_SDK_ROOT must point to a checkout containing LinkerHand/ "
        f"(not found: {sdk_package})"
    )

# The legacy SDK imports driver modules dynamically from linker_hand_api.py.
# Keep only the SDK package, its YAML settings, and the runtime libraries used
# by those drivers; PyInstaller still prunes unused Python stdlib modules.
hiddenimports = [
    "LinkerHand.linker_hand_api",
    "LinkerHand.utils.mapping",
    "LinkerHand.utils.color_msg",
    "LinkerHand.utils.load_write_yaml",
    "LinkerHand.utils.open_can",
    "core.can.linker_hand_o6_can",
    "core.can.linker_hand_l6_can",
    "core.can.linker_hand_l7_can",
    "core.can.linker_hand_l10_can",
    "core.can.linker_hand_l20_can",
    "core.can.linker_hand_g20_can",
    "core.can.linker_hand_l21_can",
    "core.can.linker_hand_l25_can",
    "core.rs485.linker_hand_o6_rs485",
    "core.rs485.linker_hand_l6_rs485",
    "core.rs485.linker_hand_l7_rs485",
    "core.rs485.linker_hand_l10_rs485",
    "yaml",
    "can",
    # python-can resolves interfaces from entry-point strings at runtime, so
    # PyInstaller cannot discover the Windows USB-CAN backends by imports.
    "can.interfaces.pcan",
    "can.interfaces.pcan.basic",
    "can.interfaces.pcan.pcan",
    "candle.candle_bus",
    "pymodbus",
    "serial",
    "numpy",
    # PyInstaller 6+ ships a `pyi_rth_pkgres` runtime hook that imports
    # `jaraco` via pkg_resources (setuptools >= 68). If these are not declared
    # here, the frozen sidecar crashes immediately with
    # `ModuleNotFoundError: No module named 'jaraco'` before any NDJSON line
    # is written to stdout, and the Tauri runtime reports the transport as
    # "sidecar crashed: stdout closed".
    "pkg_resources",
    "jaraco",
    "jaraco.functools",
    "jaraco.context",
    "jaraco.text",
]

# LinkerHand is a source checkout rather than an installed wheel, so use an
# explicit data TOC instead of collect_data_files (which intentionally skips
# source-tree modules that are not importable distributions).
datas = [(str(path), "LinkerHand/config") for path in sorted((sdk_package / "config").glob("*.yaml"))]

# pyi_rth_pkgres -> pkg_resources -> plistlib -> xml.parsers.expat pulls in
# `pyexpat.pyd`, which depends on the conda-supplied `expat.dll` living in
# `<env>/Library/bin/` (not under `DLLs/`). PyInstaller's analysis can't
# resolve it there, so the frozen exe crashes at startup with
# "DLL load failed while importing pyexpat: 找不到指定的模块". Bundle it
# explicitly so the sidecar can import stdlib `plistlib` / `xml.parsers.expat`.
_py_dir = Path(sys.executable).parent
_expat_candidates = [
    _py_dir / "DLLs" / "expat.dll",
    # Conda Python puts third-party C library DLLs under
    # `<env>/Library/bin/`, not under `DLLs/` (that's stdlib only).
    _py_dir / "Library" / "bin" / "expat.dll",
]
_expat_binaries = [(str(p), ".") for p in _expat_candidates if p.is_file()]

a = Analysis(
    [str(spec_root / "main.py")],
    # linker_hand_api imports ``core`` and ``utils`` as top-level modules.
    pathex=[str(sdk_root), str(sdk_package), str(spec_root)],
    binaries=_expat_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["IPython", "matplotlib", "mediapipe", "PyQt5", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="linkerhand-sidecar",
    console=True,
)
