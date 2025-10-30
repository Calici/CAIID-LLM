from typing import TypeVar, Callable, Generic, final

T = TypeVar("T")


def find_in_list(vs: list[T], f: Callable[[T], bool]) -> tuple[int, T] | None:
    for id, v in enumerate(vs):
        if f(v):
            return (id, v)
    return None


@final
class IsEqual(Generic[T]):
    def __init__(self, left: T):
        self.left = left

    def __call__(self, right: T) -> bool:
        return self.left == right


V = TypeVar("V")


@final
class ProjectCompare(Generic[T, V]):
    def __init__(self, projector: Callable[[T], V], left: V):
        self.left = left
        self.projector = projector

    def __call__(self, right: T):
        return self.left == self.projector(right)
