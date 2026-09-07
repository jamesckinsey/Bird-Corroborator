from datetime import datetime,timezone
from app.corroboration.models import Score
ALGORITHM_VERSION="v1"
LEVELS=((80,"STRONGLY_CORROBORATED"),(55,"LIKELY"),(30,"POSSIBLE"),(0,"UNVERIFIED"))
def score_detection(confidence:float, detected_at:datetime, matches)->Score:
    if not matches: return Score(round(min(20,max(0,confidence*20))),"UNVERIFIED",0,0,None,None,False)
    stations={m.station_id for m in matches}; distances=[m.distance_miles for m in matches]
    # SQLite may return a naive value even for timezone=True; persisted values are UTC.
    local=detected_at if detected_at.tzinfo else detected_at.replace(tzinfo=timezone.utc)
    times=[m.detected_at if m.detected_at.tzinfo else m.detected_at.replace(tzinfo=timezone.utc) for m in matches]
    diffs=[abs((x-local).total_seconds())/60 for x in times]
    signed=[(x-local).total_seconds() for x in times]
    points=confidence*20
    # Nearest match: one mutually exclusive distance band.
    nearest=min(distances); points += 25 if nearest<=2 else 18 if nearest<=5 else 10
    # Closest match: one mutually exclusive time band.
    closest=min(diffs); points += 25 if closest<=15 else 18 if closest<=60 else 8 if closest<=1440 else 0
    # Independence dominates volume; repeats have a small capped contribution.
    points += min(24,max(0,len(stations)-1)*8)
    points += min(6,max(0,len(matches)-len(stations))*2)
    both=any(x<0 for x in signed) and any(x>0 for x in signed); points += 5 if both else 0
    value=min(100,round(points)); level=next(label for threshold,label in LEVELS if value>=threshold)
    return Score(value,level,len(stations),len(matches),nearest,closest,both)
