class InvalidCredentialsException(Exception):
    """Raised when authentication fails."""

    pass


# app/users/exceptions.py


class UsernameAlreadyExistsException(Exception):
    """Raised when a user tries to register with an occupied username."""

    pass


class EmailAlreadyExistsException(Exception):
    """Raised when a user tries to register with an occupied email."""

    pass


class InvalidTokenException(Exception):
    """Raised when a JWT token is malformed, expired, or invalid."""

    pass
