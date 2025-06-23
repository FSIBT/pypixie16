import pytest

import pixie16


def test_setting_bits():
    number = 0
    start_bit = 16
    num_bits = 1
    value = 1
    result = pixie16.control._set_bits(number, start_bit, num_bits, value)
    assert result == 0b1_0000_0000_0000_0000

    number = 0
    start_bit = 2
    num_bits = 3
    value = 7
    result = pixie16.control._set_bits(number, start_bit, num_bits, value)
    assert result == 0b0_0000_0000_0001_1100


def test_masks():
    channels = [3, 4, 9]
    offset = 0

    result = pixie16.control._create_coincidence_masks(channels, offset)
    assert result == 0b0000_0010_0001_1000

    channels = [3, 4, 9]
    offset = 2

    result = pixie16.control._create_coincidence_masks(channels, offset)
    assert result == 0b0000_1000_0110_0000


def test_coincidence():
    settings = {
        "MultiplicitySelf": [4, 5, 9],
        "NrOfCoincidencesSelf": 2,
        "ChannelValidationSource": "coincidence",
    }

    result = pixie16.control._handle_coincidences(settings, 3)

    assert result["MultiplicityMaskL"][0] == 0b0000_0010_0011_0000
    assert len(result["MultiplicityMaskL"]) == 3
    assert result["MultiplicityMaskH"][0] == 0x0080_0000

    assert "MultiplicitySelf" not in settings
    assert "NrOfCoincidencesSelf" not in settings
    assert "ChannelValidationSource" not in settings


def test_expand_values():
    tmp = "a"

    result = pixie16.control._expand_values(tmp, 3)
    assert result == ["a", "a", "a"]

    tmp = 1.1

    result = pixie16.control._expand_values(tmp, 4)
    assert result == [1.1, 1.1, 1.1, 1.1]

    tmp = 42

    result = pixie16.control._expand_values(tmp, 5)
    assert result == [42, 42, 42, 42, 42]


def test_expand_list():
    tmp = []

    result = pixie16.control._expand_list(tmp, 3)
    assert result == [[], [], []]

    tmp = [1, 2, 3]

    result = pixie16.control._expand_list(tmp, 3)
    assert result == [[1, 2, 3], [1, 2, 3], [1, 2, 3]]
