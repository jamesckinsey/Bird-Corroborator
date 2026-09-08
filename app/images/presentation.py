from sqlalchemy import select
from app.db.models import SpeciesImage
PLACEHOLDER_URL="/static/images/placeholder-bird.svg"
def image_map(session,scientific_names):
    names=set(scientific_names)
    rows=session.scalars(select(SpeciesImage).where(SpeciesImage.species_scientific.in_(names))) if names else []
    return {row.species_scientific:row for row in rows}
def image_fields(row):
    if row and row.retrieval_status=="COMPLETE" and row.cached_image_path and row.cached_image_path.endswith(".webp"):
        return {"image_url":f"/media/species/{row.species_key}","image_attribution":row.attribution,"image_source":row.source_provider}
    return {"image_url":PLACEHOLDER_URL,"image_attribution":None,"image_source":None}
