import pytesseract
from PIL import Image
import io

def solve_captcha(image_bytes: bytes) -> str:
    """
    Solves a CAPTCHA image using Tesseract OCR.
    Pre-processes the image for better accuracy.
    """
    try:
        image = Image.open(io.BytesIO(image_bytes))
        
        # Pre-processing (Convert to grayscale, maybe thresholding if needed)
        # eCourts captchas are usually simple enough for default tesseract or just grayscale
        gray_image = image.convert('L')
        
        # OCR
        text = pytesseract.image_to_string(gray_image)
        
        # Clean result (alphanumeric only usually)
        clean_text = "".join(c for c in text if c.isalnum())
        return clean_text
    except Exception as e:
        print(f"OCR Failed: {e}")
        return ""
