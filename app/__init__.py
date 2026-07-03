import json
import os

from flask import Flask
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'main.login'
csrf = CSRFProtect()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

    with open(os.path.join(data_dir, 'routine_data.json')) as f:
        app.config['ROUTINE_DATA'] = json.load(f)

    with open(os.path.join(data_dir, 'progressions.json')) as f:
        app.config['PROGRESSION_DATA'] = json.load(f)

    with open(os.path.join(data_dir, 'gym_routine.json')) as f:
        app.config['GYM_ROUTINE_DATA'] = json.load(f)

    from app.routes import main

    app.register_blueprint(main)

    # Create tables on startup — run.py is bypassed under gunicorn
    with app.app_context():
        db.create_all()

    return app
