"""Protect GUI workflows that may receive callbacks from a nested Qt event loop."""

from collections.abc import Callable
from functools import wraps
from typing import Concatenate
from weakref import WeakSet


def non_reentrant[Owner, **Arguments](
    operation: Callable[Concatenate[Owner, Arguments], None],
) -> Callable[Concatenate[Owner, Arguments], None]:
    """Ignore duplicate entry on the same object until this GUI action returns.

    Separate objects and different actions remain independent, including a
    deliberate confirmation or conflict review opened from another dialog.
    """
    active: WeakSet[Owner] = WeakSet()

    @wraps(operation)
    def guarded(owner: Owner, /, *args: Arguments.args, **kwargs: Arguments.kwargs) -> None:
        if owner in active:
            return
        active.add(owner)
        try:
            operation(owner, *args, **kwargs)
        finally:
            active.discard(owner)

    return guarded
