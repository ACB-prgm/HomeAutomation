from .handler import Handler
from .clock import Clock

TimerReminder, Wheather, SmartHome, Bluetooth = Handler,Handler,Handler,Handler

__all__ = [
    "Handler",
    "Clock",
    "TimerReminder",
    "Wheather", 
    "SmartHome", 
    "Bluetooth"
]