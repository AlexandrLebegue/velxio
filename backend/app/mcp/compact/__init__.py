"""Independent compact contracts and read-only catalog. No MCP registration."""

from .catalog import Catalog, CatalogError
from .contracts import TOOL_SCHEMAS

__all__ = ["Catalog", "CatalogError", "TOOL_SCHEMAS"]
