class ECourtsError(Exception):
    """Base error for scraper."""
    pass

class TokenError(ECourtsError):
    """Raised when token is invalid or missing."""
    pass

class CaptchaError(ECourtsError):
    """Raised when captcha is invalid."""
    pass

class SessionExpiredError(ECourtsError):
    """Raised when session is not found in Redis."""
    pass

class RetryableError(ECourtsError):
    """Raised when an operation should be retried."""
    pass
