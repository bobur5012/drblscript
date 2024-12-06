# config.py
import os
from datetime import timedelta

class Config:
    """Базовый класс конфигурации"""
    
    
    CORS_RESOURCES = {
            r"/api/*": {
                "origins": "*",
                "methods": ["GET", "POST", "PUT", "DELETE"],
                "allow_headers": ["Content-Type", "Authorization"]
            }
        }
    # Настройки Flask
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    DEBUG = False
    TESTING = False
    
    SQLALCHEMY_DATABASE_URI = 'sqlite:///viewer.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Логирование
    LOG_LEVEL = 'DEBUG'
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_FILE = 'app.log'
    
    # Настройки логирования
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    LOG_FILE = 'viewer.log'
    LOG_LEVEL = 'INFO'
    
    # Настройки API
    API_BASE_URL = 'https://dbauto.site/api'
    API_TIMEOUT = 30
    API_RETRY_ATTEMPTS = 3
    API_RETRY_DELAY = 5
    
    # Настройки прокси
    PROXY_CHECK_TIMEOUT = 10
    PROXY_BAN_DURATION = 3600  # 1 час
    MAX_PROXY_FAILS = 3
    PROXY_ROTATION_INTERVAL = 300  # 5 минут
    
    # Настройки просмотров
    MIN_VIEW_TIME = 20
    MAX_VIEW_TIME = 40
    VIEWS_PER_IP = 1
    MAX_VIEWS_PER_SHOT = 35
    PAUSE_BETWEEN_VIEWS = 15
    
    # Настройки задач
    MAX_THREADS = 50
    TASK_INTERVAL_HOURS = 4
    DAILY_VIEW_LIMIT = 100000
    
    # Настройки сессии
    SESSION_TYPE = 'filesystem'
    PERMANENT_SESSION_LIFETIME = timedelta(days=31)
    
    # Настройки кеширования
    CACHE_TYPE = 'simple'
    CACHE_DEFAULT_TIMEOUT = 300

class DevelopmentConfig(Config):
    """Конфигурация для разработки"""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'
    
    # Дополнительные настройки для разработки
    SQLALCHEMY_ECHO = True
    TEMPLATES_AUTO_RELOAD = True

class TestingConfig(Config):
    """Конфигурация для тестирования"""
    TESTING = True
    DEBUG = True
    
    # Тестовая база данных
    SQLALCHEMY_DATABASE_URI = 'sqlite:///test.db'
    
    # Уменьшенные интервалы для тестирования
    MIN_VIEW_TIME = 2
    MAX_VIEW_TIME = 5
    PAUSE_BETWEEN_VIEWS = 2
    PROXY_ROTATION_INTERVAL = 30

class ProductionConfig(Config):
    """Конфигурация для продакшена"""
    DEBUG = False
    LOG_LEVEL = 'ERROR'
    
    # Настройки безопасности
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # Настройки прокси для продакшена
    PROXY_CHECK_TIMEOUT = 20
    PROXY_BAN_DURATION = 7200  # 2 часа
    MAX_PROXY_FAILS = 5
    
    # Оптимизированные интервалы
    MIN_VIEW_TIME = 25
    MAX_VIEW_TIME = 45
    PAUSE_BETWEEN_VIEWS = 20

config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Получение конфигурации на основе переменной окружения"""
    env = os.environ.get('FLASK_ENV', 'default')
    return config.get(env, config['default'])

