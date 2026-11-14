class AppError(Exception):
    """Base class for expected, client-facing errors raised by services."""

    status_code = 400
    default_detail = "Bad request"

    def __init__(self, detail: str | None = None, headers: dict[str, str] | None = None):
        self.detail = detail or self.default_detail
        self.headers = headers
        super().__init__(self.detail)


class BadRequestError(AppError):
    status_code = 400
    default_detail = "Bad request"


class UnauthorizedError(AppError):
    status_code = 401
    default_detail = "Could not validate credentials"

    def __init__(self, detail: str | None = None):
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = 403
    default_detail = "You do not have permission to perform this action"


class NotFoundError(AppError):
    status_code = 404
    default_detail = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    default_detail = "Conflict"


class UnprocessableError(AppError):
    """Well-formed request whose values don't make sense together (e.g. min > max)."""

    status_code = 422
    default_detail = "Unprocessable request"


class PaymentRequiredError(AppError):
    """The payment provider declined the charge."""

    status_code = 402
    default_detail = "Payment declined"


class BadGatewayError(AppError):
    """The (simulated) payment provider failed; nothing was charged or saved."""

    status_code = 502
    default_detail = "Payment provider unavailable. Nothing was charged; please retry."
