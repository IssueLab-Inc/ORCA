"""ORCA's server (the package keeps its first name, sightline).

The repo's .env is read here, on the first import of any module of the package, because several modules read their
settings at import (service.MAX_SCENES, step.MAX_PARTS, scene.BIG_MODEL_BYTES, built.CACHE, ...). Real environment
variables win.
"""
from .meta_client import load_env

load_env()
