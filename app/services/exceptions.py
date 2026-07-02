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


class UnsupportedFormatException(Exception):
    """Raised when the uploaded audio file has an unsupported extension."""

    pass


class FileTooLargeException(Exception):
    """Raised when the uploaded audio file exceeds MAX_FILE_SIZE_MB."""

    pass


class AudioTooLongException(Exception):
    """Raised when the uploaded audio file exceeds MAX_AUDIO_DURATION_SECS."""

    pass


class InvalidLanguageException(Exception):
    """Raised when the requested language code is not ISO 639-1 or 'auto'."""

    pass


class TranscriptionFailedException(Exception):
    """Raised when the Whisper API call fails."""

    pass


class SnippetNotFoundException(Exception):
    """Raised when a snippet cannot be found for the given user."""

    pass


class DuplicateShortcutException(Exception):
    """Raised when a snippet shortcut already exists for a user (active or archived)."""

    pass
