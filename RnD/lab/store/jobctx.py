"""JobContext: what the worker hands a stage to check for cancellation, report progress and finish (plan decision 8).

`check_cancel()` raises `errors._Cancelled` when the job's cancel flag is set; `progress(p)` writes the run doc without
persisting it (exactly as the inference job did); `finish(**fields)` calls the worker's finish routine for this run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from lab.store import runs
from lab.store.errors import _Cancelled

if TYPE_CHECKING:
    from collections.abc import Callable


class JobContextLike(Protocol):
    run_id: str

    def check_cancel(self) -> None: ...

    def progress(self, p: float) -> None: ...

    def finish(self, **fields: Any) -> None: ...


class JobContext:
    def __init__(self, run_id: str, is_cancelled: Callable[[], bool], finish: Callable[..., None]) -> None:
        self.run_id = run_id
        self._is_cancelled = is_cancelled
        self._finish = finish

    def check_cancel(self) -> None:
        if self._is_cancelled():
            raise _Cancelled()

    def progress(self, p: float) -> None:
        runs._update_run(self.run_id, persist=False, progress=p)

    def finish(self, **fields: Any) -> None:
        self._finish(self.run_id, **fields)
