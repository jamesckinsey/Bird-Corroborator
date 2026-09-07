from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.birdnet.models import BirdNetDetection
from app.db.models import LocalDetection
def insert_detection(session,item:BirdNetDetection):
    row=LocalDetection(source_detection_id=item.source_detection_id,species_common=item.species_common,species_scientific=item.species_scientific,detected_at=item.detected_at,confidence=item.confidence,audio_reference=item.audio_reference,raw_metadata=item.raw_metadata)
    try: session.add(row); session.commit(); return row,True
    except IntegrityError:
        session.rollback(); return session.scalar(select(LocalDetection).where(LocalDetection.source_detection_id==item.source_detection_id)),False
