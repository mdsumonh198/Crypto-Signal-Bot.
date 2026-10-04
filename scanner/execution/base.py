class ExecutionDisabled(RuntimeError):
    pass


class ExecutionEngine:
    def submit(self, *args, **kwargs):
        raise ExecutionDisabled('Real execution is unavailable in Phase 1')
