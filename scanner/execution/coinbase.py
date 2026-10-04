from .base import ExecutionEngine


class CoinbaseExecution(ExecutionEngine):
    """Future extension boundary. Always raises; contains no order API client."""
