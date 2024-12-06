# proxy_manager.py
import asyncio
from datetime import datetime, timedelta
import aiohttp
from aiohttp_socks import ProxyConnector
from database import db, Proxy, ViewerSettings
import logging
from typing import Dict, Any, List, Optional
import random

logger = logging.getLogger(__name__)

class ProxyManager:
    def __init__(self):
        self.settings = None
        self.max_fails = 3
        self.ban_duration = 3600  # 1 час
        self._load_settings()
    
    async def add_proxies(self, proxies: list[str]) -> list[dict]:
            """Добавляет список прокси в базу данных и возвращает результаты"""
            results = []
            for proxy in proxies:
                try:
                    # Проверяем, существует ли уже такой прокси
                    existing_proxy = Proxy.query.filter_by(proxy=proxy).first()
                    if existing_proxy:
                        results.append({'proxy': proxy, 'status': 'exists'})
                        continue

                    # Создаем новый объект Proxy
                    new_proxy = Proxy(proxy=proxy, status='unchecked')
                    db.session.add(new_proxy)
                    results.append({'proxy': proxy, 'status': 'added'})
                except Exception as e:
                    results.append({'proxy': proxy, 'status': 'error', 'message': str(e)})

            try:
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                raise Exception(f"Ошибка сохранения прокси: {str(e)}")

            return results
        
    def _load_settings(self):
        """Загрузка настроек системы"""
        try:
            self.settings = ViewerSettings.get_settings()
        except Exception as e:
            logger.error(f"Ошибка загрузки настроек: {e}")
            raise

    async def get_working_proxy(self) -> Optional[Proxy]:
        """Получение рабочего прокси с наименьшей нагрузкой"""
        try:
            # Получаем активные прокси с учетом бана
            available_proxies = Proxy.query.filter(
                Proxy.status == 'active',
                Proxy.is_banned == False,
                (Proxy.banned_until < datetime.now()) | (Proxy.banned_until == None),
                Proxy.current_threads < self.settings.max_threads_per_proxy
            ).order_by(Proxy.current_threads).all()

            if not available_proxies:
                return None

            # Выбираем прокси с наименьшей нагрузкой
            selected_proxy = min(
                available_proxies,
                key=lambda p: (p.current_threads, p.fail_count)
            )
            
            # Проверяем работоспособность
            if await self.test_proxy(selected_proxy):
                return selected_proxy
                
            # Если проверка не прошла, помечаем прокси как проблемный
            await self.mark_proxy_failed(selected_proxy)
            return await self.get_working_proxy()  # Рекурсивный поиск следующего прокси

        except Exception as e:
            logger.error(f"Ошибка получения рабочего прокси: {e}")
            return None

    async def test_proxy(self, proxy: Proxy) -> bool:
        """Тестирование работоспособности прокси"""
        try:
            start_time = datetime.now()
            proxy_url = f"socks5://{proxy.proxy}"

            # Используем aiohttp для проверки прокси
            connector = ProxyConnector.from_url(proxy_url)
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.get("https://api.ipify.org?format=json", timeout=10) as response:
                    if response.status == 200:
                        response_time = (datetime.now() - start_time).total_seconds()
                        proxy.speed = response_time
                        proxy.status = "active"  # Успешно
                        proxy.last_checked = datetime.now()
                        db.session.commit()
                        return True

        except Exception as e:
            proxy.speed = None  # Если тест неудачный, скорость сбрасывается
            proxy.status = "failed"  # Не удалось подключиться
            proxy.last_checked = datetime.now()
            proxy.last_error = str(e)
            db.session.commit()
            return False

    async def update_proxy_stats(self, proxy: Proxy, success: bool, response_time: float = None):
        """Обновление статистики использования прокси"""
        try:
            if success:
                proxy.success_count += 1
                proxy.fail_count = 0
                proxy.last_success = datetime.now()
                if response_time:
                    proxy.average_response_time = (
                        proxy.average_response_time + response_time
                    ) / 2 if proxy.average_response_time else response_time
            else:
                proxy.fail_count += 1
                proxy.last_failure = datetime.now()
                
                if proxy.fail_count >= self.max_fails:
                    proxy.is_banned = True
                    proxy.banned_until = datetime.now() + timedelta(
                        seconds=self.ban_duration
                    )

            db.session.commit()

        except Exception as e:
            logger.error(f"Ошибка обновления статистики прокси: {e}")
            db.session.rollback()

    async def mark_proxy_failed(self, proxy: Proxy):
        """Отметка прокси как проблемного"""
        try:
            proxy.fail_count += 1
            proxy.last_failure = datetime.now()
            
            if proxy.fail_count >= self.max_fails:
                proxy.is_banned = True
                proxy.banned_until = datetime.now() + timedelta(
                    seconds=self.ban_duration
                )
                logger.warning(
                    f"Прокси {proxy.proxy} заблокирован до {proxy.banned_until}"
                )
            
            db.session.commit()

        except Exception as e:
            logger.error(f"Ошибка отметки прокси как проблемного: {e}")
            db.session.rollback()

    async def rotate_proxy(self, current_proxy: Proxy) -> Optional[Proxy]:
        """Ротация прокси при возникновении проблем"""
        try:
            # Освобождаем текущий прокси
            if current_proxy:
                current_proxy.current_threads -= 1
                db.session.commit()

            # Получаем новый рабочий прокси
            return await self.get_working_proxy()

        except Exception as e:
            logger.error(f"Ошибка ротации прокси: {e}")
            return None
        
    async def check_all_proxies(self) -> list:
        proxies = Proxy.query.all()
        results = []
        for proxy in proxies:
            is_working = await self.test_proxy(proxy)
            results.append({
                "proxy": proxy.proxy,
                "status": proxy.status,
                "speed": proxy.speed
            })
        return results