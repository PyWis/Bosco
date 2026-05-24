import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///bosco.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = True

    # Game
    TURN_DURATION_MINUTES = int(os.getenv('TURN_DURATION_MINUTES', 10))

    # SuperAdmin
    SUPERADMIN_USER     = os.getenv('SUPERADMIN_USER',     'SuperAdmin')
    SUPERADMIN_EMAIL    = os.getenv('SUPERADMIN_EMAIL',    'bosco@kjxii.test')
    SUPERADMIN_PASSWORD = os.getenv('SUPERADMIN_PASSWORD', 'bosco123!')
