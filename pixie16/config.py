"""Functions to load settings from a config file."""

import configparser
import os
from pathlib import Path
import sys
from typing import List, Union

import appdirs


dirs = appdirs.AppDirs("PIXIE16")
inifile = Path(dirs.user_config_dir) / "config.ini"

config = configparser.ConfigParser()
config.read(inifile)


def config_get_parameters(
    section: str, name: str, verbose: bool = True
) -> Union[None, Path]:
    """Get the setting out of the config dir.

    Provide better error message if init file does not exist.

    """
    try:
        path_str = config.get(section, name).replace('"', "")
        path_str = path_str.replace("'", "")
        path = Path(path_str)
    except (configparser.NoOptionError, configparser.NoSectionError):
        path = None
        if verbose:
            print()
            print(f"No {name} found in {section}, please add it to {inifile}")
            print("   The file should contain something like:")
            print(f"       [{section}]")
            print(f"       {name} = <setting for {name}>")
            print()
            print("The file should contain the following sections and keys:")
            print("   [Libraries]")
            print("   sdk = <path to Pixie16Api.dll>")
            print("   [Data]")
            print("   datadir = <path where the data files should live>")
            print("   [Firmware.default]")
            print("   ComFPGAConfigFile = <path to syspixie16 firmware>")
            print("   SPFPGAConfigFile = <path to fippixie16 firmware>")
            print("   DSPCodeFile = <path to Pixie16DSP*.ldr>")
            print("   DSPVarFile = <path to Pixie16DSP*.var>")
            print("   SettingFile = <path to default setting file>")
            print()
    return path


def load_config(section_name: str) -> List[Path]:
    """Load firmware, etc setting that are defined in a section of the config file.

    Sections are defined with 'Firmware.<sectionname>'.
    """
    section = f"Firmware.{section_name}"
    if section not in config.sections():
        print("Error: cannot find section {section} in the config file {inifile}")
        sys.exit(1)
    # load new path to firmware
    firmware_com = config_get_parameters(section, "ComFPGAConfigFile")
    firmware_sp = config_get_parameters(section, "SPFPGAConfigFile")
    firmware_dsp_code = config_get_parameters(section, "DSPCodeFile")
    firmware_dsp_var = config_get_parameters(section, "DSPVarFile")
    setting_file = config_get_parameters(section, "SettingFile")

    return [
        firmware_com,
        firmware_sp,
        firmware_dsp_code,
        firmware_dsp_var,
        setting_file,
    ]


def list_firmware() -> None:
    """List all firmwars defined in the config file."""
    print(f"The config file used is: {inifile}")
    print("The following firmware definitions exists")
    names = []
    for section in config.sections():
        if not section.startswith("Firmware."):
            continue
        print(f"{section}")
        names.append(section[9:])
        for key in config[section].keys():
            print(f"   {key} = {config[section][key]}")
    print(
        f'Use only the name after the "." for the name of'
        f' the firmware: {", ".join(names)}'
    )


def get_sdk():
    sdk = config_get_parameters("Libraries", "sdk")

    # make sure the library directory in the path, so that we can find
    # dependencies, otherwise we get a "[WinError 126] The specified
    # module could not be found" error
    if sdk:
        os.environ["PATH"] = str(sdk.parent) + ";" + os.environ["PATH"]

    return str(sdk)
