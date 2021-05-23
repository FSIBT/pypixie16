"""Classes for each field inside a setings file.

These contain helper functions to, for example, combine the HI and LO values of timestamps.
"""

import abc
from typing import Tuple


class NotImplementedAttr:
    """An 'abstract attribute' class that allows for initialization for an owner instance but not access to this
    attribute"""

    def __init__(self, err_msg):
        self.err_msg = err_msg

    def __get__(self, instance, owner):
        raise NotImplementedError(self.err_msg)


class SettingsFieldBase(abc.ABC):
    """A descriptor base class that will get derived settings values according to some logic. Said logic should be
    defined in a subclass's implementation of derive_field_value"""

    name = NotImplementedAttr(
        "A SettingsFieldBase instance can only be defined as an attribute in a subclass of Entity"
    )

    @property
    def storage_names(self) -> Tuple[str]:
        """Name of the raw settings file field(s) used to store the value of this derived field. Default is set to the
        name of this field."""
        return (self.name,)

    def get_storage_values(self, instance):
        """Utility function to grab the values of the storage fields zipped together."""
        storage_values = []
        for sn in self.storage_names:
            # If the storage name is the name of this field, grab the value with dict syntax to avoid infinite recursion
            if sn == self.name:
                sv = instance.__dict__[sn]
            # If not, use getattr so that we can also grab derived fields (whose values are not directly stored in
            # __dict__)
            else:
                sv = getattr(instance, sn)
            try:
                if isinstance(sv, str):
                    raise NotImplementedError(
                        "Did not expect any settings to be saved as string"
                    )
                sv = list(sv)
            except TypeError:
                sv = [sv]
            storage_values.append(sv)
        return zip(*storage_values)

    @abc.abstractmethod
    def derive_field_value(self, instance, *storage_values):
        """An abstract method that should implement the logic to derive the value of this field from the raw settings
        file values."""

    def __get__(self, instance, owner):
        """Get the value of this field. All the logic for how to combine raw settings values is left to
        derive_field_values"""
        storage_values = self.get_storage_values(instance)
        res = tuple(self.derive_field_value(instance, *v) for v in storage_values)
        if len(res) == 1:
            return res[0]
        else:
            return res

    def __set__(self, instance, value):
        """By default SettingsFields are not settable."""
        raise AttributeError("The set method is not defined for this attribute")


class EntityMeta(type):
    """Metaclass for settings class. Assigns the name of the variable that holds the instances of SettingsFieldBase,
    call one such instance s, to s.name. E.g. if apple = SettingFieldSubclass() were defined in an EntityMeta class then
    apple.name would be 'apple'. Adapted from the Fluent Python book"""

    def __init__(cls, name, bases, attr_dict):
        super().__init__(name, bases, attr_dict)
        for key, attr in attr_dict.items():
            if isinstance(attr, SettingsFieldBase):
                attr.name = key


class Entity(metaclass=EntityMeta):
    """Entity with settings fields"""


# ----------------------------------------------------------------------------------------------------------------------


def combine_hi_lo_registers(hi, lo):
    return hi * 2 ** 32 + lo


class ABField(SettingsFieldBase):
    """A SettingsField to derives fields separated into hi lo 32 bit register subfields. Referred to as 'AB' classes
    because such fields are named 'FastPeaksA' and 'FastPeaksB' for example."""

    @property
    def storage_names(self) -> Tuple[str]:
        return self.name + "A", self.name + "B"

    def derive_field_value(self, instance, *storage_values):
        A, B = storage_values
        return combine_hi_lo_registers(A, B)


def int_to_bits(i, bits_length):
    """Converts int values to binary (in the form of a tuple of 0's and 1's)"""
    bit_fmt = f"{{:0{bits_length}b}}"
    return tuple(int(j) for j in bit_fmt.format(i))


BIT_FIELD_SIZE_TBL = {
    "MultiplicityMaskL": 32,
    "MultiplicityMaskH": 32,
    "FastTrigBackplaneEna": 32,
    "TrigConfig": 32,
    "ChanCSRa": 22,
    "ChanCSRb": 22,
    "ModCSRA": 14,
    "ModCSRB": 14,
}


class BinaryField(SettingsFieldBase):
    """A SettingsField to derive values that are meant to be interpreted as binary digits but are stored as ints"""

    def derive_field_value(self, instance, *storage_values):
        (int_value,) = storage_values
        bits_length = BIT_FIELD_SIZE_TBL[self.name]
        return int_to_bits(int_value, bits_length)


def calc_trace_delay(paf_length, trigger_delay):
    return paf_length - trigger_delay


class TraceDelayField(SettingsFieldBase):
    """A SettingsField to derive trace delay"""

    storage_names = ("PAFlength", "TriggerDelay")

    def derive_field_value(self, instance, *storage_values):
        paf_length, trigger_delay = storage_values
        return calc_trace_delay(paf_length, trigger_delay)


def calc_offset_voltage(offset_dac):
    return 1.5 * ((32768 - offset_dac) / 32768)


class OffsetVoltageField(SettingsFieldBase):
    """A SettingsField to derive offset voltage"""

    storage_names = ("OffsetDAC",)

    def derive_field_value(self, instance, *storage_values):
        (offset_dac,) = storage_values
        return calc_offset_voltage(offset_dac)
