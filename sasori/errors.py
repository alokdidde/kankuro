class CliError(Exception):
    """An error reported to the caller as JSON: {"ok": false, "error": {code, message, hint}}."""

    def __init__(self, code, message, hint=None, details=None, exit_code=2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.details = details
        self.exit_code = exit_code

    def to_dict(self):
        d = {"code": self.code, "message": self.message}
        if self.hint:
            d["hint"] = self.hint
        if self.details is not None:
            d["details"] = self.details
        return d
