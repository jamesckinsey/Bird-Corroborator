from dataclasses import dataclass
@dataclass
class Score:
    score:int; level:str; unique_stations:int; matches:int; nearest_miles:float|None; closest_minutes:float|None; before_and_after:bool
