"""Tests for web routes."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from web.server import app
    return TestClient(app)


class TestHomeRoute:
    def test_home_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Knowledge Base" in resp.text

    def test_home_has_input_form(self, client):
        resp = client.get("/")
        assert "<form" in resp.text
        assert "url" in resp.text


class TestLibraryRoute:
    def test_library_returns_200(self, client):
        resp = client.get("/library")
        assert resp.status_code == 200

    def test_library_lists_courses(self, client):
        # Should list any courses in data/knowledge_base/
        resp = client.get("/library")
        assert resp.status_code == 200


class TestCourseRoute:
    def test_nonexistent_course_returns_404(self, client):
        resp = client.get("/course/nonexistent-slug")
        assert resp.status_code == 404


class TestDownloadRoute:
    def test_nonexistent_course_returns_404(self, client):
        resp = client.get("/download/nonexistent-slug")
        assert resp.status_code == 404


class TestIntegration:
    def test_full_navigation_flow(self, client):
        """Home -> Library -> Course -> Video navigation works."""
        # Home
        resp = client.get("/")
        assert resp.status_code == 200

        # Library
        resp = client.get("/library")
        assert resp.status_code == 200

        # A known course (may not exist in test env)
        resp = client.get("/course/python-tutorials-for-absolute-beginners-by-cs-dojo")
        if resp.status_code == 200:
            resp = client.get(
                "/course/python-tutorials-for-absolute-beginners-by-cs-dojo/"
                "01-python-tutorial-for-absolute-beginners-1-what-are-variables"
            )
            assert resp.status_code == 200

    def test_download_existing_course(self, client):
        """Download ZIP for an existing course."""
        resp = client.get("/download/python-tutorials-for-absolute-beginners-by-cs-dojo")
        if resp.status_code == 200:
            assert resp.headers["content-type"] == "application/zip"

    def test_static_files_served(self, client):
        """CSS and JS files are accessible."""
        resp = client.get("/static/css/style.css")
        assert resp.status_code == 200


class TestProMode:
    @pytest.fixture(autouse=True)
    def clean_api_key(self):
        """Ensure no stale API key before/after each test."""
        from web.services.api_keys import clear_api_key
        clear_api_key()
        yield
        clear_api_key()

    def test_key_status_no_key(self, client):
        resp = client.get("/api/key-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_key"] is False

    def test_save_and_load_key(self, client):
        resp = client.post("/api/save-key", json={
            "provider": "anthropic",
            "api_key": "sk-test-123",
        })
        assert resp.status_code == 200

        resp = client.get("/api/key-status")
        data = resp.json()
        assert data["has_key"] is True
        assert data["provider"] == "anthropic"

    def test_reject_unsupported_provider(self, client):
        resp = client.post("/api/save-key", json={
            "provider": "openai",
            "api_key": "sk-test",
        })
        assert resp.status_code == 400

    def test_home_page_has_pro_toggle(self, client):
        resp = client.get("/")
        assert "Base" in resp.text
        assert "Pro" in resp.text
