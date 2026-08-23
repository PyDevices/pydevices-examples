# SPDX-FileCopyrightText: 2024 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
A class to make keypad keys appear as pins on a microcontroller.

Usage:
    import board_config
    import appdev
    import keys
    from keypins import KeyPins

    app = appdev.App(board_config)
    buttons = KeyPins(
        left=keys.K_LEFT,
        right=keys.K_RIGHT,
        go=keys.K_UP,
        stop=keys.K_DOWN,
        fire=keys.K_SPACE,
    )

    app.on([app.events.KEYDOWN, app.events.KEYUP], buttons)

    while True:
        _ = app.poll()
        for button in buttons:
            if button.value() == True:
                print(f"{button.name} ({button.keyname}) pressed")
"""

import events
import keys


class KeyPins:
    def __init__(self, **kwargs):
        self._keypins = kwargs
        self._objects = {}
        for name, key in kwargs.items():
            setattr(self, name, _KeyPin(name, key))
            self._objects[name] = getattr(self, name)

    def __call__(self, event):
        if event.key in self._keypins.values():
            button = next(name for name, key in self._keypins.items() if key == event.key)
            if event.type == events.KEYDOWN:
                getattr(self, button).value(True)
            elif event.type == events.KEYUP:
                getattr(self, button).value(False)

    def __getitem__(self, name):
        return getattr(self, name)

    def __iter__(self):
        return iter(self._objects.values())

    def __len__(self):
        return len(self._keypins)

    def __repr__(self):
        return repr(self._objects)

    def __str__(self):
        return str(self._keypins)


class _KeyPin:
    def __init__(self, name, key):
        self.name = name
        self.key = key
        self._value = False

    def __call__(self, value=None):
        return self.value(value)

    def value(self, value=None):
        if value is not None:
            self._value = value
            # print(f'setting {self.name} = {self._value}')
        return self._value

    @property
    def keyname(self):
        return keys.keyname(self.key)
