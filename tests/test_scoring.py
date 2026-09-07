from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from app.birdweather.client import bounding_box,haversine_miles
from app.corroboration.scorer import score_detection
NOW=datetime(2026,9,3,18,tzinfo=timezone.utc)
def match(station,distance,minutes):return SimpleNamespace(station_id=station,distance_miles=distance,detected_at=NOW+timedelta(minutes=minutes))
def test_haversine(): assert 68 < haversine_miles(40,-75,41,-75) < 70
def test_bounding_box_contains_center():
    ne,sw=bounding_box(40,-75,10);assert ne["lat"]>40>sw["lat"] and ne["lon"]>-75>sw["lon"]
def test_repeats_do_not_count_as_independent():
    r=score_detection(.8,NOW,[match("a",1,x) for x in (-5,2,8,12,14)]);assert r.unique_stations==1
def test_independent_stations_raise_score():
    one=score_detection(.8,NOW,[match("a",3,30)]);three=score_detection(.8,NOW,[match(x,3,30) for x in "abc"]);assert three.score>one.score
def test_time_and_distance_affect_score():
    close=score_detection(.8,NOW,[match("a",1,5)]);far=score_detection(.8,NOW,[match("a",9,600)]);assert close.score>far.score
def test_before_and_after():assert score_detection(.8,NOW,[match("a",1,-5),match("b",1,5)]).before_and_after
