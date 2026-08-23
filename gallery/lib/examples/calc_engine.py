# gallery: skip
# SPDX-FileCopyrightText: 2026 Brad Barnett
#
# SPDX-License-Identifier: MIT
"""
`calc_engine`
====================================================

Standalone pocket-calculator arithmetic engine — no display, event, or UI
imports of any kind. Shared by the three UI front ends (``calc_graphics.py``,
``calc_widgets.py``, ``calc_lvgl.py``).

Behaves like a classic four-function pocket calculator, *not* an algebraic
expression evaluator: operators apply immediately against a running
accumulator (chained, left-to-right), rather than honoring operator
precedence. For example ``5 + 3 * 2`` computes ``5 + 3 = 8``, then
``8 * 2 = 16`` — it does *not* evaluate to ``11``.

Usage::

    from calc_engine import CalcEngine

    calc = CalcEngine()
    for key in ("5", "+", "3", "*", "2", "="):
        calc.press(key)
    print(calc.display)     # "16"
    print(calc.expression)  # "8 * 2 ="

Supported keys (passed to :meth:`CalcEngine.press`):
    ``"0"``-``"9"``, ``"."``       -- build the current number
    ``"+"``, ``"-"``, ``"*"``, ``"/"`` -- binary operators
    ``"="``                        -- evaluate (repeatable: repeats last op)
    ``"C"``                        -- clear current entry only
    ``"CE"``                       -- clear everything (a.k.a. "AC")
    ``"BS"``                       -- backspace (delete last typed digit)
    ``"+/-"``                      -- negate the displayed number
    ``"%"``                        -- percent (divide displayed number by 100)
    ``"sqrt"``                     -- square root of the displayed number
"""

MAX_DIGITS = 12
_OP_SYMBOLS = {"+": "+", "-": "-", "*": "x", "/": "/"}


def _compute(a, op, b):
    """Apply one binary operator. Raises ZeroDivisionError on ``a / 0``."""
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise ZeroDivisionError
        return a / b
    raise ValueError("Unknown operator: " + repr(op))


def format_number(value):
    """
    Render a float for the display: strip trailing zeros, cap at
    :data:`MAX_DIGITS` significant digits, and fall back to scientific
    notation when the value is too large, too small, or would not fit.
    """
    if value != value:  # NaN
        return "Error"
    if value in (float("inf"), float("-inf")):
        return "Error"
    if value == 0:
        return "0"

    neg = value < 0
    mag = -value if neg else value

    if mag == int(mag) and mag < 10**MAX_DIGITS:
        text = str(int(mag))
    else:
        int_len = len(str(int(mag))) if mag >= 1 else 1
        decimals = MAX_DIGITS - int_len
        if decimals < 0:
            decimals = 0
        text = ("%.*f" % (decimals, mag)).rstrip("0").rstrip(".")
        if text == "":
            text = "0"

    digit_count = len(text.replace(".", ""))
    too_small = 0 < mag < 1e-6
    if digit_count > MAX_DIGITS or mag >= 10**MAX_DIGITS or too_small:
        text = _to_scientific(mag)

    return "-" + text if neg else text


def _to_scientific(mag):
    sci = "%.6e" % mag
    mantissa, exp = sci.split("e")
    mantissa = mantissa.rstrip("0").rstrip(".")
    exp_val = int(exp)
    sign = "+" if exp_val >= 0 else "-"
    return "%se%s%d" % (mantissa, sign, abs(exp_val))


class CalcEngine:
    """
    Pocket-calculator state machine. No UI dependencies — call :meth:`press`
    with key names and read :attr:`display` / :attr:`expression` /
    :attr:`is_error` to render.
    """

    def __init__(self):
        self._entry = "0"
        self._can_append = False  # True while mid-typing a fresh number
        self._operand_ready = False  # True when entry holds a usable operand
        self._accumulator = None
        self._pending_op = None
        self._last_op = None
        self._last_operand = None
        self._last_was_equals = False
        self._error = False
        self._error_message = ""
        self._expression = ""

    # -- public API ---------------------------------------------------

    def press(self, key):
        """Handle one key press. See module docstring for valid keys."""
        if self._error and key not in ("C", "CE"):
            self._clear_all()

        if key in "0123456789":
            self._digit(key)
        elif key == ".":
            self._digit(".")
        elif key in ("+", "-", "*", "/"):
            self._operator(key)
        elif key == "=":
            self._equals()
        elif key == "C":
            self._clear_entry()
        elif key == "CE":
            self._clear_all()
        elif key == "BS":
            self._backspace()
        elif key == "+/-":
            self._negate()
        elif key == "%":
            self._unary(lambda v: v / 100.0)
        elif key == "sqrt":
            self._unary(self._sqrt)
        else:
            raise ValueError("Unknown key: " + repr(key))

    @property
    def display(self):
        """The main display string (the number currently shown)."""
        if self._error:
            return "Error"
        return self._entry

    @property
    def expression(self):
        """The secondary/history line, e.g. ``"5 + 3 ="``."""
        return self._expression

    @property
    def is_error(self):
        """True when the engine is in an error state (div-by-zero, sqrt<0)."""
        return self._error

    # -- key handlers ---------------------------------------------------

    def _digit(self, d):
        self._last_was_equals = False
        if not self._can_append:
            self._entry = "0"
            self._can_append = True
        if d == ".":
            if "." not in self._entry:
                self._entry += "."
        elif self._entry == "0":
            self._entry = d
        elif self._digit_count(self._entry) < MAX_DIGITS:
            self._entry += d
        self._operand_ready = True

    @staticmethod
    def _digit_count(text):
        return len(text.replace("-", "").replace(".", ""))

    def _operator(self, op):
        value = self._safe_float(self._entry)
        if self._accumulator is None:
            self._accumulator = value
        elif self._operand_ready:
            try:
                self._accumulator = _compute(self._accumulator, self._pending_op, value)
            except ZeroDivisionError:
                self._set_error("Division by zero")
                return
        self._entry = format_number(self._accumulator)
        self._pending_op = op
        self._can_append = False
        self._operand_ready = False
        self._last_was_equals = False
        self._expression = "{} {}".format(format_number(self._accumulator), _OP_SYMBOLS[op])

    def _equals(self):
        if self._pending_op is None:
            self._last_was_equals = True
            return

        value = self._safe_float(self._entry)
        if self._last_was_equals and self._last_operand is not None:
            operand = self._last_operand
        elif self._operand_ready:
            operand = value
        else:
            operand = value

        left = self._accumulator if self._accumulator is not None else 0.0
        try:
            result = _compute(left, self._pending_op, operand)
        except ZeroDivisionError:
            self._set_error("Division by zero")
            return

        self._expression = "{} {} {} =".format(
            format_number(left), _OP_SYMBOLS[self._pending_op], format_number(operand)
        )
        self._last_op = self._pending_op
        self._last_operand = operand
        self._accumulator = result
        self._entry = format_number(result)
        self._can_append = False
        self._operand_ready = False
        self._last_was_equals = True

    def _clear_entry(self):
        self._entry = "0"
        self._can_append = False
        self._operand_ready = False
        self._last_was_equals = False
        self._error = False
        self._error_message = ""

    def _clear_all(self):
        self._entry = "0"
        self._can_append = False
        self._operand_ready = False
        self._accumulator = None
        self._pending_op = None
        self._last_op = None
        self._last_operand = None
        self._last_was_equals = False
        self._error = False
        self._error_message = ""
        self._expression = ""

    def _backspace(self):
        if not self._can_append:
            return
        new_entry = self._entry[:-1]
        if new_entry in ("", "-"):
            new_entry = "0"
            self._can_append = False
            self._operand_ready = False
        self._entry = new_entry
        self._last_was_equals = False

    def _negate(self):
        value = self._safe_float(self._entry)
        if value == 0:
            return
        self._entry = format_number(-value)
        self._operand_ready = True
        self._last_was_equals = False

    def _unary(self, fn):
        value = self._safe_float(self._entry)
        try:
            result = fn(value)
        except ValueError:
            self._set_error("Invalid input")
            return
        self._entry = format_number(result)
        self._can_append = False
        self._operand_ready = True
        self._last_was_equals = False

    @staticmethod
    def _sqrt(value):
        if value < 0:
            raise ValueError("sqrt of negative number")
        return value**0.5

    def _set_error(self, message):
        self._error = True
        self._error_message = message
        self._entry = "0"
        self._can_append = False
        self._operand_ready = False

    @staticmethod
    def _safe_float(text):
        try:
            return float(text)
        except ValueError:
            return 0.0
