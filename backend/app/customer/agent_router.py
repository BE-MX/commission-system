"""Reserved Customer Hub Agent surface.

Task-scoped acquisition/research writes remain registered exactly once through
``sales_automation.agent_router`` until the secured Agent tools replace them.
"""

from fastapi import APIRouter


router = APIRouter()
