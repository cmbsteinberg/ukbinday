from pydantic import BaseModel, Field
from typing import Optional, Union
from datetime import datetime
from enum import Enum


class BinColour(Enum):
    GREY = "grey"
    BLACK = "black"
    ORANGE = "orange"
    BLUE = "blue"
    RED = "red"
    BROWN = "brown"
    GREEN = "green"


class BinInfo(BaseModel, use_enum_values=True):
    next_pickup_day: Union[datetime, str, None]
    frequency: Optional[str]
    bin_colour: Optional[BinColour]


class BinDays(BaseModel, use_enum_values=True):
    postcode: Optional[str]
    general_waste: BinInfo
    recycling: BinInfo
    food_waste: BinInfo
    garden_waste: BinInfo
    notes: Optional[str] = None
