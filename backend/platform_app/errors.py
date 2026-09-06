class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class RetryLater(Exception):
    def __init__(self, seconds: int, code: str = "RATE_LIMITED"):
        self.seconds, self.code = max(seconds, 1), code
