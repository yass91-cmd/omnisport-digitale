import pytest

from backend.app.contact import normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("06 12 34 56 78", "+212612345678"),
        ("(+212) 612-345-678", "+212612345678"),
        ("00212612345678", "+212612345678"),
        ("+33123456789", "+33123456789"),
        (None, None),
        ("", None),
    ],
)
def test_contact_phone_formats(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw", ["bad", "123", "+00000000000", "+212612345678ext4", True, "+" + "1" * 16]
)
def test_invalid_phone_cannot_be_silently_accepted(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)
