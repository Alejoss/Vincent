"""Platform-specific writers (LLM prose generation)."""

from .channels import CHANNEL_WRITERS
from .essay import write_essay
from .outline import write_outline

__all__ = ["write_outline", "write_essay", "CHANNEL_WRITERS"]
