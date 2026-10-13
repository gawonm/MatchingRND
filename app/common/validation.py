"""Shared positive-integer configuration validation."""

def _positive_int(value, name, minimum=1):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f'{name}는 {minimum} 이상의 정수여야 합니다.')
    try:
        result = int(value)
    except ValueError as error:
        raise ValueError(f'{name}는 {minimum} 이상의 정수여야 합니다.') from error
    if result < minimum:
        raise ValueError(f'{name}는 {minimum} 이상의 정수여야 합니다.')
    return result
