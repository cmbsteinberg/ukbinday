class BinLookupError(Exception):
    """Base exception for bin lookup errors"""

    pass


class ConfigError(BinLookupError):
    """Raised when council configuration is invalid"""

    pass


class RequestError(BinLookupError):
    """Raised when HTTP request fails"""

    pass
