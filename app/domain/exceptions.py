class DomainException(Exception):
    """Base domain exception."""
    pass

class SSRFSecurityException(DomainException):
    """Raised when a URL attempts to target internal/private network IP ranges."""
    pass

class DRMProtectedException(DomainException):
    """Raised when media is DRM encrypted and cannot be retrieved."""
    pass

class RateLimitExceededException(DomainException):
    """Raised when request rate exceeds token bucket limits."""
    pass

class DownloadCancelledException(DomainException):
    """Raised when a download job is cancelled by the user."""
    pass

class CircuitBreakerOpenException(DomainException):
    """Raised when external service calls are temporarily halted due to repeated failures."""
    pass

