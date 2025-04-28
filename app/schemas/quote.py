from pydantic import BaseModel, Field
from typing import Optional

class QuoteBase(BaseModel):
    text: str
    author: Optional[str] = Field(default=None)  # Make author optional

class QuoteCreate(QuoteBase):
    pass

class Quote(QuoteBase):
    id: int

    class Config:
        from_attributes = True

class QuoteExtractResult(BaseModel):
    extracted_text: str
    extracted_author: Optional[str] = None
