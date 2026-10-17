"""What the options flow stores.

Kept apart from ``config_flow`` so it can be tested without Home Assistant:
the flow itself is form plumbing, but which values survive a submission is a
decision worth pinning down.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def merge_options(
    current: Mapping[str, Any], submitted: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the stored options with the submitted ones laid over them.

    Home Assistant replaces an entry's options wholesale with whatever the flow
    returns, and the form does not always show every field: the operator, meter,
    scheme and product dropdowns are built from the VREG files and are left out
    when those cannot be fetched. Returning the submitted values alone would
    then erase the all-in price configuration -- the sensor would go unavailable
    and nothing would say why -- so a field that was not on the form keeps what
    it had.

    A field that *was* on the form always wins, including when it was submitted
    empty: "Not set" is a choice, not an absence.
    """
    return {**current, **submitted}
