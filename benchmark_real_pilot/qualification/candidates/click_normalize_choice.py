from __future__ import annotations

import enum


class _Ctx:
    def __init__(self, func):
        self.token_normalize_func = func


class Choice:
    def __init__(self, choices, case_sensitive: bool = True) -> None:
        self.choices = tuple(choices)
        self.case_sensitive = case_sensitive

    def normalize_choice(self, choice, ctx):
        normed_value = choice.name if isinstance(choice, enum.Enum) else str(choice)

        if ctx is not None and ctx.token_normalize_func is not None:
            normed_value = ctx.token_normalize_func(normed_value)

        if not self.case_sensitive:
            normed_value = normed_value.casefold()

        return normed_value


def _map_dash(value: str) -> str:
    return value.replace("-", "_")


def _entry(choice, normalize_mode: str, case_sensitive: bool):
    func = {"lower": str.lower, "map": _map_dash}[normalize_mode]
    ctx = _Ctx(func)
    return Choice([choice], case_sensitive=case_sensitive).normalize_choice(choice, ctx)
