# Changing settings

The Pixie16 has many settings, some are straight forward, e.g. the
trigger threshold of a channel is just a single number, but other are
more complex, e.g. certain bits in a 32 bit number to set the number
of coincidences.

Pypixie16 provides access to the settings as they are defined in the
manual, but on top of that pypixie16 also provides some shortcuts for
complex settings, so that one can, for example, just set a flag to
`True` or `False` without having to remember which bit needs to
change. This makes setting the correct value easier and it also makes
reading the code that changes settings easier.

To change settings, use the `pixie16.control.change_setting_from_dict`
function.

The function takes a dictionar of settings names and values.

Additonally one needs to define a list of channels for which settings
are defined, so that one does not need to define always all 16 cannel
for each module. Channels are defined as a python tuple of `module`
and `channel`, for example `(0,9)` to address channel 9 in module 0.

Values in the dictionary are set in order as they appear. For this
reason it is recommended to use an `Ordereddict` as the
dictionary. This allows to, for example, set module parameters that
are defined as bit values to `0` and then afterwards settings
individual bits to certain values.

Alternatively, `pixie16.control.load_dsp_parameters_from_file(Path(<filename>))` provides a way to load existing settings.

## Example

Here is an example on how to change settings:

    channels = [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5), (0, 6), (0, 7)]

    settings = OrderedDict(
        {
            "channels": channels,
            "SLOW_FILTER_RANGE": 1,
            "ENERGY_RISETIME": [1, 2, 3, 4, 5, 6, 7],
            "ENERGY_FLATTOP": [1, 2, 3, 4, 5, 6, 7],
            "FAST_FILTER_RANGE": 0,
            "TRIGGER_RISETIME": [1, 2, 3, 4, 5, 6, 7],
            "TRIGGER_FLATTOP": [1, 2, 3, 4, 5, 6, 7],
            "TRIGGER_THRESHOLD": [
                1_000,
                4_000,
                12_000,
                24_000,
                40_000,
                60_000,
                65_534,
            ],  # in ADC units
            "TRACE_LENGTH": [
                1.0,
                1.1,
                1.2,
                1.3,
                1.4,
                1.5,
                1.6,
            ],
            "TRACE_DELAY": [0.2, 0.3, 0.35, 0.4, 0.45, 0.5, 0.550],
            "MultiplicityMaskL": 0,
            "MultiplicityMaskH": 0,
            "ChanCSRa": 0,
            "ChanCSRb": 0,
            "TrigConfig0": 0,
            "TrigConfig1": 0,
            "TrigConfig2": 0,
            "TrigConfig3": 0,
            "ChanTrigStretch": [0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17],
            "VetoStretch": [0.21, 0.22, 0.23, 0.24, 0.25, 0.26, 0.27],
            "FastTrigBackLen": [0.31, 0.32, 0.33, 0.34, 0.35, 0.36, 0.37],
            "ExternDelayLen":  [0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47],
            "ExtTrigStretch":  [0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57],
            "TriggerDelay":    [0.11, 0.22, 0.33, 0.44, 0.55, 0.66, 0.77],
            "VOFFSET": [
                -0.1,
                -0.1,
                -0.15,
                -0.20,
                0.25,
                0.30,
                0.40,
            ],  # in units of 1.5V/32768 with 0V = 32768
            "Gain": [2.5, 0.625, 0.625, 0.625, 2.5, 2.5, 2.5],
            "Polarity": [
                "positive",
                "positive",
                "positive",
                "positive",
                "negative",
                "negative",
                "negative",
            ],
            "CaptureTrace": [False, False, True, True, True, True, False],
            "CaptureSums": [False, True, True, True, True, True, False],
            "RejectPileup": [False, True, True, True, True, True, False],
            "FastTrigSelect": [
                "external",
                "group",
                "group",
                "external",
                "external",
                "group",
                "group",
            ],
            "RejectIfFull": [False, True, True, True, True, True, False],
            "EnableCFD": [False, True, True, True, True, True, False],
            "BLcut": [10, 20, 30, 40, 50, 60, 70],
            "BaselinePercent": [10, 20, 30, 40, 50, 60, 70],
            "Log2Bweight": [1, 2, 3, 4, 5, 6, 7],
            "EnergyLow": [10, 20, 30, 40, 50, 60, 70],
            "Log2Ebin": [1, 2, -3, 1, -2, 3, -1],
            "PreampTau": [0.03, 0.04, 0.50, 0.6, 0.7, 0.8, 0.9],
            "CFDDelay": [10, 20, 30, 40, 50, 60, 70],
            "CFDScale": [1, 2, 3, 1, 2, 3, 1],
            "CFDThresh": [10, 20, 30, 40, 50, 60, 70],
        }
    )
    pixie16.control.change_setting_from_dict(settings, call_pixie=call_pixie)


Notes:
* The dictionary needs a entry called 'channels'
* For settings that have a value for each channel, one can either give a list of values (same length as the number of channels) or a single value that will be used for all channels.
* Most settings names come directly from the programming manual of the pixie16.
* Some settings are custom to pypixie16. These set certain bit values (see below for a list of them)


## Setting up coincidences

One can direclty set `MultiplicityMaskH` and `MultiplicityMaskL`. However, since this involves settings single bits, pypixie16 provides the following settings to make this easier:

### MultiplicityLeft, MultiplicitySelf, MultiplicityRight

A list of channel numbers (no module, just channels) that should be used in the coincidence calculation. Left, Self, and Right refer to the different modules that can be used for this.

### ChannelValidationSource

This can be either 'multiplicity', 'coincidence', or 'group/external'. To distinguish between the three different coincidene modes the Pixie16 provides.

### NrOfMultiplicities

Defines the number of coincidences for mode 'multiplicity'.

### NrOfCoincidencesLeft, NrOfCoincidencesSelf, NrOfCoincidencesRight

Defines the number of coincidene 'coincidence' for each of the 3 modules that are used.

### Example

This set coincidences fo 7 channels:

    "MultiplicitySelf": [
        [4, 5, 9],
        [4, 9],
        [5, 9],
        [4, 5, 9],
        [4, 5, 9],
        [4, 5, 9],
        [4, 5, 9],
    ],
    "NrOfCoincidencesSelf": 2,
    "ChannelValidationSource": "coincidence",

## Bit parameters

For `MODULE_CSRB` the following settings area available:

| Name                 | bit | possible value |
|----------------------|-----|----------------|
| BackplanePullup      | 0   | True/False     |
| Director             | 4   | True/False     |
| ChassisMaster        | 6   | True/False     |
| GlobalFastTrigger    | 7   | True/False     |
| ExternalTrigger      | 8   | True/False     |
| ExternalInhibit      | 10  | True/False     |
| DistributeClocks     | 11  | True/False     |
| SortEvents           | 12  | True/False     |
| ConnectFastTriggerBP | 13  | True/False     |

For `MODULE_CSRA` the following settings area available:

| Name              | bit    | possible value                                                                        |
|-------------------|--------|---------------------------------------------------------------------------------------|
| FastTrigSelect    | 0      | external(=True)/group(=False)                                                         |
| ModValSignal      | 1      | modgate(=True)/global(=False)                                                         |
| GoodChannel       | 2      | True/False                                                                            |
| ChanValSignal     | 3      | channelgate(=True)/channelvalidation(=False)                                          |
| RejectIfFull      | 4      | True/False                                                                            |
| Polarity          | 5      | positive(=True)/negative(=False)                                                      |
| EnableVeto        | 6      | True/False                                                                            |
| CaptureHistogram  | 7      | True/False                                                                            |
| CaptureTrace      | 8      | True/False                                                                            |
| EnableQDC         | 9      | True/False                                                                            |
| EnableCFD         | 10     | True/False                                                                            |
| EnableModVal      | 11     | True/False                                                                            |
| CaptureSums       | 12     | True/False                                                                            |
| EnableChannelVal  | 13     | True/False                                                                            |
| Gain              | 14     | 2.5(=True)/0.625(=False)                                                              |
| RejectPileup      | 15, 16 | single(b15=1, b16=0)/pileup-only(b15=1, b16=1)/pileup(b15=0, b16=1)/all(b15=0, b16=0) |
| SkipLargePulses   | 17     | True/False                                                                            |
| GroupTrigSignal   | 18     | external(=True)/local(=False)                                                         |
| ChannelVetoSignal | 19     | channel(=True)/front(=False)                                                          |
| ModVetoSignal     | 20     | channel(=True)/front(=False)                                                          |
| ExtTimestamps     | 21     | True/False                                                                            |

