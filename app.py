from flask import Flask, render_template, jsonify, request, current_app
from flask_migrate import Migrate
import asyncio
from proxy_manager import ProxyManager
from task_manager import TaskManager
import logging
import traceback
from database import db, Shot, ViewerSettings, ViewerLog, Proxy, LikeAccount, ViewerTask, init_db
from datetime import datetime, timedelta, timezone
from asgiref.wsgi import WsgiToAsgi
import nest_asyncio
import httpx
from functools import wraps
from flask_cors import CORS
import uuid
from queue import Queue
from viewer_session import ViewerSession
import os
from config import Config


app = Flask(__name__, 
    static_url_path='/static',
    static_folder='static',
    template_folder='templates'
)
nest_asyncio.apply()

app.config.from_object(Config)

# Конфигурация базы данных
app.config['SQLALCHEMY_DATABASE_URI']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
migrate = Migrate(app, db)


# Настройка логирования
logging.basicConfig(
    level=app.config['LOG_LEVEL'],
    format=app.config['LOG_FORMAT'],
    handlers=[
        logging.FileHandler(app.config['LOG_FILE']),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

CORS(app, resources=app.config['CORS_RESOURCES'])

# Настройка сессии для API dbauto.site
DBAUTOMATION_SESSION = '_dbautomation_session=arWwqxwjnV88I5a4LCsBL0cyLspjsZ%2FQHIQwyUTaqDv9%2Fe9wjo0XGyNxlBY36XU9WyzTsD3SM9qBtzYNhghrwgPzdqmoZC0zIkRWTuYJK%2BGDeMtlK8A3ZtuYRR3Tegb09yIs68HIWdBG5OWDfRM0LZxdHI40G7m5%2FC5hdbDkcu3vSsVOA5bsZG6hw%2Fh1lLqP3Mx3L4e1zZO9KqRgx%2BMFWbmB1i9IdmLAnEuHyXoslUJqkz0lMspVbDAe0VUAyskq82rQ0Pf9qbA4v%2BQANSXDA9Q85UmEuNNwDNYtLcDXboJQcAf%2Be6VyCa07pR7q5e3U%2FfFuEj7TUakRXFaE3yvOBBNBErU4SPXtop4Xl1BGMUpOfBs4sf99S6uftyvX1Av91lycgIyP82Q5XxiBztM2bY45%2FcwwIXg8NYsw3k5X%2BDln30qlgl5lTi8DnAqVK5djUP%2Fc2uc%3D--o%2F%2BBQX3N1W6bxS9I--tAXe4HuyMchMx%2FVqnS1gGw%3D%3D'

DEFAULT_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9,ru;q=0.8",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "cookie": DBAUTOMATION_SESSION
}



# Настройка CORS
CORS(app, resources={
    r"/api/*": {
        "origins": "*",
        "methods": ["GET", "POST", "PUT", "DELETE"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})


# Глобальные менеджеры
task_manager = None
proxy_manager = None

def init_managers():
    """Инициализация менеджеров"""
    global task_manager, proxy_manager
    if proxy_manager is None:
        proxy_manager = ProxyManager()
    if task_manager is None:
        task_manager = TaskManager()

def handle_errors(f):
    """Декоратор для обработки ошибок в API"""
    @wraps(f)
    async def decorated_function(*args, **kwargs):
        try:
            return await f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {str(e)}\n{traceback.format_exc()}")
            return jsonify({
                "status": "error", 
                "message": str(e),
                "error_type": type(e).__name__
            }), 500
    return decorated_function

@app.route('/')
def index():
    """Главная страница"""
    return render_template('index.html')


@app.route('/api/tasks/active', methods=['GET'])
def get_active_tasks():
    try:
        tasks = ViewerTask.query.filter_by(status='active').all()
        return jsonify([{
            "id": task.id,
            "url": task.shot.url,  # Предполагается, что у ViewerTask есть связь с Shot
            "completed_views": task.completed_views,
            "total_views": task.total_views,
            "proxy": task.proxy
        } for task in tasks])
    except Exception as e:
        current_app.logger.error(f"Ошибка получения активных задач: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/proxies', methods=['GET'])
@handle_errors
async def get_proxies():
    """Получение списка прокси"""
    proxies = Proxy.query.all()
    return jsonify([proxy.to_dict() for proxy in proxies])

@app.route('/api/proxies/upload', methods=['POST'])
@handle_errors
async def upload_proxies():
    """Загрузка новых прокси"""
    data = request.json
    proxies = data.get('proxies', [])

    if not proxies or not isinstance(proxies, list):
        return jsonify({"status": "error", "message": "Invalid proxies format"}), 400

    results = await proxy_manager.add_proxies(proxies)
    return jsonify({"status": "success", "results": results})


@app.route('/api/proxies/check', methods=['POST'])
@handle_errors
async def check_proxies():
    """Проверка прокси"""
    results = await proxy_manager.check_all_proxies()
    return jsonify({"status": "success", "results": results})

@app.route('/api/proxies/<int:proxy_id>', methods=['DELETE'])
@handle_errors
async def delete_proxy(proxy_id):
    """Удаление прокси"""
    proxy = Proxy.query.get_or_404(proxy_id)
    db.session.delete(proxy)
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/shots', methods=['GET'])
@handle_errors
async def get_shots():
    """Получение списка шотов"""
    shots = Shot.query.all()
    return jsonify([shot.to_dict() for shot in shots])

@app.route('/api/shots/<int:shot_id>', methods=['GET'])
@handle_errors
async def get_shot(shot_id):
    """Получение информации о конкретном шоте"""
    shot = Shot.query.get_or_404(shot_id)
    return jsonify(shot.to_dict())

@app.route('/api/tasks/create', methods=['POST'])
async def create_task():
    try:
        data = request.json

        # Получаем ссылки на шоты
        shot_urls = data.get('shot_urls')
        total_views = data.get('total_views', 100)  # Количество просмотров
        threads_count = data.get('threads_count', 10)  # Количество потоков

        if not shot_urls:
            return jsonify({"status": "error", "message": "Missing shot URLs"}), 400

        # Логируем полученные данные
        current_app.logger.info(f"Получены ссылки на шоты: {shot_urls}")

        # Инициализация ProxyManager
        proxy_manager = ProxyManager()

        # Выполняем ротацию прокси и создаём задачу
        tasks = []
        for url in shot_urls:
            proxy = await proxy_manager.get_working_proxy()  # Асинхронное получение рабочего прокси
            if not proxy:
                return jsonify({"status": "error", "message": "No available proxies"}), 400

            task = {
                "url": url,
                "proxy": proxy.proxy,  # Используем атрибут proxy
                "total_views": total_views,
                "threads_count": threads_count
            }
            tasks.append(task)

            # Логируем задачу
            current_app.logger.info(f"Создана задача: {task}")

        # Здесь можно добавить задачи в очередь для выполнения, например через Celery или другую систему
        return jsonify({"status": "success", "tasks": tasks})
    except Exception as e:
        current_app.logger.error(f"Ошибка при создании задачи: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/tasks/<int:task_id>/stop', methods=['POST'])
@handle_errors
async def stop_task(task_id):
    """Остановка задачи"""
    success = await task_manager.stop_task(task_id)
    return jsonify({
        "status": "success" if success else "error",
        "message": "Task stopped" if success else "Failed to stop task"
    })

@app.route('/api/stats', methods=['GET'])
@handle_errors
async def get_stats():
    """Получение общей статистики"""
    total_shots = Shot.query.count()
    active_shots = Shot.query.filter_by(status='active').count()
    total_views = db.session.query(db.func.sum(Shot.current_views)).scalar() or 0
    completed_shots = Shot.query.filter_by(status='completed').count()
    
    # Рассчитываем статистику за последние 7 дней
    seven_days_ago = datetime.now() - timedelta(days=7)
    daily_views = db.session.query(
        db.func.date(ViewerLog.timestamp),
        db.func.count(ViewerLog.id)
    ).filter(
        ViewerLog.timestamp >= seven_days_ago,
        ViewerLog.status == 'success'
    ).group_by(
        db.func.date(ViewerLog.timestamp)
    ).all()
    
    return jsonify({
        "total_shots": total_shots,
        "active_shots": active_shots,
        "completed_shots": completed_shots,
        "total_views": total_views,
        "success_rate": round((completed_shots / total_shots * 100), 2) if total_shots > 0 else 0,
        "daily_views": [{"date": str(date), "views": views} for date, views in daily_views]
    })

@app.route('/api/logs', methods=['GET'])
@handle_errors
async def get_logs():
    """Получение логов"""
    limit = min(int(request.args.get('limit', 100)), 1000)
    logs = ViewerLog.query.order_by(ViewerLog.timestamp.desc()).limit(limit).all()
    return jsonify([log.to_dict() for log in logs])

@app.route('/api/settings', methods=['GET'])
@handle_errors
async def get_settings():
    """Получение настроек"""
    settings = ViewerSettings.get_settings()
    return jsonify(settings.to_dict())

@app.route('/api/settings/save', methods=['POST'])
@handle_errors
async def save_settings():
    """Сохранение настроек"""
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data provided"}), 400

    settings = ViewerSettings.get_settings()
    for key, value in data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    
    db.session.commit()
    return jsonify({"status": "success"})

@app.route('/api/like_accounts/update', methods=['POST'])
async def update_like_accounts():
    """Синхронизация аккаунтов и шотов из внешнего API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{Config.API_BASE_URL}/like_accounts",
                headers=DEFAULT_HEADERS,
            )
            response.raise_for_status()
            accounts_data = response.json()

            for account_data in accounts_data:
                # Проверяем, существует ли аккаунт в базе
                account = LikeAccount.query.get(account_data["id"])
                if not account:
                    account = LikeAccount(
                        id=account_data["id"],
                        name=account_data["name"],
                        shots_count=account_data["shots_count"],
                        last_update=datetime.utcnow(),
                    )
                    db.session.add(account)
                else:
                    account.name = account_data["name"]
                    account.shots_count = account_data["shots_count"]
                    account.last_update = datetime.utcnow()

                # Обрабатываем шоты
                for shot_data in account_data.get("shots", []):
                    shot = Shot.query.filter_by(dribbble_id=shot_data["id"]).first()
                    if not shot:
                        shot = Shot(
                            dribbble_id=shot_data["id"],
                            title=shot_data.get("title", "").strip(),
                            image_url=shot_data.get("image_url"),
                            url=shot_data.get("url"),
                            account_id=account.id,
                            status="pending",
                        )
                        db.session.add(shot)
                    else:
                        shot.title = shot_data.get("title", "").strip()
                        shot.image_url = shot_data.get("image_url")
                        shot.url = shot_data.get("url")
                        shot.account_id = account.id

            db.session.commit()
            return jsonify({"status": "success", "message": "Accounts and shots updated successfully"})
    except Exception as e:
        current_app.logger.error(f"Ошибка обновления аккаунтов: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/like_accounts/cached', methods=['GET'])
def get_cached_like_accounts():
    """Получение аккаунтов и шотов из базы данных"""
    try:
        accounts = LikeAccount.query.all()
        data = [{
            "id": account.id,
            "name": account.name,
            "shots_count": account.shots_count,
            "last_update": account.last_update.isoformat(),
            "shots": [shot.to_dict() for shot in account.shots],
        } for account in accounts]

        return jsonify(data)
    except Exception as e:
        current_app.logger.error(f"Ошибка получения данных из базы: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/api/like_accounts/<int:account_id>/shots/list', methods=['GET'])
@handle_errors
async def get_account_shots_proxy(account_id):
    """Получение и сохранение шотов аккаунта"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f'https://dbauto.site/api/like_accounts/{account_id}/shots',
                headers=DEFAULT_HEADERS
            )
            response.raise_for_status()
            data = response.json()

            if 'shots' in data:
                for shot_data in data['shots']:
                    if shot_data.get('image_url') and not shot_data['image_url'].startswith('http'):
                        shot_data['image_url'] = f"https://dbauto.site{shot_data['image_url']}"

                    # Сохранение шотов
                    shot = Shot.query.filter_by(dribbble_id=shot_data['id']).first()
                    if shot:
                        shot.title = shot_data.get('title', '').strip()
                        shot.image_url = shot_data.get('image_url', '')
                        shot.url = shot_data.get('url', '')
                        shot.account_id = account_id
                    else:
                        shot = Shot(
                            dribbble_id=shot_data['id'],
                            title=shot_data.get('title', '').strip(),
                            image_url=shot_data.get('image_url', ''),
                            url=shot_data.get('url', ''),
                            account_id=account_id,
                            status='pending'
                        )
                        db.session.add(shot)

                # Коммит изменений
                db.session.commit()

            return jsonify(data)

    except Exception as e:
        logger.error(f"Error fetching shots: {str(e)}\n{traceback.format_exc()}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route('/api/viewer/start', methods=['POST'])
@handle_errors
async def start_viewer_session():
    """Запуск сессии просмотров"""
    try:
        data = request.json
        if not data or 'urls' not in data or 'views_target' not in data:
            return jsonify({
                "status": "error",
                "message": "Missing required parameters"
            }), 400

        session_id = await task_manager.create_viewer_session(data)
        if not session_id:
            return jsonify({
                "status": "error",
                "message": "Failed to create viewer session"
            }), 500

        return jsonify({
            "status": "success",
            "session_id": session_id
        })

    except Exception as e:
        logger.error(f"Error starting viewer session: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route('/api/viewer/status/<session_id>', methods=['GET'])
@handle_errors
async def get_viewer_session_status(session_id):
    """Получение статуса сессии просмотров"""
    status = await task_manager.get_session_status(session_id)
    if not status:
        return jsonify({
            "status": "error",
            "message": f"Session {session_id} not found"
        }), 404

    return jsonify({
        "status": "success",
        "data": status
    })

@app.route('/api/viewer/stop/<session_id>', methods=['POST'])
@handle_errors
async def stop_viewer_session(session_id):
    """Остановка сессии просмотров"""
    if session_id in task_manager.active_sessions:
        session = task_manager.active_sessions[session_id]
        session.stop()
        del task_manager.active_sessions[session_id]
        return jsonify({
            "status": "success",
            "message": f"Session {session_id} stopped successfully"
        })
    return jsonify({
        "status": "error",
        "message": f"Session {session_id} not found"
    }), 404

@app.route('/api/tasks/status', methods=['GET'])
@handle_errors
async def get_tasks_status():
    """Получение статуса всех задач"""
    status = await task_manager.get_tasks_status()
    return jsonify(status)

@app.route('/api/tasks/<int:task_id>/stats', methods=['GET'])
@handle_errors
async def get_task_stats(task_id):
    """Получение статистики конкретной задачи"""
    task = ViewerTask.query.get_or_404(task_id)
    
    total_views = sum(shot.current_views for shot in task.shots)
    progress = (total_views / task.total_views * 100) if task.total_views > 0 else 0
    
    return jsonify({
        "task_id": task.id,
        "total_views": total_views,
        "target_views": task.total_views,
        "progress": round(progress, 2),
        "status": task.status,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "shots_stats": [{
            "shot_id": shot.id,
            "views": shot.current_views,
            "target": shot.target_views,
            "progress": round((shot.current_views / shot.target_views * 100), 2) if shot.target_views > 0 else 0
        } for shot in task.shots]
    })

@app.route('/api/system/status', methods=['GET'])
@handle_errors
async def get_system_status():
    """Получение статуса системы"""
    try:
        # Статистика прокси
        total_proxies = Proxy.query.count()
        active_proxies = Proxy.query.filter_by(status='active', is_banned=False).count()
        banned_proxies = Proxy.query.filter_by(is_banned=True).count()

        # Статистика задач
        total_tasks = ViewerTask.query.count()
        active_tasks = ViewerTask.query.filter_by(status='active').count()
        completed_tasks = ViewerTask.query.filter_by(status='completed').count()
        failed_tasks = ViewerTask.query.filter_by(status='failed').count()

        # Активные сессии
        active_sessions = len(task_manager.active_sessions) if task_manager else 0

        return jsonify({
            "status": "success",
            "system_time": datetime.now().isoformat(),
            "proxies": {
                "total": total_proxies,
                "active": active_proxies,
                "banned": banned_proxies
            },
            "tasks": {
                "total": total_tasks,
                "active": active_tasks,
                "completed": completed_tasks,
                "failed": failed_tasks
            },
            "sessions": {
                "active": active_sessions
            },
            "managers_status": {
                "task_manager": task_manager.is_running if task_manager else False,
                "proxy_manager": proxy_manager is not None
            }
        })
    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        return jsonify({
            "status": "error",
            "message": "Failed to get system status"
        }), 500


@app.teardown_appcontext
def teardown_appcontext(exception=None):
    """Очистка при завершении контекста приложения"""
    if task_manager and task_manager.is_running:
        task_manager.stop()
        logger.info("Task manager stopped")


def init_app():
    """Инициализация приложения"""
    try:
        # Создаем контекст приложения
        with app.app_context():
            # Инициализация базы данных
            init_db(app)
            
            # Инициализируем менеджеры
            init_managers()

            # Создаем все таблицы
            db.create_all()
            
            # Запускаем task manager
            if task_manager and not task_manager.is_running:
                task_manager.start()  # Здесь мы создаем цикл и запускаем задачи

            logger.info("Application initialized successfully")
    except Exception as e:
        logger.error(f"Error during initialization: {str(e)}\n{traceback.format_exc()}")
        raise

if __name__ == '__main__':
    init_app()
    app.run(host='0.0.0.0', port=5000, debug=True)