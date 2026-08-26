from pydantic import BaseModel
from typing import Optional

class ExtractedProductData(BaseModel):
    title: str
    brand: str
    ean_gtin: Optional[str] = None
    search_keyword: Optional[str] = None
    search_position: Optional[int] = None
    base_price: float
    discount_price: Optional[float] = None
    is_sponsored: bool = False
    banner_presence: bool = False
    promotion_tag: Optional[str] = None
    in_stock: bool = True