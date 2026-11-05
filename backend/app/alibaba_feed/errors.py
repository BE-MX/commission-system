"""Safe errors: never include external content or database exception text."""


class FeedError(Exception):
    def __init__(self, status_code, error_code, field_path=None, retry_after=None):
        super().__init__(error_code)
        self.status_code = status_code
        self.error_code = error_code
        self.field_path = field_path
        self.retry_after = retry_after
