"""rawdecode — versioned raw sensor decoding dependency used by rawproc.

This is the single raw-decoding boundary of the project.  The development
kernel never opens a ``.raw`` byte stream or reaches into sidecar JSON
itself; it consumes the structured :class:`RawFrame` produced here.

Version policy
--------------
- ``DECODER_VERSION`` is the v2 contract version (structured frame, explicit
  levels / active window / as-shot white balance).
- ``LEGACY_API_VERSION`` records the v1 contract (loose ``RawMeta`` + bare
  pixel list) that :mod:`rawproc.rawio` still mirrors for reference.
"""

from .decoder import (
    DECODER_NAME,
    DECODER_VERSION,
    LEGACY_API_VERSION,
    decode_sidecar,
)
from .errors import (
    DecodeError,
    LevelError,
    StreamError,
    WhiteBalanceError,
    WindowError,
)
from .models import (
    CHANNELS,
    ActiveWindow,
    RawFrame,
    RawLevels,
    WhiteBalanceCoeffs,
)
from .stream import read_uint16_plane, write_uint16_plane

__all__ = [
    "DECODER_NAME",
    "DECODER_VERSION",
    "LEGACY_API_VERSION",
    "decode_sidecar",
    "DecodeError",
    "LevelError",
    "StreamError",
    "WhiteBalanceError",
    "WindowError",
    "CHANNELS",
    "ActiveWindow",
    "RawFrame",
    "RawLevels",
    "WhiteBalanceCoeffs",
    "read_uint16_plane",
    "write_uint16_plane",
]
