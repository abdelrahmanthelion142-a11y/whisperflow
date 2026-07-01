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


class SnippetNotFoundException(Exception):
    """Raised when a snippet cannot be found for the given user."""

    pass


class DuplicateShortcutException(Exception):
    """Raised when a snippet shortcut already exists for a user (active or archived)."""

    pass
