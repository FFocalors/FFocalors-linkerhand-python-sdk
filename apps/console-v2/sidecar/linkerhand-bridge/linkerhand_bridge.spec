# PyInstaller boundary skeleton. The real SDK is supplied with --sdk-root in development.
from PyInstaller.utils.hooks import collect_data_files

sdk_root = r"PATH_TO_LINKERHAND_SDK"
a = Analysis(
    ["main.py"],
    pathex=[sdk_root],
    datas=collect_data_files("LinkerHand"),
    hiddenimports=["LinkerHand.linker_hand_api"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="linkerhand-sidecar", console=True)
