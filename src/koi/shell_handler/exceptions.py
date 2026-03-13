class ShellHandlerError(Exception):
    pass


class CommandTimeout(ShellHandlerError):
    def __init__(self, command: str, timeout: float):
        self.command = command
        self.timeout = timeout
        super().__init__(f"Command timed out after {timeout}s: {command}")


class CommandFailed(ShellHandlerError):
    def __init__(self, command: str, returncode: int, stderr: str = ""):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"Command failed with code {returncode}: {command}"
            + (f"\nstderr: {stderr}" if stderr else "")
        )


class MaxRetriesExceeded(ShellHandlerError):
    def __init__(self, command: str, attempts: int):
        self.command = command
        self.attempts = attempts
        super().__init__(f"Command failed after {attempts} attempts: {command}")


class SessionClosed(ShellHandlerError):
    pass


class SessionTimeout(ShellHandlerError):
    pass