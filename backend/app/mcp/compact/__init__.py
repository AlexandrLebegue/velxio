"""Independent compact contracts, catalog and project store. No MCP registration."""

from .catalog import Catalog, CatalogError
from .contracts import TOOL_SCHEMAS
from .projects import ProjectStore

__all__ = ["Catalog", "CatalogError", "ProjectStore", "TOOL_SCHEMAS"]
