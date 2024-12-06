from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
import json

db = SQLAlchemy()

class LikeAccount(db.Model):
    """Модель аккаунта Dribbble"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    shots_count = db.Column(db.Integer, default=0)
    last_update = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Связи
    shots = db.relationship('Shot', backref='account', lazy='dynamic')
    
    def update_shots_count(self):
        """Обновляет количество шотов для аккаунта"""
        self.shots_count = self.shots.count()
        self.last_update = datetime.now(timezone.utc)
        return self.shots_count

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'name': self.name,
            'shots_count': self.shots_count,
            'last_update': self.last_update.isoformat() if self.last_update else None
        }

class Shot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_name = db.Column(db.String(255), nullable=True)
    dribbble_id = db.Column(db.String(255), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    image_url = db.Column(db.String(512), nullable=True)
    url = db.Column(db.String(512), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('like_account.id'))
    target_views = db.Column(db.Integer, default=0)
    current_views = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default="pending", index=True)
    
    # Метрики и статистика
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    last_view_at = db.Column(db.DateTime, nullable=True)
    views_per_hour = db.Column(db.Float, default=0.0)
    failed_attempts = db.Column(db.Integer, default=0)
    successful_attempts = db.Column(db.Integer, default=0)
    daily_views_quota = db.Column(db.Integer, default=35)

    def calculate_views_per_hour(self) -> float:
        """Рассчитывает среднюю скорость просмотров"""
        if not self.started_at or not self.last_view_at:
            return 0.0
        
        hours = (self.last_view_at - self.started_at).total_seconds() / 3600
        return round(self.current_views / hours, 2) if hours > 0 else 0.0

    def update_status(self):
        """Обновляет статус на основе прогресса"""
        if self.current_views >= self.target_views:
            self.status = "completed"
            self.completed_at = datetime.now(timezone.utc)
        elif self.current_views > 0:
            self.status = "active"
            if not self.started_at:
                self.started_at = datetime.now(timezone.utc)
        else:
            self.status = "pending"

    def can_add_view(self) -> bool:
        """Проверяет возможность добавления просмотра"""
        if self.status == "completed":
            return False
            
        today = datetime.now(timezone.utc).date()
        today_views = ViewerLog.query.filter(
            ViewerLog.shot_id == self.id,
            ViewerLog.status == 'success',
            db.func.date(ViewerLog.timestamp) == today
        ).count()
        
        return today_views < self.daily_views_quota

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'dribbble_id': self.dribbble_id,
            'title': self.title,
            'image_url': self.image_url,
            'url': self.url,
            'account_id': self.account_id,
            'target_views': self.target_views,
            'current_views': self.current_views,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'last_view_at': self.last_view_at.isoformat() if self.last_view_at else None,
            'views_per_hour': self.views_per_hour,
            'progress': (self.current_views / self.target_views * 100) if self.target_views > 0 else 0,
            'daily_views_quota': self.daily_views_quota
        }

class Proxy(db.Model):
    """Модель прокси-сервера"""
    id = db.Column(db.Integer, primary_key=True)
    proxy = db.Column(db.String(255), unique=True, nullable=False, index=True)
    status = db.Column(db.String(50), default="unchecked", index=True)
    
    # Метрики производительности
    speed = db.Column(db.Float, nullable=True)
    success_count = db.Column(db.Integer, default=0)
    fail_count = db.Column(db.Integer, default=0)
    last_success = db.Column(db.DateTime, nullable=True)
    last_failure = db.Column(db.DateTime, nullable=True)
    last_checked = db.Column(db.DateTime, nullable=True)
    average_response_time = db.Column(db.Float, default=0.0)
    
    # Контроль нагрузки
    current_threads = db.Column(db.Integer, default=0)
    max_threads = db.Column(db.Integer, default=5)
    is_banned = db.Column(db.Boolean, default=False)
    banned_until = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.String(512), nullable=True)
    last_ip = db.Column(db.String(50), nullable=True)

    def is_available(self) -> bool:
        """Проверяет доступность прокси"""
        if self.is_banned and self.banned_until:
            if datetime.now(timezone.utc) > self.banned_until:
                self.is_banned = False
                self.banned_until = None
                return True
            return False
        return (
            self.status == "active" and
            not self.is_banned and
            self.current_threads < self.max_threads
        )

    def update_stats(self, success: bool, response_time: float = None):
        """Обновляет статистику использования"""
        now = datetime.now(timezone.utc)
        if success:
            self.success_count += 1
            self.last_success = now
            if response_time:
                self.average_response_time = (
                    (self.average_response_time + response_time) / 2 
                    if self.average_response_time 
                    else response_time
                )
        else:
            self.fail_count += 1
            self.last_failure = now

    def ban(self, duration: int = 3600):
        """Временно блокирует прокси"""
        self.is_banned = True
        self.banned_until = datetime.now(timezone.utc) + timedelta(seconds=duration)
        self.status = "banned"

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'proxy': self.proxy,
            'status': self.status,
            'speed': self.speed,
            'success_count': self.success_count,
            'fail_count': self.fail_count,
            'last_success': self.last_success.isoformat() if self.last_success else None,
            'last_failure': self.last_failure.isoformat() if self.last_failure else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'average_response_time': self.average_response_time,
            'current_threads': self.current_threads,
            'max_threads': self.max_threads,
            'is_banned': self.is_banned,
            'banned_until': self.banned_until.isoformat() if self.banned_until else None,
            'last_error': self.last_error,
            'last_ip': self.last_ip
        }

class ViewerSettings(db.Model):
    """Модель настроек системы"""
    id = db.Column(db.Integer, primary_key=True)
    
    # Настройки просмотров
    min_view_time = db.Column(db.Integer, default=20)
    max_view_time = db.Column(db.Integer, default=40)
    views_per_ip = db.Column(db.Integer, default=1)
    max_views_per_shot = db.Column(db.Integer, default=35)
    pause_between_views = db.Column(db.Integer, default=15)
    
    # Настройки задач
    max_threads = db.Column(db.Integer, default=50)
    task_interval_hours = db.Column(db.Integer, default=4)
    daily_view_limit = db.Column(db.Integer, default=100000)
    
    # Настройки прокси
    proxy_timeout = db.Column(db.Integer, default=30)
    max_proxy_fails = db.Column(db.Integer, default=3)
    proxy_ban_duration = db.Column(db.Integer, default=3600)
    proxy_rotation_interval = db.Column(db.Integer, default=300)
    max_threads_per_proxy = db.Column(db.Integer, default=5)

    @staticmethod
    def get_settings():
        """Получение текущих настроек"""
        settings = ViewerSettings.query.first()
        if not settings:
            settings = ViewerSettings()
            db.session.add(settings)
            db.session.commit()
        return settings

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'min_view_time': self.min_view_time,
            'max_view_time': self.max_view_time,
            'views_per_ip': self.views_per_ip,
            'max_views_per_shot': self.max_views_per_shot,
            'pause_between_views': self.pause_between_views,
            'max_threads': self.max_threads,
            'task_interval_hours': self.task_interval_hours,
            'daily_view_limit': self.daily_view_limit,
            'proxy_timeout': self.proxy_timeout,
            'max_proxy_fails': self.max_proxy_fails,
            'proxy_ban_duration': self.proxy_ban_duration,
            'proxy_rotation_interval': self.proxy_rotation_interval,
            'max_threads_per_proxy': self.max_threads_per_proxy
        }

class ViewerLog(db.Model):
    """Модель логов просмотров"""
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    
    # Связи
    shot_id = db.Column(db.Integer, db.ForeignKey('shot.id'), nullable=True)
    proxy_id = db.Column(db.Integer, db.ForeignKey('proxy.id'), nullable=True)
    task_id = db.Column(db.Integer, db.ForeignKey('viewer_task.id'), nullable=True)
    
    # Данные события
    action = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    details = db.Column(db.String(512), nullable=True)
    response_time = db.Column(db.Float, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'shot_id': self.shot_id,
            'proxy_id': self.proxy_id,
            'task_id': self.task_id,
            'action': self.action,
            'status': self.status,
            'details': self.details,
            'response_time': self.response_time,
            'ip_address': self.ip_address
        }

class ViewerTask(db.Model):
    """Модель задачи просмотров"""
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(255), nullable=False, unique=True)
    title = db.Column(db.String(255), nullable=False)
    
    # Параметры выполнения
    total_views = db.Column(db.Integer, nullable=False)
    current_views = db.Column(db.Integer, default=0)
    views_per_ip = db.Column(db.Integer, nullable=False)
    threads_count = db.Column(db.Integer, nullable=False)
    pause_between_views = db.Column(db.Integer, nullable=False)
    
    # Статус и время
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    next_run_at = db.Column(db.DateTime, nullable=True)
    
    # Связи
    shots = db.relationship('Shot', secondary='task_shots', backref='tasks')
    logs = db.relationship('ViewerLog', backref='task', lazy='dynamic')

    def calculate_progress(self) -> float:
        """Рассчитывает прогресс выполнения"""
        return (self.current_views / self.total_views * 100) if self.total_views > 0 else 0

    def update_status(self):
        """Обновляет статус задачи"""
        if self.current_views >= self.total_views:
            self.status = 'completed'
            self.completed_at = datetime.now(timezone.utc)
        elif self.current_views > 0:
           self.status = 'active'
        if not self.started_at:
                self.started_at = datetime.now(timezone.utc)
        else:
            self.status = 'pending'

    def schedule_next_run(self, hours: int = None):
        """Планирование следующего запуска"""
        if not hours:
            settings = ViewerSettings.get_settings()
            hours = settings.task_interval_hours
        self.next_run_at = datetime.now(timezone.utc) + timedelta(hours=hours)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация в словарь"""
        return {
            'id': self.id,
            'uid': self.uid,
            'title': self.title,
            'total_views': self.total_views,
            'current_views': self.current_views,
            'views_per_ip': self.views_per_ip,
            'threads_count': self.threads_count,
            'pause_between_views': self.pause_between_views,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'next_run_at': self.next_run_at.isoformat() if self.next_run_at else None,
            'progress': self.calculate_progress(),
            'shots': [shot.to_dict() for shot in self.shots]
        }

# Связь many-to-many между задачами и шотами
task_shots = db.Table('task_shots',
    db.Column('task_id', db.Integer, db.ForeignKey('viewer_task.id')),
    db.Column('shot_id', db.Integer, db.ForeignKey('shot.id'))
)

def init_db(app):
    """Инициализация базы данных"""
    with app.app_context():
        db.create_all()
        # Создаем настройки по умолчанию, если их нет
        settings = ViewerSettings.get_settings()
        
        # Проверяем и обновляем статусы
        try:
            # Сбрасываем зависшие задачи
            stuck_tasks = ViewerTask.query.filter(
                ViewerTask.status.in_(['active', 'pending']),
                ViewerTask.created_at < datetime.now(timezone.utc) - timedelta(days=1)
            ).all()
            
            for task in stuck_tasks:
                task.status = 'failed'
            
            # Сбрасываем счетчики потоков прокси
            proxies = Proxy.query.filter(Proxy.current_threads > 0).all()
            for proxy in proxies:
                proxy.current_threads = 0
            
            db.session.commit()
            
        except Exception as e:
            db.session.rollback()
            raise Exception(f"Error during database initialization: {str(e)}")

class TaskMetrics:
    """Класс для работы с метриками задач"""
    @staticmethod
    def get_daily_stats(date: datetime = None) -> Dict[str, Any]:
        """Получение статистики за день"""
        if not date:
            date = datetime.now(timezone.utc)

        start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        successful_views = ViewerLog.query.filter(
            ViewerLog.timestamp >= start_of_day,
            ViewerLog.timestamp < end_of_day,
            ViewerLog.status == 'success'
        ).count()

        failed_views = ViewerLog.query.filter(
            ViewerLog.timestamp >= start_of_day,
            ViewerLog.timestamp < end_of_day,
            ViewerLog.status == 'error'
        ).count()

        total_tasks = ViewerTask.query.filter(
            ViewerTask.created_at >= start_of_day,
            ViewerTask.created_at < end_of_day
        ).count()

        completed_tasks = ViewerTask.query.filter(
            ViewerTask.completed_at >= start_of_day,
            ViewerTask.completed_at < end_of_day,
            ViewerTask.status == 'completed'
        ).count()

        return {
            'date': date.date().isoformat(),
            'successful_views': successful_views,
            'failed_views': failed_views,
            'total_tasks': total_tasks,
            'completed_tasks': completed_tasks,
            'success_rate': (successful_views / (successful_views + failed_views) * 100) 
                          if (successful_views + failed_views) > 0 else 0
        }

    @staticmethod
    def get_proxy_stats(days: int = 7) -> List[Dict[str, Any]]:
        """Получение статистики прокси за период"""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        proxies = Proxy.query.all()
        stats = []
        
        for proxy in proxies:
            success_count = ViewerLog.query.filter(
                ViewerLog.proxy_id == proxy.id,
                ViewerLog.timestamp >= start_date,
                ViewerLog.status == 'success'
            ).count()
            
            fail_count = ViewerLog.query.filter(
                ViewerLog.proxy_id == proxy.id,
                ViewerLog.timestamp >= start_date,
                ViewerLog.status == 'error'
            ).count()
            
            avg_response = db.session.query(
                db.func.avg(ViewerLog.response_time)
            ).filter(
                ViewerLog.proxy_id == proxy.id,
                ViewerLog.timestamp >= start_date,
                ViewerLog.response_time.isnot(None)
            ).scalar()
            
            stats.append({
                'proxy_id': proxy.id,
                'proxy': proxy.proxy,
                'success_count': success_count,
                'fail_count': fail_count,
                'average_response': float(avg_response) if avg_response else 0,
                'success_rate': (success_count / (success_count + fail_count) * 100)
                               if (success_count + fail_count) > 0 else 0
            })
        
        return stats

    @staticmethod
    def get_shot_view_history(shot_id: int, days: int = 7) -> List[Dict[str, Any]]:
        """Получение истории просмотров шота"""
        start_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        daily_views = db.session.query(
            db.func.date(ViewerLog.timestamp).label('date'),
            db.func.count().label('views')
        ).filter(
            ViewerLog.shot_id == shot_id,
            ViewerLog.timestamp >= start_date,
            ViewerLog.status == 'success'
        ).group_by(
            db.func.date(ViewerLog.timestamp)
        ).all()
        
        return [{
            'date': date.isoformat(),
            'views': views
        } for date, views in daily_views]