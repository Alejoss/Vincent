"""Editorial engine: outline → essay → platform posts."""

from .pipeline import generate_channels, generate_essay, generate_outline

__all__ = ["generate_outline", "generate_essay", "generate_channels"]
