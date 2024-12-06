// main.js

class AppManager {
    constructor() {
        this.currentPage = 'accountsPage';
        this.selectedShots = new Set();
        this.currentAccount = null;
        this.currentPage = 1;
        this.itemsPerPage = 12;
        this.viewsChart = null;
        
        this.initializeEventListeners();
        this.initializeCharts();
        this.loadInitialData();
    }

    // Инициализация слушателей событий
    initializeEventListeners() {
        // Навигация
        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchPage(e.target.dataset.page));
        });

        document.getElementById('accountsList').addEventListener('click', (e) => {
            const accountElement = e.target.closest('.account-item');
            if (accountElement) {
                const accountId = accountElement.dataset.id;
                this.selectAccount(accountId);
            }
        });

        // Кнопки действий
        document.getElementById('updateBtn').addEventListener('click', () => this.refreshData());
        document.getElementById('syncAccountsBtn').addEventListener('click', () => this.syncAccounts());
        document.getElementById('createTaskBtn').addEventListener('click', () => this.showCreateTaskModal());
        document.getElementById('addProxyBtn').addEventListener('click', () => this.showAddProxyModal());
        document.getElementById('checkProxiesBtn').addEventListener('click', () => this.checkAllProxies());

        // Формы
        document.getElementById('createTaskForm').addEventListener('submit', (e) => this.handleCreateTask(e));
        document.getElementById('addProxyForm').addEventListener('submit', (e) => this.handleAddProxy(e));

        // Закрытие модальных окон
        document.querySelectorAll('.closeModal').forEach(btn => {
            btn.addEventListener('click', () => this.closeAllModals());
        });
    }

    // Инициализация графиков
    initializeCharts() {
        const ctx = document.getElementById('viewsChartCanvas').getContext('2d');
        this.viewsChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'Просмотры',
                    data: [],
                    borderColor: '#3B82F6',
                    tension: 0.1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }

    // Загрузка начальных данных
    async loadInitialData() {
        await Promise.all([
            this.loadAccounts(),
            this.loadStats(),
            this.loadProxies()
        ]);
    }

    async loadActiveTasks() {
        try {
            const tasks = await this.api('tasks/active'); // Получение активных задач из API
            this.renderActiveTasks(tasks);
        } catch (error) {
            console.error('Ошибка загрузки активных задач:', error);
        }
    }

    // Переключение страниц
    switchPage(pageName) {
        document.querySelectorAll('.page').forEach(page => {
            page.classList.add('hidden');
            page.classList.remove('active');
        });
        document.getElementById(pageName).classList.remove('hidden');
        document.getElementById(pageName).classList.add('active');

        document.querySelectorAll('.nav-btn').forEach(btn => {
            btn.classList.remove('active');
            if (btn.dataset.page === pageName) {
                btn.classList.add('active');
            }
        });

        this.currentPage = pageName;
        this.refreshCurrentPage();
    }

    // API запросы
    async api(endpoint, options = {}) {
        try {
            const response = await fetch(`/api/${endpoint}`, {
                ...options,
                headers: {
                    'Content-Type': 'application/json',
                    ...options.headers
                }
            });
            
            if (!response.ok) {
                throw new Error(`API Error: ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            this.showToast(`Ошибка: ${error.message}`, 'error');
            throw error;
        }
    }

     
    // Загрузка аккаунтов
    async loadAccounts() {
        try {
            const accounts = await this.api('like_accounts/cached');
            this.renderAccounts(accounts);
    
            // Выбираем первый аккаунт по умолчанию
            if (accounts.length > 0 && !this.currentAccount) {
                await this.selectAccount(accounts[0].id);
            }
        } catch (error) {
            console.error('Ошибка загрузки аккаунтов:', error);
        }
    }
    
    // Загрузка статистики
    async loadStats() {
        try {
            const stats = await this.api('stats');
            this.updateStats(stats);
        } catch (error) {
            console.error('Ошибка загрузки статистики:', error);
        }
    }

    // Загрузка прокси
    async loadProxies() {
        try {
            const proxies = await this.api('proxies');
            this.renderProxies(proxies);
        } catch (error) {
            console.error('Ошибка загрузки прокси:', error);
        }
    }

    // Отрисовка списка аккаунтов
    renderAccounts(accounts) {
        const accountsList = document.getElementById('accountsList');
        accountsList.innerHTML = accounts.map(account => `
            <div class="account-item p-3 bg-gray-50 rounded hover:bg-gray-100 cursor-pointer ${
                this.currentAccount?.id === account.id ? 'bg-blue-50' : ''
            }" data-id="${account.id}">
                <div class="font-medium">${account.name}</div>
                <div class="text-sm text-gray-500">
                    Шотов: ${account.shots_count}
                    <span class="ml-2">Обновлено: ${new Date(account.last_update).toLocaleString()}</span>
                </div>
            </div>
        `).join('');
    
        // Добавляем обработчики
        accountsList.querySelectorAll('.account-item').forEach(item => {
            item.addEventListener('click', () => this.selectAccount(item.dataset.id));
        });
        
    }


    renderActiveTasks(tasks) {
        const tableBody = document.getElementById('tasksTableBody');
        tableBody.innerHTML = ''; // Очистка таблицы перед добавлением строк

        if (tasks.length === 0) {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="5" class="text-center text-gray-500 py-4">Нет активных задач</td>
                </tr>
            `;
            return;
        }

        tasks.forEach((task, index) => {
            const progress = ((task.completed_views / task.total_views) * 100).toFixed(2);
            tableBody.innerHTML += `
                <tr>
                    <td class="px-4 py-2 text-sm text-gray-600">${index + 1}</td>
                    <td class="px-4 py-2 text-sm text-blue-600">
                        <a href="${task.url}" target="_blank">${task.url}</a>
                    </td>
                    <td class="px-4 py-2 text-sm text-gray-600">${progress}%</td>
                    <td class="px-4 py-2 text-sm text-gray-600">${task.proxy || 'N/A'}</td>
                    <td class="px-4 py-2 text-sm">
                        <button class="text-red-600 hover:text-red-800" onclick="appManager.stopTask('${task.id}')">Остановить</button>
                    </td>
                </tr>
            `;
        });
    }


    // Выбор аккаунта
    async selectAccount(accountId) {
        try {
            const accountResponse = await this.api(`like_accounts/${accountId}/shots/list`);
            if (!accountResponse || !accountResponse.shots) throw new Error('Не удалось загрузить шоты аккаунта');
    
            this.currentAccount = {
                id: accountId,
                name: accountResponse.name || 'Неизвестный аккаунт',
                shots: accountResponse.shots,
            };
    
            // Рендерим шоты
            this.renderShots(this.currentAccount.shots);
            document.getElementById('selectedAccountTitle').textContent = this.currentAccount.name;
    
            // Сбрасываем выбранные шоты
            this.selectedShots.clear();
            this.updateShotCounters(this.currentAccount.shots.length);
        } catch (error) {
            console.error('Ошибка загрузки шотов:', error);
            this.currentAccount = null;
        }
    }
    
    

    // Отрисовка шотов
    renderShots(shots) {
        const shotsList = document.getElementById('shotsList');
    
        if (!shots || shots.length === 0) {
            shotsList.innerHTML = `<p class="text-gray-500">Шоты отсутствуют для этого аккаунта.</p>`;
            return;
        }
    
        const start = (this.currentPage - 1) * this.itemsPerPage;
        const end = start + this.itemsPerPage;
        const pageShots = shots.slice(start, end);

        shotsList.innerHTML = pageShots.map(shot => `
            <div class="shot-item relative bg-white rounded-lg shadow overflow-hidden">
                <input type="checkbox" class="absolute top-2 right-2 w-4 h-4" 
                       data-id="${shot.id}" ${this.selectedShots.has(shot.id) ? 'checked' : ''}>
                <img src="${shot.image_url}" alt="${shot.title}" class="w-full h-48 object-cover">
                <div class="p-4">
                    <h3 class="font-medium truncate">${shot.title}</h3>
                    <div class="mt-2 text-sm text-gray-500">
                        Просмотры: ${shot.current_views || 0} / ${shot.target_views || 0}
                    </div>
                    <div class="mt-2 h-2 bg-gray-200 rounded">
                        <div class="h-full bg-blue-500 rounded" 
                             style="width: ${(shot.current_views / shot.target_views * 100) || 0}%"></div>
                    </div>
                </div>
            </div>
        `).join('');

        // Обновляем пагинацию
        this.updatePagination(shots.length);

        // Добавляем обработчики выбора
        shotsList.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => this.toggleShotSelection(e.target));
        });

        // Обновляем счетчики
        this.updateShotCounters(shots.length);
    }

    // Обновление пагинации
    updatePagination(totalItems) {
        const pagination = document.getElementById('pagination');
        const totalPages = Math.ceil(totalItems / this.itemsPerPage);

        let paginationHtml = '';
        for (let i = 1; i <= totalPages; i++) {
            paginationHtml += `
                <button class="px-3 py-1 rounded ${
                    this.currentPage === i ? 'bg-blue-500 text-white' : 'bg-gray-200'
                }" data-page="${i}">${i}</button>
            `;
        }
        pagination.innerHTML = paginationHtml;

        // Добавляем обработчики
        pagination.querySelectorAll('button').forEach(btn => {
            btn.addEventListener('click', () => {
                this.currentPage = parseInt(btn.dataset.page);
                this.renderShots(this.currentAccount.shots);
            });
        });
    }

    // Обновление счетчиков шотов
    updateShotCounters(totalShots) {
        document.getElementById('selectedShotsCount').textContent = totalShots;
        document.getElementById('selectedCount').textContent = this.selectedShots.size;
    }
    

    // Выбор/отмена выбора шота
    toggleShotSelection(checkbox) {
        const shotId = parseInt(checkbox.dataset.id);
        if (checkbox.checked) {
            this.selectedShots.add(shotId);
        } else {
            this.selectedShots.delete(shotId);
        }
        this.updateShotCounters(this.currentAccount?.shots?.length || 0);
    }

    // Отрисовка прокси
    renderProxies(proxies) {
        const proxyList = document.getElementById('proxyList');
        proxyList.innerHTML = proxies.map(proxy => `
            <tr>
                <td class="px-6 py-4 whitespace-nowrap">${proxy.proxy}</td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="px-2 py-1 text-sm rounded-full ${
                        proxy.status === 'active' ? 'bg-green-100 text-green-800' :
                        proxy.status === 'inactive' ? 'bg-red-100 text-red-800' :
                        'bg-gray-100 text-gray-800'
                    }">
                        ${proxy.status}
                    </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">${proxy.speed ? `${proxy.speed.toFixed(2)}s` : 'N/A'}</td>
                <td class="px-6 py-4 whitespace-nowrap">${proxy.success_count}</td>
                <td class="px-6 py-4 whitespace-nowrap">${proxy.fail_count}</td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <button class="text-red-600 hover:text-red-800" 
                            onclick="appManager.deleteProxy('${proxy.id}')">
                        Удалить
                    </button>
                </td>
            </tr>
        `).join('');
    }

    // Обновление статистики
    updateStats(stats) {
        document.getElementById('totalShots').textContent = stats.total_shots;
        document.getElementById('activeShots').textContent = stats.active_shots;
        document.getElementById('totalViews').textContent = stats.total_views;
        document.getElementById('successRate').textContent = `${stats.success_rate}%`;

        // Обновляем график
        if (stats.daily_views) {
            this.viewsChart.data.labels = stats.daily_views.map(d => d.date);
            this.viewsChart.data.datasets[0].data = stats.daily_views.map(d => d.views);
            this.viewsChart.update();
        }
    }

    // Создание задачи
    async handleCreateTask(e) {
        e.preventDefault();
    
        if (this.selectedShots.size === 0) {
            this.showToast('Выберите хотя бы один шот', 'error');
            return;
        }
    
        const formData = new FormData(e.target);
    
        const shotUrls = Array.from(this.selectedShots).map(
            (shotId) => this.currentAccount.shots.find((shot) => shot.id === shotId)?.url
        );
    
        if (shotUrls.length === 0) {
            this.showToast('Ошибка: ссылки на шоты не найдены', 'error');
            return;
        }
    
        const requestData = {
            shot_urls: shotUrls, // Ссылки на шоты
            total_views: parseInt(formData.get('totalViews')), // Количество просмотров
            threads_count: parseInt(formData.get('threads')) // Количество потоков
        };
    
        try {
            console.log('Request Data:', requestData);
    
            const response = await this.api('tasks/create', {
                method: 'POST',
                body: JSON.stringify(requestData),
            });
    
            this.showToast('Задача успешно создана', 'success');
            this.closeAllModals();
            this.refreshData();
        } catch (error) {
            console.error('Ошибка создания задачи:', error);
            this.showToast('Ошибка создания задачи', 'error');
        }
    }    
    

    // Добавление прокси
    async handleAddProxy(e) {
        e.preventDefault();
        const formData = new FormData(e.target);
        const proxyList = formData.get('proxyList').split('\n').filter(p => p.trim());

        try {
            const response = await this.api('proxies/upload', {
                method: 'POST',
                body: JSON.stringify({ proxies: proxyList })
            });

            this.showToast(`Добавлено ${response.results.added} прокси`, 'success');
            this.closeAllModals();
            this.loadProxies();
        } catch (error) {
            this.showToast('Ошибка добавления прокси', 'error');
        }
    }

    // Проверка прокси
    async checkAllProxies() {
        try {
            const response = await this.api('proxies/check', {
                method: 'POST'
            });

            this.showToast(`Проверено ${response.results.checked} прокси`, 'success');
            this.loadProxies();
        } catch (error) {
            this.showToast('Ошибка проверки прокси', 'error');
        }
    }

    // Удаление прокси
    async deleteProxy(proxyId) {
        if (!confirm('Вы уверены, что хотите удалить этот прокси?')) {
            return;
        }

        try {
            await this.api(`proxies/${proxyId}`, {
                method: 'DELETE'
            });

            this.showToast('Прокси успешно удален', 'success');
            this.loadProxies();
        } catch (error) {
            this.showToast('Ошибка удаления прокси', 'error');
        }
    }

  
    // Синхронизация аккаунтов
    async syncAccounts() {
        try {
            this.showToast('Синхронизация аккаунтов...', 'info');
            await this.api('like_accounts/update', { method: 'POST' });
            this.showToast('Синхронизация завершена', 'success');
            await this.loadAccounts(); // Перезагрузка списка аккаунтов
            if (this.currentAccount) {
                await this.selectAccount(this.currentAccount.id); // Перезагрузка шотов текущего аккаунта
            }
        } catch (error) {
            console.error('Ошибка синхронизации аккаунтов:', error);
            this.showToast('Ошибка синхронизации аккаунтов', 'error');
        }
    }
    
    

    // Обновление данных
    async refreshData() {
        switch (this.currentPage) {
            case 'accountsPage':
                await this.loadAccounts();
                if (this.currentAccount) {
                    await this.selectAccount(this.currentAccount.id);
                }
                break;
            case 'proxyPage':
                await this.loadProxies();
                break;
            case 'statsPage':
                await this.loadStats();
                break;
        }
    }

    // Обновление текущей страницы
    refreshCurrentPage() {
        this.refreshData();
        this.loadAccounts();
    }

    // Управление модальными окнами
    showCreateTaskModal() {
        if (this.selectedShots.size === 0) {
            this.showToast('Выберите хотя бы один шот', 'warning');
            return;
        }
    
        if (!this.currentAccount) {
            this.showToast('Выберите аккаунт перед созданием задачи', 'warning');
            return;
        }
    
        document.getElementById('createTaskModal').classList.remove('hidden');
    }

    showAddProxyModal() {
        document.getElementById('addProxyModal').classList.remove('hidden');
    }

    closeAllModals() {
        document.querySelectorAll('.fixed.inset-0').forEach(modal => {
            modal.classList.add('hidden');
        });
    }

    // Отображение уведомлений
    showToast(message, type = 'info') {
        const toast = document.getElementById('toast');
        const toastMessage = document.getElementById('toastMessage');
        
        // Установка цвета в зависимости от типа уведомления
        const colors = {
            success: 'bg-green-500',
            error: 'bg-red-500',
            warning: 'bg-yellow-500',
            info: 'bg-blue-500'
        };
        
        // Удаляем все цвета и добавляем нужный
        toast.classList.remove('bg-green-500', 'bg-red-500', 'bg-yellow-500', 'bg-blue-500');
        toast.classList.add(colors[type]);
        
        // Устанавливаем сообщение
        toastMessage.textContent = message;
        
        // Показываем уведомление
        toast.classList.remove('translate-y-full');
        
        // Автоматически скрываем через 3 секунды
        setTimeout(() => {
            toast.classList.add('translate-y-full');
        }, 3000);
    }

    // Получение данных статистики задачи
    async getTaskStats(taskId) {
        try {
            const stats = await this.api(`tasks/${taskId}/stats`);
            return stats;
        } catch (error) {
            console.error('Ошибка получения статистики задачи:', error);
            return null;
        }
    }

    // Остановка задачи
    async stopTask(taskId) {
        try {
            await this.api(`tasks/${taskId}/stop`, { method: 'POST' });
            this.showToast('Задача успешно остановлена', 'success');
            this.loadActiveTasks(); // Перезагружаем таблицу задач
        } catch (error) {
            console.error('Ошибка остановки задачи:', error);
            this.showToast('Ошибка остановки задачи', 'error');
        }
    }


    // Получение статуса сессии
    async getSessionStatus(sessionId) {
        try {
            const status = await this.api(`viewer/status/${sessionId}`);
            return status;
        } catch (error) {
            console.error('Ошибка получения статуса сессии:', error);
            return null;
        }
    }

    // Загрузка логов
    async loadLogs(limit = 100) {
        try {
            const logs = await this.api(`logs?limit=${limit}`);
            this.renderLogs(logs);
        } catch (error) {
            console.error('Ошибка загрузки логов:', error);
        }
    }

    // Отрисовка логов
    renderLogs(logs) {
        const logsContainer = document.getElementById('logsContainer');
        if (!logsContainer) return;

        logsContainer.innerHTML = logs.map(log => `
            <div class="log-entry p-2 border-b ${
                log.status === 'success' ? 'bg-green-50' :
                log.status === 'error' ? 'bg-red-50' :
                'bg-gray-50'
            }">
                <div class="text-sm text-gray-500">
                    ${new Date(log.timestamp).toLocaleString()}
                </div>
                <div class="font-medium">
                    ${log.action}
                </div>
                <div class="text-sm">
                    ${log.details || ''}
                </div>
            </div>
        `).join('');
    }

    // Форматирование времени
    formatTime(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }

    // Форматирование даты
    formatDate(date) {
        return new Date(date).toLocaleString('ru-RU', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
}

// Инициализация приложения
const appManager = new AppManager();

// Обработка ошибок
window.onerror = function(msg, url, lineNo, columnNo, error) {
    appManager.showToast(`Ошибка: ${msg}`, 'error');
    console.error('Error: ' + msg + '\nurl: ' + url + '\nline: ' + lineNo);
    return false;
};

// Автоматическое обновление данных каждые 30 секунд
setInterval(() => {
    appManager.refreshData();
}, 30000);