import pytest
from io import BytesIO
from flask import Flask

from govuk_ai_accelerator_app import create_app
from scripts.pipeline.utils import is_yaml_file, error_response


@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHealthCheck:
    """Test health check endpoints."""
    
    def test_health_check_ready(self, client):
        """Test /healthcheck/ready endpoint."""
        response = client.get('/healthcheck/ready')
        assert response.status_code == 200
        assert response.json['status'] == 'healthy'


class TestOntologyEndpoints:
    
    def test_index_page_loads(self, client):
        response = client.get('/ontology/')
        assert response.status_code == 200
    
    def test_submit_without_file(self, client):
        response = client.post('/ontology/submit')
        assert response.status_code == 400
        assert 'error' in response.json

    def test_job_lifecycle(self, client, app):
        yaml_content = b"version: {}\npath: {}\n"  
        data = {
            'file': (BytesIO(yaml_content), 'config.yaml')
        }
        response = client.post('/ontology/submit', data=data, content_type='multipart/form-data')
        assert response.status_code == 202
        body = response.get_json()
        assert 'job_id' in body
        job_id = body['job_id']

        status_resp = client.get(f'/ontology/status/{job_id}')
        assert status_resp.status_code == 200
        assert status_resp.get_json()['status'] in ('pending', 'completed', 'failed')

    def test_submit_with_db_down(self, client, app, monkeypatch):
        """If the database raises OperationalError during job creation, the
        endpoint should still accept the file and return a warning in the
        payload instead of raising an error."""
        from sqlalchemy.exc import OperationalError

        def boom(*args, **kwargs):
            raise OperationalError("test", None, None)

        # monkeypatch the session methods used in upload_file without breaking
        # the session object itself (avoids teardown errors)
        import govuk_ai_accelerator_app
        monkeypatch.setattr(govuk_ai_accelerator_app.db.session, 'add', boom)
        monkeypatch.setattr(govuk_ai_accelerator_app.db.session, 'commit', boom)

        yaml_content = b"version: {}\npath: {}\n"  
        data = {
            'file': (BytesIO(yaml_content), 'config.yaml')
        }
        response = client.post('/ontology/submit', data=data, content_type='multipart/form-data')
        assert response.status_code == 202
        body = response.get_json()
        assert 'job_id' in body
        assert 'warning' in body
        assert 'database unavailable' in body['warning']


class TestUtilityFunctions:
    
    def test_is_yaml_file_valid(self):
        assert is_yaml_file('config.yaml') is True
        assert is_yaml_file('config.yml') is True
    
    def test_is_yaml_file_invalid(self):
        assert is_yaml_file('config.txt') is False
        assert is_yaml_file('') is False
        assert is_yaml_file(None) is False
    
    def test_error_response(self, app):
        with app.app_context():
            response = error_response("Test error")
            assert hasattr(response, 'status_code')
            assert response.status_code == 400
            assert b"Test error" in response.get_data()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
 