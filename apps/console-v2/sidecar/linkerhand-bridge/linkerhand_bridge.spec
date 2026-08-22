"""Reproducible Windows PyInstaller spec for the real LinkerHand SDK bridge.

The SDK root is supplied by ``LINKERHAND_SDK_ROOT`` (or defaults to this
checkout). There are no machine-specific paths in this file; this matters for
checkouts under Chinese or space-containing Windows paths.
"""
from pathlib import Path
import os

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
    "pymodbus",
    "serial",
    "numpy",
]

# LinkerHand is a source checkout rather than an installed wheel, so use an
# explicit data TOC instead of collect_data_files (which intentionally skips
# source-tree modules that are not importable distributions).
datas = [(str(path), "LinkerHand/config") for path in sorted((sdk_package / "config").glob("*.yaml"))]
a = Analysis(
    [str(spec_root / "main.py")],
    # linker_hand_api imports ``core`` and ``utils`` as top-level modules.
    pathex=[str(sdk_root), str(sdk_package), str(spec_root)],
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
