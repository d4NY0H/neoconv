"""C ROM byte interleaving for .neo container layout."""

from __future__ import annotations


def _interleave_c_chips(chips: list[bytes]) -> bytes:
    """
    Interleave pairs of C chips into .neo format.
    chips = [c1, c2, c3, c4, ...]
    Output: interleaved(c1,c2) + interleaved(c3,c4) + ...
    """
    result = bytearray()
    for i in range(0, len(chips), 2):
        a = chips[i]
        b = chips[i + 1]
        if len(a) != len(b):
            raise ValueError(
                f"C chip pair {i+1}/{i+2} size mismatch: "
                f"{len(a)} vs {len(b)} bytes."
            )
        interleaved = bytearray(len(a) + len(b))
        interleaved[0::2] = a
        interleaved[1::2] = b
        result.extend(interleaved)
    return bytes(result)
