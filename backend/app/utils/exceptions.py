class AppException(Exception):
    def __init__(self, message: str, status_code: int = 400, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", detail: dict | None = None):
        super().__init__(message, status_code=404, detail=detail)


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Unauthorized", detail: dict | None = None):
        super().__init__(message, status_code=401, detail=detail)


class ForbiddenException(AppException):
    def __init__(self, message: str = "Forbidden", detail: dict | None = None):
        super().__init__(message, status_code=403, detail=detail)
