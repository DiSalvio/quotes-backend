from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app import schemas
from app.models.quote import Quote
from app.database import get_db

router = APIRouter()

@router.post("/quotes/", response_model=schemas.Quote)
def create_quote(quote: schemas.QuoteCreate, db: Session = Depends(get_db)):
    db_quote = Quote(**quote.model_dump())  # Updated from .dict() in Pydantic v2
    db.add(db_quote)
    db.commit()
    db.refresh(db_quote)
    return db_quote

@router.get("/quotes/", response_model=list[schemas.Quote])
def read_quotes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Quote).offset(skip).limit(limit).all()
