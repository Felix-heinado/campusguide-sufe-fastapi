import time
from concurrent.futures import ThreadPoolExecutor


def test_health_exposes_service_and_knowledge_stats(client):
    response = client.get("/api/health", headers={"X-Request-Id": "test-request"})
    assert response.status_code == 200
    assert response.headers["X-Request-Id"] == "test-request"
    assert response.json()["knowledgeBase"]["documents"] >= 100


def test_root_serves_the_complete_web_interface(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "财问 · SUFE Guide" in response.text
    assert "/frontend/app.js" in response.text


def test_frontend_assets_are_served_by_fastapi(client):
    response = client.get("/frontend/app.js")
    assert response.status_code == 200
    assert "requestAgentAnswer" in response.text


def test_search_prefers_domain_terms_over_generic_intent_words(client):
    short = client.post("/api/search", json={"query": "挂科重修", "limit": 5}).json()
    long = client.post("/api/search", json={"query": "挂科重修怎么办去哪办理", "limit": 5}).json()
    assert short["results"]
    assert short["results"][0]["id"] == long["results"][0]["id"]


def test_chat_refuses_when_evidence_is_missing(client):
    response = client.post("/api/chat", json={"question": "学校是否允许饲养外星宠物"})
    assert response.status_code == 200
    assert response.json()["status"] == "insufficient_evidence"


def test_chat_answers_a_short_but_specific_campus_topic(client):
    response = client.post("/api/chat", json={"question": "挂科重修怎么办"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "grounded"
    assert body["citations"][0]["id"] == "KB-2017-001"


def test_tools_are_constrained_and_validate_arguments(client):
    catalog = client.get("/api/tools").json()["tools"]
    assert {item["name"] for item in catalog} == {
        "search_documents", "get_document", "get_evidence", "record_feedback"
    }
    response = client.post("/api/tools/call", json={"name": "shell", "arguments": {}})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "UNKNOWN_TOOL"


def test_feedback_requires_a_real_boolean(client):
    response = client.post("/api/tools/call", json={
        "name": "record_feedback",
        "arguments": {"question": "test", "helpful": "false"},
    })
    assert response.status_code == 400


def test_parallel_idempotent_requests_return_one_task(client):
    body = {"source": "official-regulations-package", "idempotency_key": "same-request"}

    def submit():
        return client.post("/api/ingestion/tasks", json=body).json()["task"]["task_id"]

    with ThreadPoolExecutor(max_workers=10) as executor:
        task_ids = list(executor.map(lambda _: submit(), range(20)))
    assert len(set(task_ids)) == 1

    task_id = task_ids[0]
    for _ in range(50):
        task = client.get(f"/api/ingestion/tasks/{task_id}").json()["task"]
        if task["status"] == "succeeded":
            break
        time.sleep(0.01)
    assert task["status"] == "succeeded"
    assert task["result"]["registeredDocuments"] >= 100


def test_request_validation_is_visible_to_clients(client):
    response = client.post("/api/search", json={"query": "", "limit": 100})
    assert response.status_code == 422
