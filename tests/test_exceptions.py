"""Smoke tests for the NeoConvError hierarchy."""

from neoconv.core import (
    InvalidConfigurationError,
    InvalidNeoError,
    InvalidRomLayoutError,
    NeoConvError,
    UserCancelledError,
)


def test_neoconv_error_hint_and_code():
    exc = InvalidConfigurationError("bad size", hint="try 2 MB")
    assert exc.code == "invalid_configuration"
    assert str(exc) == "bad size"
    assert exc.hint == "try 2 MB"
    assert isinstance(exc, NeoConvError)


def test_subclass_codes():
    assert InvalidNeoError("x").code == "invalid_neo"
    assert InvalidRomLayoutError("x").code == "rom_layout"
    assert UserCancelledError("x").code == "cancelled"
