"""任务中心领域异常。router 统一转换为 HTTPException，detail 为中文提示。"""


class TaskError(Exception):
    status_code = 400

    def __init__(self, message: str, code: str | None = None, extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.extra = extra or {}


class TaskNotFound(TaskError):
    status_code = 404


class TaskConflict(TaskError):
    status_code = 409


class TaskInvalid(TaskError):
    status_code = 422
