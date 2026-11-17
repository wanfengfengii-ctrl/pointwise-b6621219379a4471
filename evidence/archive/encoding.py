from fractions import Fraction
import re


_INTEGER = re.compile(r"0|-?[1-9][0-9]*")


def encode_fraction(value):
    if not isinstance(value, Fraction):
        raise ValueError("expected Fraction")
    return [str(value.numerator), str(value.denominator)]


def decode_fraction(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("invalid rational encoding")
    if any(not isinstance(part, str) or not _INTEGER.fullmatch(part) for part in value):
        raise ValueError("noncanonical integer encoding")
    numerator, denominator = map(int, value)
    if denominator <= 0:
        raise ValueError("nonpositive denominator")
    result = Fraction(numerator, denominator)
    if encode_fraction(result) != list(value):
        raise ValueError("noncanonical rational encoding")
    return result
