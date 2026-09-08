// Station & Camera DRI Management - Common JavaScript Functions

// API request helper
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });
        return await response.json();
    } catch (error) {
        console.error('API request failed:', error);
        alert('请求失败，请稍后重试');
        throw error;
    }
}

// Show toast notification
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 px-4 py-2 rounded-lg text-white ${
        type === 'success' ? 'bg-green-500' :
        type === 'error' ? 'bg-red-500' :
        'bg-blue-500'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

// Confirm dialog helper
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

// Format date
function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('zh-CN');
}

// Format datetime
function formatDateTime(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN');
}

// 通用：把用户输入的表头字符串拆分成表头数组（供各模块建表/定义表头复用）。
// 兼容中英文逗号（英文 , 与中文 ，），统一先转成英文逗号再拆分，
// 自动去除每个表头首尾空白，并过滤掉空项。可避免中文逗号导致的表头未分隔问题。
function parseTableHeaders(input) {
    if (input === undefined || input === null) return [];
    return String(input)
        .replace(/，/g, ',')          // 中文逗号 → 英文逗号
        .split(',')                   // 按英文逗号拆分
        .map(function (s) { return (s || '').trim(); })
        .filter(function (s) { return s !== ''; });
}

