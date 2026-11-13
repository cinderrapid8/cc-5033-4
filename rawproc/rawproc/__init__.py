"""rawproc — minimal, explicit Bayer raw development prototype.

Implemented scope: one Bayer layout (RGGB family, any 2x2 phase), little
endian uint16 sensor dumps with JSON sidecars, per-channel black/white
correction with preserved under-black/saturation flags, bilinear
demosaicing, optional white balance and separate display conversion.
"""

from .errors import MetadataError, RawDevError, RawIOError, UnsupportedLayoutError
from .metadata import RawMeta, load_metadata
from .pipeline import PipelineResult, run_pipeline, save_outputs

__all__ = [
    "RawDevError",
    "MetadataError",
    "RawIOError",
    "UnsupportedLayoutError",
    "RawMeta",
    "load_metadata",
    "PipelineResult",
    "run_pipeline",
    "save_outputs",
]
