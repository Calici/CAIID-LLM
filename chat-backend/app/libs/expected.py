from __future__ import annotations
from collections.abc import Awaitable
from typing import Callable, Generic, TypeVar, final

T = TypeVar("T")
E = TypeVar("E")
V = TypeVar("V")


@final
class Expected(Generic[T, E]):
    def __init__(self, value_type: type[T], error_type: type[E], value: T | E):
        self.value_type = value_type
        self.error_type = error_type
        self._value = value

    def value(self) -> T:
        if not isinstance(self._value, self.value_type):
            raise ValueError
        return self._value

    def error(self) -> E:
        if not isinstance(self._value, self.error_type):
            raise ValueError
        return self._value

    def has_value(self) -> bool:
        return isinstance(self._value, self.value_type)

    def transform(self, value_type: type[V], f: Callable[[T], V]) -> Expected[V, E]:
        if isinstance(self._value, self.value_type):
            return Expected(value_type, self.error_type, f(self._value))
        if isinstance(self._value, self.error_type):
            return Expected(value_type, self.error_type, self._value)
        raise AssertionError("unreachable")

    def transform_error(
        self, error_type: type[V], f: Callable[[E], V]
    ) -> Expected[T, V]:
        if isinstance(self._value, self.value_type):
            return Expected(self.value_type, error_type, self._value)
        if isinstance(self._value, self.error_type):
            return Expected(self.value_type, error_type, f(self._value))
        raise AssertionError("unreachable")

    def and_then(
        self, value_type: type[T], f: Callable[[T], Expected[V, E]]
    ) -> Expected[V, E]:
        if isinstance(self._value, self.value_type):
            return f(self._value)
        if isinstance(self._value, self.error_type):
            return Expected(value_type, self.error_type, self._value)
        raise AssertionError("unreachable")

    def or_else(
        self, error_type: type[V], f: Callable[[E], Expected[T, V]]
    ) -> Expected[T, V]:
        if isinstance(self._value, self.error_type):
            return f(self._value)
        if isinstance(self._value, self.value_type):
            return Expected(self.value_type, error_type, self._value)
        raise AssertionError("unreachable")

    async def atransform(
        self, value_type: type[V], f: Callable[[T], Awaitable[V]]
    ) -> Expected[V, E]:
        if isinstance(self._value, self.value_type):
            return Expected(value_type, self.error_type, await f(self._value))
        if isinstance(self._value, self.error_type):
            return Expected(value_type, self.error_type, self._value)
        raise AssertionError("unreachable")

    async def aand_then(
        self, value_type: type[V], f: Callable[[T], Awaitable[Expected[V, E]]]
    ) -> Expected[V, E]:
        if isinstance(self._value, self.value_type):
            return await f(self._value)
        if isinstance(self._value, self.error_type):
            return Expected(value_type, self.error_type, self._value)
        raise AssertionError("unreachable")
