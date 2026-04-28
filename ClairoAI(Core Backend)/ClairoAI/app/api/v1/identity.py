"""
Product identity endpoint.

Returns the canonical AHAL AI product identity — used by the
frontend, external integrations, and investor-facing demos.
"""

from fastapi import APIRouter

from app.core.product_identity import get_product_identity, get_product_summary

router = APIRouter()


@router.get("/identity")
async def product_identity():
    """Return the full AHAL AI product identity profile."""
    return get_product_identity()


@router.get("/identity/summary")
async def product_summary():
    """Return a compact one-line product summary."""
    return {"summary": get_product_summary()}
