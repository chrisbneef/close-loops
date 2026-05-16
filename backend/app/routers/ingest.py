from __future__ import annotations

import logging

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import IngestRequest, IngestResponse
from app.services import decomposition
from app.services.llm import LLMNotConfigured

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
def post_ingest(req: IngestRequest, session: Session = Depends(get_session)) -> IngestResponse:
    try:
        return decomposition.ingest(
            session,
            raw_goal=req.raw_goal,
            owner_id=req.owner_id,
            project_id=req.project_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LLMNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except anthropic.AuthenticationError as e:
        raise HTTPException(status_code=503, detail="LLM unavailable: invalid ANTHROPIC_API_KEY") from e
    except anthropic.RateLimitError as e:
        raise HTTPException(status_code=429, detail="LLM rate-limited; try again shortly") from e
    except anthropic.APIError as e:
        logger.exception("Anthropic API failure")
        raise HTTPException(status_code=502, detail=f"LLM failure: {e!s}") from e
