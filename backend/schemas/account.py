from typing import Literal

from pydantic import BaseModel


class AccountDeleteRequest(BaseModel):
    password: str
    confirmation: Literal["DELETE"]
