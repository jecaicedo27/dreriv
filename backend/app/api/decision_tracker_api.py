"""
API endpoint for L1 vs Groq decision tracker scorecard
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.services.decision_tracker import get_scorecard

router = APIRouter()


@router.get("/decision-tracker")
async def decision_tracker(db: Session = Depends(get_db)):
    """Get L1 vs Groq decision comparison scorecard"""
    return get_scorecard(db)
