import abc
from typing import Tuple


class NotImplementedAttr:

    def __init__(self, err_msg):
        self.err_msg = err_msg

    def __get__(self, instance, owner):
        raise NotImplementedError(self.err_msg)


class SettingsFieldBase:
    name = NotImplementedAttr(
        'A SettingsFieldBase instance can only be defined as an attribute in a subclass of Entity'
    )

    @property
    def storage_names(self) -> Tuple[str]:
        return self.name,

    def get_storage_values(self, instance):
        storage_values = []
        for sn in self.storage_names:
            if sn == self.name:
                sv = instance.__dict__[sn]
            else:
                sv = getattr(instance, sn)
            storage_values.append(sv)
        return zip(storage_values)

    @abc.abstractmethod
    def derive_field_value(self, instance, *storage_values):
        pass

    def __get__(self, instance, owner):
        storage_values = self.get_storage_values(instance)
        return tuple(self.derive_field_value(instance, *v) for v in storage_values)


class EntityMeta(type):
    """Metaclass for settings class. Adapted from the Fluent Python book"""

    def __init__(cls, name, bases, attr_dict):
        super().__init__(name, bases, attr_dict)
        for key, attr in attr_dict.items():
            if isinstance(attr, SettingsFieldBase):
                attr.name = key


class Entity(metaclass=EntityMeta):
    """Entity with settings fields"""


# ----------------------------------------------------------------------------------------------------------------------


def combine_hi_lo_registers(hi, lo):
    return hi*2**32 + lo


class ABField(SettingsFieldBase):

    @property
    def storage_names(self) -> Tuple[str]:
        return self.name + 'A', self.name + 'B'

    def derive_field_value(self, instance, *storage_values):
        A, B = storage_values
        return combine_hi_lo_registers(A, B)


def int_to_bits(i, bits_length):
    """Converts int values to binary (in the form of a tuple of 0's and 1's)"""
    bit_fmt = '{' + ':0' + bits_length + '}'
    return tuple(int(j) for j in bit_fmt.format(i))


BIT_FIELD_SIZE_TBL = {
    'MultiplicityMaskL': 32,
    'MultiplicityMaskH': 32,
    'FastTrigBackplaneEna': 32,
    'TrigConfig': 32,
    'ChanCSRa': 22,
    'ChanCSRb': 22,
    'ModCSRA': 14,
    'ModCSRB': 14
}


class BinaryField(SettingsFieldBase):

    def derive_field_value(self, instance, *storage_values):
        int_value, = storage_values
        bits_length = BIT_FIELD_SIZE_TBL[self.name]
        return int_to_bits(int_value, bits_length)


def calc_trace_delay(paf_length, trigger_delay):
    return paf_length - trigger_delay


class TraceDelayField(SettingsFieldBase):

    storage_names = ('PAFlength', 'TriggerDelay')

    def derive_field_value(self, instance, *storage_values):
        paf_length, trigger_delay = storage_values
        return calc_trace_delay(paf_length, trigger_delay)


def calc_offset_voltage(offset_dac):
    return 1.5 * ((32768 - offset_dac)/32768)


class OffsetVoltageField(SettingsFieldBase):

    storage_names = ('OffsetDAC',)

    def derive_field_value(self, instance, *storage_values):
        offset_dac, = storage_values
        return calc_offset_voltage(offset_dac)
