"""Normalize the phone formats accepted by the local booking contact form."""

import re


def normalize_phone(value):
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Enter a phone number, for example 0612345678 or +212612345678.")
    number = re.sub(r"[\s().-]", "", value)
    if number.startswith("00"):
        number = "+" + number[2:]
    if re.fullmatch(r"0[0-9]{9}", number):
        number = "+212" + number[1:]
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", number):
        raise ValueError(
            "Use a Moroccan number starting with 0, or an international number starting with +."
        )
    return number


def name_key(value):
    return " ".join(value.split()).casefold()
