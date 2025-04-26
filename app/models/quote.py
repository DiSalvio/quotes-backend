from sqlalchemy import Column, Integer, String
from app.database import Base

class Quote(Base):
    __tablename__ = "quotes"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(String, nullable=False)
    author = Column(String, server_default="Unknown")
