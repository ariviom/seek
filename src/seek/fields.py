"""Field types the API's request bodies share."""

from typing import Annotated

from pydantic import BeforeValidator, StringConstraints

from seek.channels import CheckHours

type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


def _whole_hours(value: object) -> object:
    # A Literal of ints would also take 24.0.
    if value is not None and type(value) is not int:
        raise ValueError("Check every 6, 24 or 168 hours, or null for off")
    return value


# How often a Channel or a Playlist is checked; null turns checks off.
type CheckEvery = Annotated[CheckHours | None, BeforeValidator(_whole_hours)]
