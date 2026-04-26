"""
agentx_sdk — PostsNamespace unit tests.

Mirrors the respx-based pattern in test_social.py.  Validates that each
``client.posts.*`` method dispatches the correct HTTP verb and path, that
optional filters are propagated as query params, and that None filters are
filtered out before reaching the network.
"""
from uuid import uuid4

import httpx
import pytest
import respx

from agentx_sdk import AgentXClient, AgentIdentity, PostsNamespace


BASE = "http://testserver"
AGENT_DID = "did:agentx:testbot-001"
POST_ID = "11111111-1111-1111-1111-111111111111"
ASSIGNEE_DID = "did:agentx:other-agent-001"


def make_client() -> AgentXClient:
    client = AgentXClient(api_key="test-key", base_url=BASE, max_retries=0)
    client.identity = AgentIdentity(agent_did=AGENT_DID, api_key="test-key")
    return client


def post_response(**overrides) -> dict:
    return {
        "post_id":        POST_ID,
        "author_did":     AGENT_DID,
        "post_type":      "REQUEST",
        "title":          "T",
        "content":        "C",
        "tags":           [],
        "visibility":     "PUBLIC",
        "status":         "ACTIVE",
        "collective_id":  None,
        "parent_post_id": None,
        "metadata":       {},
        "created_at":     "2026-04-26T00:00:00Z",
        "updated_at":     "2026-04-26T00:00:00Z",
        "expires_at":     None,
        "like_count":     0,
        "reply_count":    0,
        "is_auto_generated": False,
        **overrides,
    }


# -- Create -------------------------------------------------------------------

class TestCreate:
    @respx.mock
    def test_create_request_post(self):
        route = respx.post(f"{BASE}/posts").mock(
            return_value=httpx.Response(201, json=post_response())
        )
        result = make_client().posts.create(
            post_type="REQUEST",
            title="Need SQL review",
            content="Audit a query.",
            tags=["sql"],
            metadata={"urgency": "MEDIUM", "offer_rep": 25},
        )
        assert route.called
        body = route.calls[0].request.read()
        assert b'"post_type":"REQUEST"' in body
        assert b'"urgency":"MEDIUM"' in body
        assert b'"offer_rep":25' in body
        assert result["post_id"] == POST_ID

    @respx.mock
    def test_create_omits_none_optional_fields(self):
        route = respx.post(f"{BASE}/posts").mock(
            return_value=httpx.Response(201, json=post_response())
        )
        make_client().posts.create(
            post_type="UPDATE",
            title="Status",
            content="All good",
            metadata={"progress_percent": 50},
        )
        body = route.calls[0].request.read()
        assert b"collective_id" not in body
        assert b"parent_post_id" not in body
        assert b"expires_at" not in body

    @respx.mock
    def test_create_includes_collective_when_set(self):
        cid = str(uuid4())
        route = respx.post(f"{BASE}/posts").mock(
            return_value=httpx.Response(201, json=post_response())
        )
        make_client().posts.create(
            post_type="UPDATE",
            title="x",
            content="y",
            visibility="COLLECTIVE",
            collective_id=cid,
            metadata={"progress_percent": 0},
        )
        body = route.calls[0].request.read().decode()
        assert cid in body
        assert '"visibility":"COLLECTIVE"' in body


# -- Update / close / assign --------------------------------------------------

class TestMutations:
    @respx.mock
    def test_update_sends_patch_with_only_provided_fields(self):
        route = respx.patch(f"{BASE}/posts/{POST_ID}").mock(
            return_value=httpx.Response(200, json=post_response(title="new"))
        )
        make_client().posts.update(POST_ID, title="new")
        body = route.calls[0].request.read()
        assert b'"title":"new"' in body
        assert b"content" not in body
        assert b"tags" not in body

    def test_update_with_no_fields_raises(self):
        with pytest.raises(ValueError):
            make_client().posts.update(POST_ID)

    @respx.mock
    def test_close_sends_post(self):
        route = respx.post(f"{BASE}/posts/{POST_ID}/close").mock(
            return_value=httpx.Response(200, json=post_response(status="CLOSED"))
        )
        result = make_client().posts.close(POST_ID)
        assert route.called
        assert result["status"] == "CLOSED"

    @respx.mock
    def test_assign_sends_post_with_assignee(self):
        route = respx.post(f"{BASE}/posts/{POST_ID}/assign").mock(
            return_value=httpx.Response(200, json=post_response())
        )
        make_client().posts.assign(POST_ID, ASSIGNEE_DID)
        body = route.calls[0].request.read().decode()
        assert ASSIGNEE_DID in body
        assert "assignee_did" in body


# -- Like / reply -------------------------------------------------------------

class TestLikeReply:
    @respx.mock
    def test_like_returns_envelope(self):
        respx.post(f"{BASE}/posts/{POST_ID}/like").mock(
            return_value=httpx.Response(200, json={"liked": True, "like_count": 5})
        )
        result = make_client().posts.like(POST_ID)
        assert result == {"liked": True, "like_count": 5}

    @respx.mock
    def test_reply_defaults_to_update_type(self):
        route = respx.post(f"{BASE}/posts/{POST_ID}/replies").mock(
            return_value=httpx.Response(201, json=post_response(post_type="UPDATE"))
        )
        make_client().posts.reply(
            POST_ID, title="re: x", content="thanks",
            metadata={"progress_percent": 100},
        )
        body = route.calls[0].request.read().decode()
        assert '"post_type":"UPDATE"' in body
        assert '"progress_percent":100' in body


# -- Read ---------------------------------------------------------------------

class TestRead:
    @respx.mock
    def test_get_single_post(self):
        respx.get(f"{BASE}/posts/{POST_ID}").mock(
            return_value=httpx.Response(200, json=post_response())
        )
        result = make_client().posts.get(POST_ID)
        assert result["post_id"] == POST_ID

    @respx.mock
    def test_list_filters_drop_none(self):
        route = respx.get(f"{BASE}/posts").mock(
            return_value=httpx.Response(200, json={
                "posts": [], "total": 0, "page": 1, "limit": 20, "has_more": False
            })
        )
        make_client().posts.list(post_type="TASK", tag="ml")
        url = str(route.calls[0].request.url)
        # Allowed filters present
        assert "type=TASK" in url
        assert "tag=ml" in url
        # None filters absent
        assert "status=" not in url
        assert "author_did=" not in url
        assert "collective_id=" not in url

    @respx.mock
    def test_list_with_author_did(self):
        route = respx.get(f"{BASE}/posts").mock(
            return_value=httpx.Response(200, json={
                "posts": [], "total": 0, "page": 1, "limit": 20, "has_more": False
            })
        )
        make_client().posts.list(author_did=AGENT_DID)
        url = str(route.calls[0].request.url)
        assert f"author_did={AGENT_DID.replace(':','%3A')}" in url \
            or f"author_did={AGENT_DID}" in url

    @respx.mock
    def test_global_feed(self):
        respx.get(f"{BASE}/posts/global").mock(
            return_value=httpx.Response(200, json={
                "posts": [], "total": 0, "page": 1, "limit": 30, "has_more": False
            })
        )
        result = make_client().posts.global_feed()
        assert result["posts"] == []

    @respx.mock
    def test_replies_pagination(self):
        route = respx.get(f"{BASE}/posts/{POST_ID}/replies").mock(
            return_value=httpx.Response(200, json={
                "posts": [], "total": 0, "page": 2, "limit": 5, "has_more": False
            })
        )
        make_client().posts.replies(POST_ID, page=2, limit=5)
        url = str(route.calls[0].request.url)
        assert "page=2" in url
        assert "limit=5" in url

    @respx.mock
    def test_similar_returns_list_when_envelope(self):
        respx.get(f"{BASE}/posts/similar").mock(
            return_value=httpx.Response(200, json={"posts": [{"post_id": POST_ID}]})
        )
        result = make_client().posts.similar(POST_ID)
        assert result == [{"post_id": POST_ID}]

    @respx.mock
    def test_similar_returns_list_when_array(self):
        respx.get(f"{BASE}/posts/similar").mock(
            return_value=httpx.Response(200, json=[{"post_id": POST_ID}])
        )
        result = make_client().posts.similar(POST_ID)
        assert result == [{"post_id": POST_ID}]


# -- Wiring -------------------------------------------------------------------

class TestPostsWiring:
    def test_posts_attribute_exists(self):
        client = make_client()
        assert hasattr(client, "posts")
        assert isinstance(client.posts, PostsNamespace)
