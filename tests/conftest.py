import pytest

from app import create_app, db
from config import Config


class TestConfig(Config):
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    TESTING = True
    WTF_CSRF_ENABLED = False
    ANTHROPIC_API_KEY = None  # tests opt in explicitly; never inherit the env


@pytest.fixture
def app():
    app = create_app(TestConfig)
    yield app
    with app.app_context():
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    client.post(
        '/register',
        data={
            'username': 'testuser',
            'email': 'test@example.com',
            'password': 'testpassword123',
        },
    )
    client.post(
        '/login',
        data={
            'username': 'testuser',
            'password': 'testpassword123',
        },
    )
    return client
