import configparser
import os
from pathlib import Path

import appdirs


dirs = appdirs.AppDirs("PIXIE16")
inifile = Path(dirs.user_config_dir) / "config.ini"

config = configparser.ConfigParser()
config.read(inifile)

# set path so that we have pxisys.ini in the directory
current_dir = Path(__file__).parent.parent
os.chdir(current_dir)


def config_get_parameters(section, name):
    """Get the setting out of the config dir.

    Provide better error message if init file does not exist.

    """
    try:
        path = config.get(section, name).replace('"', "")
        path = path.replace("'", "")
        path = Path(path)
    except (configparser.NoOptionError, configparser.NoSectionError):
        path = None
        print()
        print(f"No {name} found in {section}, please add it to {inifile}")
        print(f"   The file should contain something like:")
        print(f"       [{section}]")
        print(f"       {name} = <setting for  {name}>")
        print()
        print("The file should contain the following sections and keys:")
        print("   [Libraries]")
        print("   app = '<path do PixieAppDll.dll>")
        print("   sys = '<path do Pixie16SysDll.dll>")
        print("   [Data]")
        print("   datadir = '<path where the data files should live")
        print("   [Firmware.default]")
        print("   ComFPGAConfigFile = '<path do syspixie16 firmware>")
        print("   SPFPGAConfigFile = '<path do fippixie16 firmware>")
        print("   DSPCodeFile = '<path do Pixie16DSP*.ldr>")
        print("   DSPVarFile = '<path do Pixie16DSP*.var>")
        print()
        # sys.exit()
    return path


lib_app = config_get_parameters("Libraries", "app")
lib_sys = config_get_parameters("Libraries", "sys")

data_dir = config_get_parameters("Data", "datadir")

firmware_com = config_get_parameters("Firmware.default", "ComFPGAConfigFile")
firmware_sp = config_get_parameters("Firmware.default", "SPFPGAConfigFile")
firmware_dsp_code = config_get_parameters("Firmware.default", "DSPCodeFile")
firmware_dsp_var = config_get_parameters("Firmware.default", "DSPVarFile")


# make sure the library directory in the path, so that we can find
# dependencies, otherwise we get a "[WinError 126] The specified
# module could not be found" error
if lib_app:
    os.environ["PATH"] = str(lib_app.parent) + ";" + os.environ["PATH"]
