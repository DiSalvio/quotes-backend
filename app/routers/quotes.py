from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import io
import re
import numpy as np
import cv2
from app import schemas
from app.models.quote import Quote
from app.database import get_db

router = APIRouter()
def preprocess_quote_image(img):
    """Enhanced preprocessing specifically for quote images"""
    # Convert to numpy array
    img_np = np.array(img)
    
    # Convert to grayscale
    if len(img_np.shape) == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_np
    
    # Increase resolution (2x upscale)
    height, width = gray.shape
    gray = cv2.resize(gray, (width * 2, height * 2), interpolation=cv2.INTER_CUBIC)
    
    # Apply adaptive thresholding
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                                  cv2.THRESH_BINARY, 11, 2)
    
    # Perform noise removal
    kernel = np.ones((1, 1), np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(cleaned)
    
    return Image.fromarray(enhanced)

def extract_author_from_quote(text_lines, original_image):
    """Multiple specialized pattern matching for author extraction"""
    author = None
    quote_text = None
    
    # No lines detected
    if not text_lines:
        return "", None
    
    # 1. ALL CAPS pattern (Simone Biles style)
    # Look for any line with ALL CAPS that's likely an author
    for line in text_lines:
        # Clean the line from special characters
        clean_line = re.sub(r'[^\w\s]', '', line)
        # Check if it's all uppercase and reasonable length for a name
        if clean_line.isupper() and len(clean_line.split()) <= 4 and len(clean_line) >= 3:
            author = re.search(r'([A-Z]{2,}[\s]*[A-Z]{2,})', line)
            if author:
                author = author.group(0).strip()
                # Remove author line from quote text
                quote_text = "\n".join([l for l in text_lines if author not in l])
                return quote_text, author
    
    # 2. Dash-prefix pattern (Michael Jordan style)
    for line in text_lines:
        # Look for various dash styles followed by a name
        dash_match = re.search(r'[-–-]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})', line)
        if dash_match:
            author = dash_match.group(1).strip()
            # Remove author from quote
            quote_text = "\n".join([l.replace(dash_match.group(0), "") for l in text_lines])
            return quote_text, author
    
    # 3. Bottom-aligned name pattern (Ralph Waldo Emerson style)
    # Last line with proper capitalization pattern
    if len(text_lines) > 1:
        last_line = text_lines[-1].strip()
        # Pattern for a properly capitalized multi-word name
        name_match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})$', last_line)
        if name_match and len(last_line.split()) >= 2:
            author = last_line
            quote_text = "\n".join(text_lines[:-1])
            return quote_text, author
    
    # 4. Fallback: Check for position-based author detection
    # This requires image analysis for bottom-aligned text
    
    # If no author found, return original text
    return "\n".join(text_lines), author


@router.post("/quotes/", response_model=schemas.Quote)
def create_quote(quote: schemas.QuoteCreate, db: Session = Depends(get_db)):
    db_quote = Quote(**quote.model_dump())
    db.add(db_quote)
    db.commit()
    db.refresh(db_quote)
    return db_quote


@router.get("/quotes/", response_model=List[schemas.Quote])
def read_quotes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Quote).offset(skip).limit(limit).all()

@router.put("/quotes/{quote_id}", response_model=schemas.Quote)
def update_quote(
    quote_id: int,
    quote_update: schemas.QuoteBase,
    db: Session = Depends(get_db)
):
    db_quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not db_quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    db_quote.text = quote_update.text
    db_quote.author = quote_update.author or "Unknown"

    db.commit()
    db.refresh(db_quote)
    return db_quote

@router.delete("/quotes/{quote_id}", status_code=204)
def delete_quote(quote_id: int, db: Session = Depends(get_db)):
    db_quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if not db_quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    db.delete(db_quote)
    db.commit()
    return None


@router.post("/quotes/from-image/")
async def create_quote_from_image(image: UploadFile = File(...)):
    try:
        # Read image
        image_bytes = await image.read()
        img = Image.open(io.BytesIO(image_bytes))
        
        # Use enhanced preprocessing
        processed_img = preprocess_quote_image(img)
        
        # Try multiple OCR configuration options
        config_options = [
            r'--psm 6 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,\'\"-:;!? ',
            r'--psm 4 --oem 3',  # Assume single column of text
            r'--psm 3 --oem 3'   # Auto page segmentation
        ]
        
        best_result = ""
        for config in config_options:
            extracted_text = pytesseract.image_to_string(processed_img, config=config)
            if len(extracted_text) > len(best_result):
                best_result = extracted_text
        
        # Clean extracted text
        cleaned_text = re.sub(r'\s+', ' ', best_result).strip()
        text_lines = [line.strip() for line in cleaned_text.split('\n') if line.strip()]
        
        # Apply dictionary correction
        text_lines = [correct_common_ocr_errors(line) for line in text_lines]
        
        # Extract quote and author
        quote_text, author = extract_author_from_quote(text_lines, img)
        
        return {
            "extracted_text": quote_text.strip(),
            "extracted_author": author
        }
    except Exception as e:
        raise HTTPException(500, f"Error processing image: {str(e)}")


def correct_common_ocr_errors(text):
    """Dictionary-based correction for common OCR errors"""
    corrections = {
        "beeause": "because",
        "vou": "you",
        "IT think": "I think",
        "y Bas": "Always",
        ") »": "",
        "| ot": "",
        ";": ""
    }
    
    for error, correction in corrections.items():
        text = text.replace(error, correction)
    
    return text
