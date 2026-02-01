from http import HTTPStatus
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == HTTPStatus.OK
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_agents_and_groups(async_client: AsyncClient):
    agent_payload = {"name": "Tester", "persona": "builder", "bio": "test"}
    response = await async_client.post("/api/agents", json=agent_payload)
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    response = await async_client.get("/api/agents")
    agents = response.json()
    assert agents
    agent_id = agents[0]["id"]

    group_payload = {
        "name": "r/test",
        "topic": "testing",
        "description": "test group",
        "created_by_id": agent_id,
    }
    response = await async_client.post("/api/groups", json=group_payload)
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)


@pytest.mark.asyncio
async def test_posts_and_comments(async_client: AsyncClient):
    agents = (await async_client.get("/api/agents")).json()
    groups = (await async_client.get("/api/groups")).json()
    assert agents and groups

    post_payload = {
        "title": "Test Post",
        "content": "Hello world",
        "author_id": agents[0]["id"],
        "group_id": groups[0]["id"],
    }
    response = await async_client.post("/api/posts", json=post_payload)
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    post = response.json()

    comment_payload = {
        "content": "Nice thread",
        "author_id": agents[0]["id"],
        "post_id": post["id"],
    }
    response = await async_client.post("/api/comments", json=comment_payload)
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    root_comment = response.json()

    nested_payload = {
        "content": "Nested reply",
        "author_id": agents[0]["id"],
        "post_id": post["id"],
        "parent_comment_id": root_comment["id"],
    }
    response = await async_client.post("/api/comments", json=nested_payload)
    assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
    nested_comment = response.json()
    assert nested_comment["parent_comment_id"] == root_comment["id"]

    vote_payload = {"voter_id": agents[0]["id"], "value": 1}
    response = await async_client.post(f"/api/posts/{post['id']}/vote", json=vote_payload)
    assert response.status_code == HTTPStatus.OK
    assert response.json()["score"] == 1

    response = await async_client.post(f"/api/comments/{root_comment['id']}/vote", json=vote_payload)
    assert response.status_code == HTTPStatus.OK
    assert response.json()["score"] == 1

    response = await async_client.get("/api/posts?sort=top")
    assert response.status_code == HTTPStatus.OK
    top_posts = response.json()
    assert top_posts and top_posts[0]["id"] == post["id"]

    response = await async_client.get("/api/posts?sort=discussed")
    assert response.status_code == HTTPStatus.OK
    discussed_posts = response.json()
    assert discussed_posts and discussed_posts[0]["id"] == post["id"]

    response = await async_client.get(f"/api/comments?post_id={post['id']}&parent_comment_id={root_comment['id']}")
    assert response.status_code == HTTPStatus.OK
    nested = response.json()
    assert nested and nested[0]["id"] == nested_comment["id"]
