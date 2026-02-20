from __future__ import annotations

import pytest

from backend.app.services.incubator.supadata_search import (
    SupadataSearchQuery,
    SupadataSearchService,
)


def test_supadata_search_incubator_placeholder_is_explicit() -> None:
    service = SupadataSearchService(api_key="test-key")

    with pytest.raises(NotImplementedError, match="incubator"):
        service.search_videos(SupadataSearchQuery(query="microservices"))
