"""
DEPRECATED: app.analyzer has been refactored to app.services.inspection_service.
This module re-exports functions and delegates to InspectionService with full SSRF,
TLS validation, and circuit breaker protection.
"""
import warnings
from typing import Optional, List, Dict, Any
from app.services.inspection_service import (
    InspectionService,
    inspection_service,
    DIRECT_EXTENSIONS,
)
from app.domain.models import AnalyzedLink, FormatOption

warnings.warn(
    "app.analyzer is deprecated; use app.services.inspection_service instead.",
    DeprecationWarning,
    stacklevel=2,
)

def is_direct_file_url(url: str) -> bool:
    return inspection_service.is_direct_file_url(url)

async def probe_direct_file(url: str) -> Optional[AnalyzedLink]:
    return await inspection_service.probe_direct_file(url)

async def analyze_url(url: str) -> AnalyzedLink:
    return await inspection_service.analyze(url)

__all__ = [
    "DIRECT_EXTENSIONS",
    "is_direct_file_url",
    "probe_direct_file",
    "analyze_url",
]
