"""Model failures whose messages are authored locally and safe to show users."""


class ModelRequestError(ValueError):
    def __init__(self, message, code='invalid_response'):
        super().__init__(message)
        self.code = code


class ModelOutputLimitError(ModelRequestError):
    def __init__(self, message):
        super().__init__(message, 'output_limit')
