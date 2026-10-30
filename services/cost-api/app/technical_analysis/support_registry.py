"""Explicit technical support coverage; catalog membership is not support."""

from dataclasses import dataclass
from types import MappingProxyType

from .owned_synthetic_source import CODE


@dataclass(frozen=True)
class PositionSupport:
    position_code: str
    unit: str
    scope: str
    pdf_page: int | None
    source_kind: str = "analysis_pdf"


SUPPORTED_POSITIONS = MappingProxyType(
    {
        CODE: PositionSupport(CODE, "m²", "layers_and_critical_attributes_only", None, "synthetic_owned"),
        "15.275.1111": PositionSupport(
            position_code="15.275.1111",
            unit="m²",
            scope="layers_and_critical_attributes_only",
            pdf_page=423,
        ),
    }
)


def get_position_support(position_code: str | None) -> PositionSupport | None:
    """Unknown candidates must remain outside this pilot's verified scope."""
    return SUPPORTED_POSITIONS.get(position_code)
