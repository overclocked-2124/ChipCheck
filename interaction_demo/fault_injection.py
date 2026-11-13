"""The hidden fault the search is meant to find. Hard-coded on purpose; the planner never sees this file.

The device under test is a buzzer that should ALWAYS be buzzing. The fault: when the BLUE and GREEN LEDs
are fully on (3.3 V) and the YELLOW LED is between 2.7 V and 3.3 V, the buzzer wrongly goes silent.

Controls are 0-255 PWM duty on a 3.3 V pin, so volts = value / 255 * 3.3.
  led1 = blue, led2 = green, led3 = yellow.
"""
VCC = 3.3
FULL_ON_MIN = 250            # "completely on": 250/255 * 3.3 V = 3.24 V or more (allows for PWM and LED tolerance)
YELLOW_MIN_V, YELLOW_MAX_V = 2.7, 3.3
YELLOW_MIN = 209             # 2.7 V -> duty 208.6, rounded up
YELLOW_MAX = 255


def volts(value):
    return value / 255 * VCC


def buzzer_should_sound(led1, led2, led3):
    """True = the buzzer works (always buzzing). False = the injected fault silences it."""
    in_fault = led1 >= FULL_ON_MIN and led2 >= FULL_ON_MIN and YELLOW_MIN <= led3 <= YELLOW_MAX
    return not in_fault


def describe():
    return (f"fault: blue >= {FULL_ON_MIN} ({volts(FULL_ON_MIN):.2f} V) and green >= {FULL_ON_MIN}, "
            f"yellow {YELLOW_MIN}-{YELLOW_MAX} ({volts(YELLOW_MIN):.2f}-{volts(YELLOW_MAX):.2f} V) -> buzzer silent")


if __name__ == "__main__":
    print(describe())
    size = (256 - FULL_ON_MIN) ** 2 * (YELLOW_MAX - YELLOW_MIN + 1)
    print(f"{size} of {256 ** 3} combinations ({size / 256 ** 3 * 100:.4f}%)")
