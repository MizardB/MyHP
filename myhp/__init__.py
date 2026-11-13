"""Package entry point and exports for myhp."""

from myhp.protocol import PrimeCommand, PrimeInfo
from myhp.usb import HP_PRIME_PIDS, HP_VENDOR_ID, PrimeDevice, PrimeDeviceDescriptor, find_prime_devices

__all__ = [
    "HP_VENDOR_ID",
    "HP_PRIME_PIDS",
    "PrimeCommand",
    "PrimeInfo",
    "PrimeDevice",
    "PrimeDeviceDescriptor",
    "find_prime_devices",
]
