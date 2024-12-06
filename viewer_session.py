# viewer_session.py
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
from queue import Queue
import random
import aiohttp
from aiohttp_socks import ProxyConnector
from urllib.parse import urlparse
import traceback

from database import db, ViewerSettings, ViewerLog, Shot

logger = logging.getLogger(__name__)

class ViewerSession:
    """Класс для управления сессией просмотров"""
    
    def __init__(
        self,
        proxy: str,
        settings: ViewerSettings,
        log_queue: Queue,
        status_queue: Queue,
        session_id: str,
        dribbble_urls: List[str],
        views_target: int
    ):
        self.proxy = proxy
        self.settings = settings
        self.log_queue = log_queue
        self.status_queue = status_queue
        self.session_id = session_id
        self.dribbble_urls = dribbble_urls
        self.views_target = views_target
        
        self.view_count = 0
        self.is_running = False
        self.current_ip = None
        self.user_agent = self._generate_user_agent()
        
        # Статистика сессии
        self.start_time = None
        self.last_view_time = None
        self.failed_attempts = 0
        self.successful_attempts = 0

    def _generate_user_agent(self) -> str:
        """Генерация случайного User-Agent"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
        ]
        return random.choice(user_agents)

    async def _check_ip(self, session: aiohttp.ClientSession) -> Optional[str]:
        """Проверка IP-адреса прокси"""
        try:
            async with session.get('https://api.ipify.org?format=json') as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('ip')
        except Exception as e:
            logger.error(f"Ошибка проверки IP: {e}")
        return None

    async def _create_session(self) -> Optional[aiohttp.ClientSession]:
        """Создание сессии с прокси"""
        try:
            connector = ProxyConnector.from_url(f"socks5://{self.proxy}")
            session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    'User-Agent': self.user_agent,
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Cache-Control': 'max-age=0'
                }
            )
            return session
        except Exception as e:
            logger.error(f"Ошибка создания сессии: {e}")
            return None

    async def _process_view(self, session: aiohttp.ClientSession, url: str) -> bool:
        """Обработка одного просмотра"""
        try:
            start_time = datetime.now(timezone.utc)
            
            # Имитация поведения реального пользователя
            view_time = random.randint(
                self.settings.min_view_time,
                self.settings.max_view_time
            )
            
            # Первый запрос - получение страницы
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Ошибка загрузки страницы: {response.status}")
                
                # Имитация чтения страницы
                await asyncio.sleep(view_time)
                
                # Логируем успешный просмотр
                self._log_view(
                    url=url,
                    status='success',
                    response_time=(datetime.now(timezone.utc) - start_time).total_seconds()
                )
                
                self.successful_attempts += 1
                self.last_view_time = datetime.now(timezone.utc)
                return True

        except Exception as e:
            logger.error(f"Ошибка просмотра {url}: {e}")
            self._log_view(
                url=url,
                status='error',
                details=str(e)
            )
            self.failed_attempts += 1
            return False

    def _log_view(self, url: str, status: str, response_time: float = None, details: str = None):
        """Логирование просмотра"""
        try:
            # Получаем ID шота из URL
            dribbble_id = urlparse(url).path.split('/')[-1]
            shot = Shot.query.filter_by(dribbble_id=dribbble_id).first()
            
            log = ViewerLog(
                shot_id=shot.id if shot else None,
                action='view',
                status=status,
                details=details,
                response_time=response_time,
                ip_address=self.current_ip
            )
            
            db.session.add(log)
            
            if shot and status == 'success':
                shot.current_views += 1
                shot.last_view_at = datetime.now(timezone.utc)
                shot.views_per_hour = shot.calculate_views_per_hour()
                
            db.session.commit()
            
            # Отправляем лог в очередь
            self.log_queue.put(log.to_dict())
            
        except Exception as e:
            logger.error(f"Ошибка логирования просмотра: {e}")
            db.session.rollback()

    async def run_session(self):
        """Запуск сессии просмотров"""
        if self.is_running:
            logger.warning("Сессия уже запущена")
            return

        try:
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            
            async with await self._create_session() as session:
                # Проверяем IP
                self.current_ip = await self._check_ip(session)
                if not self.current_ip:
                    raise Exception("Не удалось определить IP прокси")
                
                while self.is_running and self.view_count < self.views_target:
                    for url in self.dribbble_urls:
                        if not self.is_running:
                            break
                            
                        if await self._process_view(session, url):
                            self.view_count += 1
                            
                            # Обновляем статус
                            self.status_queue.put({
                                'session_id': self.session_id,
                                'view_count': self.view_count,
                                'target': self.views_target,
                                'progress': f"{(self.view_count / self.views_target * 100):.1f}%"
                            })
                            
                            # Пауза между просмотрами
                            await asyncio.sleep(
                                random.randint(
                                    self.settings.pause_between_views,
                                    self.settings.pause_between_views * 2
                                )
                            )
                        
                        if self.failed_attempts >= self.settings.max_proxy_fails:
                            raise Exception("Превышен лимит ошибок прокси")

        except Exception as e:
            logger.error(f"Ошибка сессии {self.session_id}: {e}\n{traceback.format_exc()}")
            self.status_queue.put({
                'session_id': self.session_id,
                'error': str(e)
            })
        finally:
            self.is_running = False

    def stop(self):
        """Остановка сессии"""
        self.is_running = False

    def get_stats(self) -> dict:
        """Получение статистики сессии"""
        return {
            'session_id': self.session_id,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'last_view_time': self.last_view_time.isoformat() if self.last_view_time else None,
            'view_count': self.view_count,
            'views_target': self.views_target,
            'successful_attempts': self.successful_attempts,
            'failed_attempts': self.failed_attempts,
            'is_running': self.is_running,
            'current_ip': self.current_ip,
            'proxy': self.proxy
        }