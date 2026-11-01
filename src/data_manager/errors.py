"""Expected persistence failures, distinct from programming errors."""


class DataManagerError(RuntimeError):
    pass


def format_data_error(error):
    return f"Data Manager error: {error}"
