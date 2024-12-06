from datetime import datetime, timedelta
import asyncio
import logging
import uuid
import random
from typing import Dict, List, Optional, Set
from concurrent.futures import ThreadPoolExecutor, wait
from queue import Queue
from database import db, Shot, ViewerTask, Proxy, ViewerSettings
from viewer_session import ViewerSession
from proxy_manager import ProxyManager
import httpx

logger = logging.getLogger(__name__)

class TaskManager:
    def __init__(self):
        """Инициализация менеджера задач"""
        self.active_sessions: Dict[str, ViewerSession] = {}
        self.running_tasks: Set[int] = set()
        self.proxy_manager = ProxyManager()
        self.daily_view_limit = 100000
        self.max_views_per_shot = 35
        self.min_views_per_shot = 30
        self.session_interval_hours = (4, 6)
        self.is_running = False
        self.settings = None
        self._load_settings()

    def _load_settings(self):
        """Загрузка настроек из базы данных"""
        try:
            self.settings = ViewerSettings.get_settings()
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")
            raise

    async def update_shots_status(self):
        """Обновление статуса шотов"""
        try:
            shots = Shot.query.all()
            for shot in shots:
                if shot.current_views >= 1000:
                    shot.status = 'completed'
                elif shot.current_views > 0:
                    shot.status = 'active'
                else:
                    shot.status = 'pending'
            db.session.commit()
        except Exception as e:
            logger.error(f"Ошибка обновления статусов шотов: {e}")
            db.session.rollback()

    async def fetch_and_store_shot(self, shot_id: int, account_id: int):
        """Извлекает данные о шоте через API аккаунта и сохраняет их в базу данных"""
        async with httpx.AsyncClient() as client:
            # Получаем все шоты аккаунта
            response = await client.get(f'https://dbauto.site/api/like_accounts/{account_id}/shots')
            if response.status_code == 200:
                data = response.json()

                # Ищем шот с нужным ID
                shot_data = next((shot for shot in data.get('shots', []) if shot['id'] == shot_id), None)
                if not shot_data:
                    raise Exception(f"Shot with ID {shot_id} not found in account {account_id}")

                # Сохраняем шот в базу данных
                shot = Shot(
                    dribbble_id=shot_data['id'],
                    title=shot_data.get('title', '').strip(),
                    image_url=shot_data.get('image_url'),
                    url=shot_data.get('url'),
                    status='pending'
                )
                db.session.add(shot)
                db.session.commit()
                return shot
            else:
                raise Exception(f"Failed to fetch shots for account {account_id}: {response.status_code}")


    async def distribute_daily_views(self) -> List[ViewerTask]:
        """Распределение дневной квоты просмотров между шотами"""
        try:
            # Получаем активные шоты с просмотрами < 1000
            active_shots = Shot.query.filter(
                Shot.status.in_(['pending', 'active']),
                Shot.current_views < 1000
            ).all()

            if not active_shots:
                logger.info("Нет активных шотов для распределения просмотров")
                return []

            # Рассчитываем количество просмотров на каждый шот
            views_per_shot = min(
                self.daily_view_limit // len(active_shots),
                self.max_views_per_shot
            )

            # Создаем задачи с учетом временных блоков
            tasks = []
            time_blocks = 4  # Разделяем день на 4 блока
            shots_per_block = len(active_shots) // time_blocks
            
            for i in range(time_blocks):
                start_idx = i * shots_per_block
                end_idx = start_idx + shots_per_block if i < time_blocks - 1 else len(active_shots)
                block_shots = active_shots[start_idx:end_idx]
                
                if not block_shots:
                    continue
                
                task = ViewerTask(
                    uid=str(uuid.uuid4()),
                    title=f"Daily Task Block {i + 1}",
                    shots=block_shots,
                    total_views=views_per_shot * len(block_shots),
                    views_per_ip=1,
                    threads_count=min(50, len(block_shots)),
                    pause_between_views=random.randint(10, 20),
                    status='pending'
                )
                
                db.session.add(task)
                tasks.append(task)

            db.session.commit()
            return tasks

        except Exception as e:
            logger.error(f"Ошибка распределения просмотров: {e}")
            db.session.rollback()
            return []

    async def process_task(self, task: ViewerTask):
        """Обработка отдельной задачи просмотров"""
        try:
            if task.id in self.running_tasks:
                logger.warning(f"Задача {task.id} уже выполняется")
                return

            self.running_tasks.add(task.id)
            task.status = 'active'
            db.session.commit()

            # Получаем доступные прокси
            available_proxies = await self.proxy_manager.get_available_proxies()
            if not available_proxies:
                logger.error("Нет доступных прокси для выполнения задачи")
                task.status = 'failed'
                db.session.commit()
                return

            # Создаем сессии для каждого шота
            sessions = []
            for shot in task.shots:
                try:
                    proxy = await self.proxy_manager.get_working_proxy()
                    if not proxy:
                        continue

                    session = ViewerSession(
                        proxy=proxy.proxy,
                        settings=self.settings,
                        log_queue=Queue(),
                        status_queue=Queue(),
                        session_id=str(uuid.uuid4()),
                        dribbble_urls=[shot.url],
                        views_target=min(
                            self.max_views_per_shot - shot.current_views,
                            task.views_per_ip
                        )
                    )
                    
                    sessions.append(session)
                    self.active_sessions[session.session_id] = session
                    
                except Exception as e:
                    logger.error(f"Ошибка создания сессии для шота {shot.id}: {e}")

            if not sessions:
                logger.error("Не удалось создать сессии для задачи")
                task.status = 'failed'
                db.session.commit()
                return

            # Запускаем сессии в пуле потоков
            with ThreadPoolExecutor(max_workers=task.threads_count) as executor:
                futures = [
                    executor.submit(session.run_session_with_context)
                    for session in sessions
                ]
                await asyncio.get_event_loop().run_in_executor(
                    None, wait, futures
                )

            # Проверяем результаты и обновляем статус
            success = all(future.result() for future in futures)
            task.status = 'completed' if success else 'partially_completed'
            
            # Очищаем сессии
            for session in sessions:
                try:
                    session.stop()
                    if session.session_id in self.active_sessions:
                        del self.active_sessions[session.session_id]
                except Exception as e:
                    logger.error(f"Ошибка остановки сессии: {e}")

            db.session.commit()

        except Exception as e:
            logger.error(f"Ошибка обработки задачи {task.id}: {e}")
            task.status = 'failed'
            db.session.commit()
        finally:
            self.running_tasks.remove(task.id)

    async def start_daily_processing(self):
        """Запуск ежедневной обработки задач"""
        while self.is_running:
            await asyncio.sleep(86400)
            try:
                await self.update_shots_status()
                
                # Создаем новые задачи на день
                tasks = await self.distribute_daily_views()
                
                for task in tasks:
                    if not self.is_running:
                        break
                        
                    # Рассчитываем задержку для временного блока
                    delay_hours = random.uniform(
                        self.session_interval_hours[0],
                        self.session_interval_hours[1]
                    )
                    
                    logger.info(f"Ожидание {delay_hours:.2f} часов перед выполнением блока задач")
                    await asyncio.sleep(delay_hours * 3600)
                    
                    if self.is_running:
                        await self.process_task(task)

                # Ожидаем начала следующего дня
                if self.is_running:
                    seconds_until_next_day = self._get_seconds_until_next_day()
                    logger.info(f"Ожидание {seconds_until_next_day} секунд до следующего дня")
                    await asyncio.sleep(seconds_until_next_day)

            except Exception as e:
                logger.error(f"Ошибка в ежедневной обработке: {e}")
                await asyncio.sleep(300)  # Пауза перед повторной попыткой

    def _get_seconds_until_next_day(self) -> int:
        """Расчет секунд до начала следующего дня"""
        now = datetime.now()
        tomorrow = now + timedelta(days=1)
        next_day = datetime(
            year=tomorrow.year,
            month=tomorrow.month,
            day=tomorrow.day,
            hour=0,
            minute=0,
            second=0
        )
        return int((next_day - now).total_seconds())
      
    async def create_viewer_session(self, session_data: dict) -> Optional[str]:
        """Создание новой сессии просмотров"""
        try:
            proxy = await self.proxy_manager.get_working_proxy()
            if not proxy:
                logger.warning("Нет доступных прокси для сессии")
                return None
                
            session_id = str(uuid.uuid4())
            session = ViewerSession(
                proxy=proxy.proxy,
                settings=self.settings,
                log_queue=Queue(),
                status_queue=Queue(),
                session_id=session_id,
                dribbble_urls=session_data['urls'],
                views_target=session_data['views_target']
            )
            
            self.active_sessions[session_id] = session
            
            # Запускаем сессию в отдельном потоке
            executor = ThreadPoolExecutor(max_workers=1)
            executor.submit(session.run_session)
            
            return session_id

        except Exception as e:
            logger.error(f"Ошибка создания сессии просмотров: {e}")
            return None

    async def get_session_status(self, session_id: str) -> Optional[Dict]:
        """Получение статуса сессии"""
        try:
            session = self.active_sessions.get(session_id)
            if not session:
                return None

            return {
                'session_id': session_id,
                'is_running': session.is_running,
                'view_count': session.view_count,
                'views_target': session.views_target,
                'current_proxy': session.proxy,
                'progress': f"{(session.view_count / session.views_target * 100):.1f}%" 
                           if session.views_target > 0 else "0%"
            }

        except Exception as e:
            logger.error(f"Ошибка получения статуса сессии {session_id}: {e}")
            return None

    def start(self):
        """Запуск менеджера задач"""
        if not self.is_running:
            self.is_running = True
            loop = asyncio.get_event_loop()
            if not loop.is_running():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.create_task(self.start_daily_processing())
            logger.info("Менеджер задач запущен")

    def stop(self):
        """Остановка менеджера задач"""
        self.is_running = False
        for session in list(self.active_sessions.values()):
            try:
                session.stop()
            except Exception as e:
                logger.error(f"Ошибка остановки сессии: {e}")
        self.active_sessions.clear()
        logger.info("Менеджер задач остановлен")

    async def stop_task(self, task_id: int) -> bool:
        """Остановка выполнения задачи"""
        try:
            task = ViewerTask.query.get(task_id)
            if not task:
                return False

            if task.id in self.running_tasks:
                # Останавливаем связанные сессии
                for session in list(self.active_sessions.values()):
                    if any(shot.url in session.dribbble_urls for shot in task.shots):
                        try:
                            session.stop()
                            if session.session_id in self.active_sessions:
                                del self.active_sessions[session.session_id]
                        except Exception as e:
                            logger.error(f"Ошибка остановки сессии: {e}")

                self.running_tasks.remove(task.id)
                
            task.status = 'stopped'
            db.session.commit()
            return True

        except Exception as e:
            logger.error(f"Ошибка остановки задачи {task_id}: {e}")
            return False

    async def get_tasks_status(self) -> Dict:
        """Получение статуса всех задач"""
        try:
            total_tasks = ViewerTask.query.count()
            active_tasks = ViewerTask.query.filter_by(status='active').count()
            completed_tasks = ViewerTask.query.filter_by(status='completed').count()
            failed_tasks = ViewerTask.query.filter_by(status='failed').count()
            
            return {
                'total_tasks': total_tasks,
                'active_tasks': active_tasks,
                'completed_tasks': completed_tasks,
                'failed_tasks': failed_tasks,
                'running_tasks': len(self.running_tasks),
                'active_sessions': len(self.active_sessions)
            }

        except Exception as e:
            logger.error(f"Ошибка получения статуса задач: {e}")
            return {}