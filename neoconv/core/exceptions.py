"""Typed errors for expected neoconv failures (CLI, GUI, and library callers)."""

from __future__ import annotations


class NeoConvError(Exception):
    """
    Base class for expected, user-facing neoconv failures.

    Subclasses set :attr:`code` for stable identification (CLI, GUI, JSON).
    Optional :attr:`hint` adds a short remediation line without parsing ``str(e)``.
    """

    code: str = "neoconv_error"

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class InvalidNeoError(NeoConvError):
    """``.neo`` container is missing, truncated, or inconsistent."""

    code = "invalid_neo"


class InvalidRomLayoutError(NeoConvError):
    """MAME ROM set layout or naming does not match what pack expects."""

    code = "rom_layout"


class InvalidConfigurationError(NeoConvError):
    """Operation parameters are invalid (extract chip/bank size, P-ROM swap rules)."""

    code = "invalid_configuration"


class UserCancelledError(NeoConvError):
    """GUI or worker operation was cancelled by the user."""

    code = "cancelled"
