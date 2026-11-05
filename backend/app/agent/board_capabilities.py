"""Chat-only board pin capabilities for wiring decisions.

These are the board modes the simulator actually implements, not guessed board
features. The six-tool compact MCP keeps its raw pin list unchanged.
"""
from __future__ import annotations

_I2C_UNO = {'sda': ['A4', 'A4.2'], 'scl': ['A5', 'A5.2']}
_SPI_UNO = {'sck': ['13'], 'miso': ['12'], 'mosi': ['11'], 'ss': ['10']}

CAPABILITIES = {
    'arduino-uno': {
        'pwm': [3, 5, 6, 9, 10, 11],
        'analog_in': ['A0', 'A1', 'A2', 'A3', 'A4', 'A5'],
        'i2c': _I2C_UNO,
        'spi': _SPI_UNO,
        'uart': {'tx': ['1'], 'rx': ['0']},
    },
    'arduino-nano': {
        'pwm': [3, 5, 6, 9, 10, 11],
        'analog_in': ['A0', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7'],
        'i2c': _I2C_UNO,
        'spi': _SPI_UNO,
        'uart': {'tx': ['1'], 'rx': ['0']},
    },
    'arduino-mega': {
        'pwm': [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 44, 45, 46],
        'analog_in': ['A' + str(index) for index in range(16)],
        'i2c': {'sda': ['20'], 'scl': ['21']},
        'spi': {'sck': ['52'], 'miso': ['50'], 'mosi': ['51'], 'ss': ['53']},
        'uart': {'tx': ['1', '14', '16', '18'], 'rx': ['0', '15', '17', '19']},
    },
}


def capabilities(board_kind):
    value = CAPABILITIES.get(board_kind)
    return {key: (list(item) if isinstance(item, list) else dict(item))
            for key, item in value.items()} if value else None
