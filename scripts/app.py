"""
Station & Camera DRI Management Web Server
部门信息管理与数据收集平台
"""
import csv
import io
import json
import os
import re
import secrets
import sys
import time
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for
from markupsafe import escape, Markup

# 把 scripts 目录加入 sys.path：
# 无论用 `app:app`（cwd=scripts，gunicorn/docker-compose 命令）还是
# `scripts.app:app`（cwd=/app，镜像默认 CMD）启动，都能正确 import data_manager。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_manager import (
    init_all_data,
    DEPT_SHORT_NAMES, normalize_dept,
    get_all_staff, get_department_summary, get_department_detail, get_department_all, get_department_staff,
    add_staff_to_department, remove_staff_from_department, update_department_members, add_left_record,
    add_joined_record, find_staff_id_by_name, update_staff_member,
    update_department_record, delete_department_record,
    get_personnel_file, update_personnel_file,
    get_personnel_files_by_dept, find_collector_sheet_by_name, classify_reward_punishment,
    get_all_users, get_user, upsert_user, delete_user,
    verify_user_password, set_user_password, DEFAULT_PASSWORD,
    read_tabular_rows,
    get_all_action_items, add_action_item, update_action_item, delete_action_item,
    get_action_columns, set_action_columns,
    get_all_info_list, create_info_table, add_info_row, update_info_row, delete_info_table, delete_info_row,
    update_info_table_headers,
    get_collector_sheets, get_collector_sheet, create_collector_sheet,
    add_collector_row, update_collector_row, delete_collector_row, delete_collector_sheet,
    update_collector_sheet_headers, set_collector_sheet_locked, is_collector_sheet_locked,
    get_history, add_history,
    export_staff_to_excel, import_staff_from_excel
)

from version import __version__

# 获取项目根目录和模板路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
TEMPLATE_DIR = os.path.join(PROJECT_DIR, 'templates')
STATIC_DIR = os.path.join(PROJECT_DIR, 'static')
DATA_DIR = os.path.join(PROJECT_DIR, 'data')

# ===== 安全配置辅助 =====

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')


def _load_or_create_secret_key() -> str:
    """读取环境变量 SECRET_KEY；否则从 data/.secret_key（旧版在项目根）读取；
    都没有则生成一个随机值并落盘保存（避免重启后会话全部失效）。
    Docker 场景下 data/ 是持久化卷，密钥可随容器重建保留。"""
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    key_file = os.path.join(DATA_DIR, '.secret_key')
    legacy_key_file = os.path.join(PROJECT_DIR, '.secret_key')
    for kf in (key_file, legacy_key_file):
        if os.path.exists(kf):
            try:
                with open(kf, 'r', encoding='utf-8') as f:
                    k = f.read().strip()
                if k:
                    return k
            except OSError:
                pass
    k = secrets.token_hex(32)
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(key_file, 'w', encoding='utf-8') as f:
            f.write(k)
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return k


# 是否处于调试/开发模式（生产请保持关闭）
APP_DEBUG = _env_bool('FLASK_DEBUG', False)

app = Flask(__name__,
            template_folder=TEMPLATE_DIR,
            static_folder=STATIC_DIR,
            static_url_path='/static')


# ===== 反向代理子路径（URL 前缀）支持 =====
# 站点部署在 http://hwte.luxsan-ict.com/AL/ 这类子路径下时，
# 通过 URL_PREFIX=/AL 让 url_for / redirect 生成带前缀的 URL。
class UrlPrefixMiddleware:
    """把反向代理的子路径前缀变成 WSGI 的 SCRIPT_NAME。

    - 请求已带前缀（/AL/login）→ 剥掉前缀后交给路由，并设 SCRIPT_NAME=/AL
    - 请求不带前缀（代理已剥离 / 本地直连 / 容器健康检查）→ 只设 SCRIPT_NAME，路由照常匹配
    - /AL（无尾斜杠）→ 规范化为 /AL/，避免 404
    前缀来源：环境变量 URL_PREFIX 优先，其次代理头 X-Forwarded-Prefix，都没有则不做任何处理。
    """

    def __init__(self, wsgi_app, prefix: str = ''):
        self.wsgi_app = wsgi_app
        self.prefix = (prefix or '').strip().rstrip('/')

    def __call__(self, environ, start_response):
        prefix = self.prefix or (environ.get('HTTP_X_FORWARDED_PREFIX') or '').strip().rstrip('/')
        if prefix:
            path = environ.get('PATH_INFO', '') or ''
            if path == prefix:
                path = '/'
            elif path.startswith(prefix + '/'):
                path = path[len(prefix):]
            environ['SCRIPT_NAME'] = prefix
            environ['PATH_INFO'] = path or '/'
        return self.wsgi_app(environ, start_response)


app.wsgi_app = UrlPrefixMiddleware(app.wsgi_app, os.environ.get('URL_PREFIX', ''))

# —— 会话与安全相关配置 ——
app.config['SECRET_KEY'] = _load_or_create_secret_key()
app.config['DEBUG'] = APP_DEBUG
# 生产关闭模板自动重载可减少每次渲染的扫描开销
app.config['TEMPLATES_AUTO_RELOAD'] = APP_DEBUG
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# 若走 HTTPS，可设环境变量 SESSION_COOKIE_SECURE=true
app.config['SESSION_COOKIE_SECURE'] = _env_bool('SESSION_COOKIE_SECURE', False)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
# 限制上传体积，防止超大文件拖垮服务（Excel/CSV 导入）
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024

#version control
@app.context_processor
def inject_version():
    return dict(app_version=__version__)

def nl2br(value):
    """把文本中的换行符转成 <br>，同时转义 HTML，供表格单元格保留换行显示。"""
    if value is None:
        return ''
    text = str(value).replace('\r\n', '\n').replace('\r', '\n')
    return Markup(str(escape(text)).replace('\n', '<br>'))


app.jinja_env.filters['nl2br'] = nl2br

DEPARTMENTS = ['五部', '六部', '七部', '八部']

# 用户管理入口密码（可用环境变量 ADMIN_PASSWORD 覆盖，生产环境务必设置）
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or 'DLJ360781dlj'
# 仅该工号可见/可进入用户管理（可用环境变量 ADMIN_EMPLOYEE_ID 覆盖）
ADMIN_EMPLOYEE_ID = os.environ.get('ADMIN_EMPLOYEE_ID') or '12214253'


def get_client_ip():
    """获取客户端真实IP地址"""
    # 优先从 X-Forwarded-For 获取（反向代理场景）
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    # 其次从 X-Real-IP 获取
    if request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    # 最后用 remote_addr
    return request.remote_addr or 'Unknown'


# ===== API 登录守卫（未登录返回 401 JSON，而不是跳转页面） =====
def api_login_required(f):
    """需要登录才能访问的 API 守卫，返回 JSON 而不是 302。"""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'success': False, 'message': '请先登录'}), 401
        return f(*args, **kwargs)
    return wrapped


# ===== 基础安全响应头 =====
@app.after_request
def set_security_headers(response):
    # 防 XSS/点击劫持/类型嗅探
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'same-origin')
    if request.path.startswith('/static/'):
        # 静态资源可被浏览器缓存较长时间
        response.headers.setdefault('Cache-Control', 'public, max-age=3600')
    else:
        response.headers.setdefault('Cache-Control', 'no-store')
    return response


# 上传体积超限统一返回 JSON 提示
@app.errorhandler(413)
def too_large(e):
    return jsonify({'success': False, 'message': '上传文件过大，最大允许 25MB'}), 413


# ===== 登录暴力破解限流 =====
LOGIN_WINDOW_SECONDS = 300      # 5 分钟窗口
LOGIN_MAX_ATTEMPTS = 8          # 窗口内最多尝试次数
_login_failures = {}            # key -> {'count': n, 'first': ts}
_login_lock = threading.RLock()


def _too_many_login_attempts(key: str) -> bool:
    with _login_lock:
        now = time.time()
        rec = _login_failures.get(key)
        if rec and (now - rec['first']) >= LOGIN_WINDOW_SECONDS:
            _login_failures.pop(key, None)
            rec = None
        if rec and rec['count'] >= LOGIN_MAX_ATTEMPTS:
            return True
        return False


def _record_login_failure(key: str):
    with _login_lock:
        now = time.time()
        rec = _login_failures.get(key)
        if not rec or (now - rec['first']) >= LOGIN_WINDOW_SECONDS:
            _login_failures[key] = {'count': 1, 'first': now}
        else:
            rec['count'] += 1


def _clear_login_failures(key: str):
    with _login_lock:
        _login_failures.pop(key, None)


def check_user_in_whitelist(employee_id):
    """检查工号是否在用户表（app.db 的 users 表）中"""
    user = get_user(employee_id)
    if user:
        return True, user
    return False, None


def get_user_permissions(employee_id, name):
    """根据工号获取用户权限配置，未配置的工号使用默认权限"""
    # 默认权限：所有人都可以编辑数据收集，其他需要匹配用户表
    default_user = {
        'employee_id': employee_id,
        'name': name,
        'can_edit_department': False,
        'can_edit_action_items': False,
        'can_edit_info_list': False,
        'can_edit_collector': True,  # 数据收集默认开启
        'can_edit_personnel_file': 'NO'  # 员工档案默认无权限
    }

    u = get_user(employee_id)
    if u:
        result = default_user.copy()
        result['name'] = name  # 使用登录时输入的姓名
        result['can_edit_department'] = bool(u.get('can_edit_department'))
        result['can_edit_action_items'] = bool(u.get('can_edit_action_items'))
        result['can_edit_info_list'] = bool(u.get('can_edit_info_list'))
        result['can_edit_collector'] = True  # 数据收集始终可编辑
        result['can_edit_personnel_file'] = str(u.get('can_edit_personnel_file', 'NO')).strip()
        return result

    return default_user


# ===== 员工档案权限（can_edit_personnel_file）=====
def personnel_allowed_depts(policy) -> set:
    """解析员工档案权限策略为可访问部门集合。
    ALL=全部部门；NO=无权限；其它按“部”关键字匹配（如 七部八部 / 五部 / 六部）。"""
    if not policy:
        return set()
    v = str(policy).strip()
    if v.upper() == 'ALL':
        return set(DEPT_SHORT_NAMES)
    if v.upper() == 'NO':
        return set()
    return {d for d in DEPT_SHORT_NAMES if d in v}


def can_access_personnel_file(user, dept) -> bool:
    """判断当前用户对某部门员工的档案是否有查阅/编辑权限"""
    if not user:
        return False
    policy = user.get('can_edit_personnel_file', 'NO')
    if str(policy).upper() == 'ALL':
        return True
    return dept in personnel_allowed_depts(policy)


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            # 用 url_for 生成，自动带上子路径前缀（如 /AL/login）
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function


def get_current_user():
    """获取当前登录用户"""
    return session.get('user')


# ===== 登录 =====

@app.route('/login')
def login_page():
    """登录页面"""
    if 'user' in session:
        return redirect(url_for('index'))
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """登录验证 - 只允许数据库 users 表中的成员访问（含暴力破解限流）"""
    ip = get_client_ip()
    data = request.json or {}
    employee_id = str(data.get('employee_id', '')).strip()
    name = str(data.get('name', '')).strip()
    password = str(data.get('password', ''))

    if not employee_id or not name:
        return jsonify({'success': False, 'message': '请填写工号和姓名'})
    if not password:
        return jsonify({'success': False, 'message': '请输入密码'})

    # 限流 key：同一 IP + 同一工号 分别计数
    if _too_many_login_attempts(f'ip:{ip}') or _too_many_login_attempts(f'id:{employee_id}'):
        return jsonify({'success': False, 'message': '尝试次数过多，请 5 分钟后再试'}), 429

    # 检查是否在白名单中
    in_whitelist, _user_data = check_user_in_whitelist(employee_id)
    if not in_whitelist:
        _record_login_failure(f'ip:{ip}')
        _record_login_failure(f'id:{employee_id}')
        return jsonify({
            'success': False,
            'message': '无权限访问此页面，请联系管理员申请权限'
        })

    # 工号 + 密码 必须完全匹配
    if not verify_user_password(employee_id, password):
        _record_login_failure(f'ip:{ip}')
        _record_login_failure(f'id:{employee_id}')
        return jsonify({'success': False, 'message': '工号或密码不正确'})

    # 获取用户权限配置
    user = get_user_permissions(employee_id, name)
    session.permanent = True
    session['user'] = user
    _clear_login_failures(f'ip:{ip}')
    _clear_login_failures(f'id:{employee_id}')
    return jsonify({'success': True, 'user': user})


@app.route('/api/logout', methods=['POST'])
def api_logout():
    """退出登录"""
    session.pop('user', None)
    return jsonify({'success': True})


@app.route('/api/current-user')
def api_current_user():
    """获取当前用户信息"""
    if 'user' in session:
        return jsonify({'logged_in': True, 'user': session['user']})
    return jsonify({'logged_in': False})


# ===== 用户管理（仅 ADMIN_EMPLOYEE_ID 可见/可进入，且每次进入需密码）=====
# 说明：不使用 session 持久化“已解锁”，而是在密码校验通过后签发一个
# 短期有效的随机 token（仅存于服务器内存），由管理页面保存在 JS 变量里。
# 页面一刷新/重新进入，JS 变量即丢失，因此“每次进入都需要输入密码”。

_ADMIN_TOKENS = {}          # token -> 过期时间戳
_ADMIN_TOKEN_TTL = 30 * 60  # token 有效期（秒）
_admin_lock = threading.RLock()


def _is_admin_employee() -> bool:
    """当前登录用户是否为指定的管理员工号"""
    user = session.get('user') or {}
    return str(user.get('employee_id', '')) == ADMIN_EMPLOYEE_ID


def _prune_admin_tokens():
    now = time.time()
    with _admin_lock:
        for t in [t for t, exp in _ADMIN_TOKENS.items() if exp < now]:
            _ADMIN_TOKENS.pop(t, None)


def _issue_admin_token() -> str:
    token = secrets.token_urlsafe(24)
    with _admin_lock:
        _ADMIN_TOKENS[token] = time.time() + _ADMIN_TOKEN_TTL
    return token


def _admin_token_ok() -> bool:
    """校验请求头中的 X-Admin-Token 是否有效"""
    token = (request.headers.get('X-Admin-Token') or '').strip()
    if not token:
        return False
    with _admin_lock:
        exp = _ADMIN_TOKENS.get(token)
        if exp is None or exp < time.time():
            _ADMIN_TOKENS.pop(token, None)
            return False
    return True


def _admin_request_ok() -> bool:
    """管理接口鉴权：必须是指定工号，且携带有效 token"""
    return _is_admin_employee() and _admin_token_ok()


@app.route('/admin/users')
@login_required
def admin_users():
    """用户管理入口：仅指定工号可见；页面内每次进入都需输入密码"""
    if not _is_admin_employee():
        return redirect(url_for('index'))
    return render_template('admin_users.html')


@app.route('/api/admin/unlock', methods=['POST'])
def api_admin_unlock():
    """校验工号 + 管理密码，成功后签发短期 token（不写入 session）"""
    if not _is_admin_employee():
        return jsonify({'success': False, 'message': '无权限'}), 403
    data = request.json or {}
    employee_id = str(data.get('employee_id', '')).strip()
    pwd = str(data.get('password', ''))
    # 工号必须为指定的管理员工号
    if not employee_id or not secrets.compare_digest(employee_id, ADMIN_EMPLOYEE_ID):
        return jsonify({'success': False, 'message': '工号不正确'}), 403
    if pwd and secrets.compare_digest(pwd, ADMIN_PASSWORD):
        _prune_admin_tokens()
        return jsonify({'success': True, 'token': _issue_admin_token()})
    return jsonify({'success': False, 'message': '密码错误'}), 403


@app.route('/api/admin/lock', methods=['POST'])
def api_admin_lock():
    """销毁当前 token（前端离开页面时调用）"""
    token = (request.headers.get('X-Admin-Token') or '').strip()
    with _admin_lock:
        _ADMIN_TOKENS.pop(token, None)
    return jsonify({'success': True})


@app.route('/api/admin/users', methods=['GET'])
def api_admin_users_list():
    if not _admin_request_ok():
        return jsonify({'success': False, 'message': '未通过管理员验证'}), 403
    return jsonify({'success': True, 'users': get_all_users()})


@app.route('/api/admin/users', methods=['POST'])
def api_admin_user_save():
    if not _admin_request_ok():
        return jsonify({'success': False, 'message': '未通过管理员验证'}), 403
    data = request.json or {}
    employee_id = str(data.get('employee_id', '')).strip()
    if not employee_id:
        return jsonify({'success': False, 'message': '工号不能为空'}), 400
    upsert_user({
        'employee_id': employee_id,
        'name': data.get('name', ''),
        'can_edit_department': data.get('can_edit_department', False),
        'can_edit_action_items': data.get('can_edit_action_items', False),
        'can_edit_info_list': data.get('can_edit_info_list', False),
        'can_edit_personnel_file': data.get('can_edit_personnel_file', 'NO')
    })
    admin = session.get('user', {})
    add_history(f"用户管理: 保存用户 {data.get('name', '')}({employee_id})",
                admin.get('name', 'admin'), admin.get('employee_id', ''), get_client_ip())
    return jsonify({'success': True})


@app.route('/api/admin/users/<employee_id>', methods=['DELETE'])
def api_admin_user_delete(employee_id):
    if not _admin_request_ok():
        return jsonify({'success': False, 'message': '未通过管理员验证'}), 403
    ok = delete_user(employee_id)
    if not ok:
        return jsonify({'success': False, 'message': '用户不存在'}), 404
    admin = session.get('user', {})
    add_history(f"用户管理: 删除用户 {employee_id}",
                admin.get('name', 'admin'), admin.get('employee_id', ''), get_client_ip())
    return jsonify({'success': True})


@app.route('/api/admin/users/<employee_id>/reset-password', methods=['POST'])
def api_admin_user_reset_password(employee_id):
    """管理员把用户密码重置为初始密码（用户忘记密码时使用）"""
    if not _admin_request_ok():
        return jsonify({'success': False, 'message': '未通过管理员验证'}), 403

    user = get_user(employee_id)
    if not user:
        return jsonify({'success': False, 'message': '用户不存在'}), 404
    if not set_user_password(employee_id, DEFAULT_PASSWORD):
        return jsonify({'success': False, 'message': '重置失败，请重试'}), 500

    admin = session.get('user', {})
    add_history(f"用户管理: 重置密码为初始密码 {user.get('name', '')}({employee_id})",
                admin.get('name', 'admin'), admin.get('employee_id', ''), get_client_ip())
    return jsonify({'success': True,
                    'message': '密码已重置为初始密码',
                    'default_password': DEFAULT_PASSWORD})


# ===== 首页 =====

@app.route('/')
@login_required
def index():
    """首页 - 导航"""
    return render_template('index.html')


@app.route('/change-password')
@login_required
def change_password_page():
    """修改密码页面（工号 + 新密码）"""
    user = get_current_user()
    return render_template('change_password.html', user=user)


@app.route('/api/change-password', methods=['POST'])
@api_login_required
def api_change_password():
    """修改本人登录密码；工号必须与当前登录用户一致"""
    user = get_current_user()
    data = request.json or {}
    employee_id = str(data.get('employee_id', '')).strip()
    new_password = str(data.get('new_password', ''))

    if not employee_id:
        return jsonify({'success': False, 'message': '请输入工号'}), 400
    if not new_password:
        return jsonify({'success': False, 'message': '请输入新密码'}), 400
    if len(new_password) < 4:
        return jsonify({'success': False, 'message': '新密码至少 4 位'}), 400
    if employee_id != str(user.get('employee_id', '')).strip():
        return jsonify({'success': False, 'message': '只能修改本人密码（工号需与当前登录账号一致）'}), 403
    if not get_user(employee_id):
        return jsonify({'success': False, 'message': '该工号不存在'}), 404
    if not set_user_password(employee_id, new_password):
        return jsonify({'success': False, 'message': '保存失败，请重试'}), 500

    add_history(f'修改密码: {user.get("name", "")}({employee_id})',
                user.get('name', employee_id), employee_id, get_client_ip())
    return jsonify({'success': True, 'message': '密码修改成功'})


# ===== 部门人员信息 =====

@app.route('/department')
@login_required
def department():
    """部门人员信息页面"""
    user = get_current_user()
    allowed = sorted(personnel_allowed_depts(user.get('can_edit_personnel_file', 'NO')))
    return render_template('dashboard.html', departments=DEPARTMENTS,
                           can_edit=user.get('can_edit_department', False),
                           personnel_depts=allowed)


def _parse_level(value):
    """从级别文本中取数字（如 '9级' -> 9）；无数字返回 None"""
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return int(digits) if digits else None


def _row_value(row, key, default=''):
    """按列名取值（忽略大小写与首尾空白，兼容 'Skill 名称' / 'skill 名称' 之类的写法）"""
    if not isinstance(row, dict):
        return default
    if key in row and row[key] not in (None, ''):
        return row[key]
    target = str(key).strip().lower()
    for k, v in row.items():
        if isinstance(k, str) and k.strip().lower() == target and v not in (None, ''):
            return v
    return default


def _dept_sheet_rows(keyword, dept):
    """从名称含 keyword 的收集表格中取「部门 == dept」的行；返回 (表名, 表头, 行列表)
    部门写法会先归一化（HWTE5 → 五部，硬件测试开发五部 → 五部）。"""
    sheet = find_collector_sheet_by_name(keyword)
    if not sheet:
        return None, [], []
    headers = sheet.get('headers', [])
    # 找“部门”列（兼容 department）
    dept_col = None
    for h in headers:
        if h == '部门' or str(h).lower() in ('部门', 'department'):
            dept_col = h
            break
    rows = []
    for r in sheet.get('rows', []):
        if dept_col:
            val = _row_value(r, dept_col, r.get('部门', r.get('department', '')))
            if normalize_dept(val) != dept:
                continue
        rows.append(r)
    return sheet.get('name', ''), headers, rows


@app.route('/department/analysis/<dept>')
@login_required
def department_analysis(dept):
    """部门分析页面（点击部门大卡片进入）；需部门信息编辑权限（can_edit_department）"""
    if dept not in DEPT_SHORT_NAMES:
        return redirect(url_for('department'))

    user = get_current_user()
    if not user.get('can_edit_department', False):
        return redirect(url_for('department'))

    current = get_department_detail(dept).get('current', [])

    # 1) 级别分布
    dist = {}
    for m in current:
        lv = _parse_level(m.get('level'))
        dist[lv] = dist.get(lv, 0) + 1
    known_levels = sorted([k for k in dist if k is not None])
    level_dist = [{'label': f'{k} 级', 'count': dist[k], 'num': k} for k in known_levels]
    if None in dist:
        level_dist.append({'label': '未知', 'count': dist[None], 'num': None})
    max_count = max([d['count'] for d in level_dist], default=0) or 1

    # 2) 人员占比：9 级及以上 / 9 级以下
    total = len(current)
    high = sum(v for k, v in dist.items() if k is not None and k >= 9)
    low = total - high
    high_pct = round(high * 100.0 / total, 1) if total else 0
    low_pct = round(100 - high_pct, 1) if total else 0

    # 3)/4) 惩罚 / 奖励信息（来自员工档案的奖惩信息）
    punish_list, reward_list = [], []
    for f in get_personnel_files_by_dept(dept):
        rw, pu = classify_reward_punishment(f.get('reward_punishment'))
        if pu:
            punish_list.append({'name': f.get('name', ''), 'employee_id': f.get('employee_id', ''),
                                'info': '\n'.join(pu)})
        if rw:
            reward_list.append({'name': f.get('name', ''), 'employee_id': f.get('employee_id', ''),
                                'info': '\n'.join(rw)})

    # 5)/6)/7) 来自数据收集的 Tracker
    patent_name, patent_headers, patent_rows = _dept_sheet_rows('专利', dept)
    rd_name, rd_headers, rd_rows = _dept_sheet_rows('研发立项', dept)
    inc_name, inc_headers, inc_rows = _dept_sheet_rows('激励专案', dept)

    # 8) Skills 开发信息（数据收集 · Skills Tracker；部门列 HWTE5~8 统一显示为 五~八部）
    skills_name, _skills_headers, skills_raw = _dept_sheet_rows('Skills', dept)
    skills_list = [{
        '部门': dept,
        'Skill 名称': _row_value(r, 'Skill 名称', r.get('skill 名称', '')),
        '描述': _row_value(r, '描述', ''),
        'DRI': _row_value(r, 'DRI', r.get('dri', '')),
    } for r in skills_raw]

    return render_template(
        'department_analysis.html', dept=dept, total=total,
        level_dist=level_dist, max_count=max_count,
        high=high, low=low, high_pct=high_pct, low_pct=low_pct,
        punish_list=punish_list, reward_list=reward_list,
        patent_name=patent_name, patent_headers=patent_headers, patent_rows=patent_rows,
        rd_name=rd_name, rd_headers=rd_headers, rd_rows=rd_rows,
        inc_name=inc_name, inc_headers=inc_headers, inc_rows=inc_rows,
        skills_name=skills_name, skills_list=skills_list)


# ===== KPI 管理：横向对比四个部门（五/六/七/八部）=====
KPI_DEPT_COLORS = {'五部': '#0071E3', '六部': '#34C759', '七部': '#FF9500', '八部': '#AF52DE'}


def _parse_number(value):
    """把 '77.5%' / '0.775' / '80' 解析为数值；失败返回 None"""
    if value is None:
        return None
    s = str(value).strip().replace(',', '')
    if not s:
        return None
    has_pct = s.endswith('%')
    if has_pct:
        s = s[:-1].strip()
    m = re.search(r'-?\d+(?:\.\d+)?', s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _info_table_by_keyword(keyword):
    """按名称关键字（不区分大小写）查找信息表"""
    kw = str(keyword).lower()
    for t in get_all_info_list():
        if kw in str(t.get('name', '')).lower():
            return t
    return None


def _nre_section():
    """NRE 比例：Station DRI(五部+六部) 与 Camera(七部+八部)。
    优先使用表中现成的功能部门行；若表内是 五/六/七/八部 明细行，
    则按「在职 ÷ NRE HC」合并计算（表格中 Station DRI 62/80=77.5%、Camera 66/88=75%）。"""
    table = _info_table_by_keyword('NRE')
    direct, grouped = {}, {'Station DRI': {'hc': 0.0, 'nre': 0.0}, 'Camera': {'hc': 0.0, 'nre': 0.0}}
    if table:
        for r in table.get('rows', []) or []:
            dept = str(r.get('部门', r.get('department', '')) or '').strip()
            if not dept:
                continue
            low = dept.lower()
            if 'station' in low or 'camera' in low:
                label = 'Station DRI' if 'station' in low else 'Camera'
                ratio = _parse_number(r.get('NRE 比例', r.get('NRE比例', '')))
                if ratio is not None:
                    direct[label] = ratio
                continue
            if dept in ('五部', '六部'):
                key = 'Station DRI'
            elif dept in ('七部', '八部'):
                key = 'Camera'
            else:
                continue
            hc = _parse_number(r.get('在职', ''))
            nre = _parse_number(r.get('NRE HC', r.get('NREHC', '')))
            if hc is not None:
                grouped[key]['hc'] += hc
            if nre is not None:
                grouped[key]['nre'] += nre

    items = []
    for label, sub, color in (('Station DRI', '五部 + 六部', '#0071E3'),
                              ('Camera', '七部 + 八部', '#FF9500')):
        ratio = direct.get(label)
        if ratio is None and grouped[label]['nre']:
            ratio = round(grouped[label]['hc'] * 100.0 / grouped[label]['nre'], 1)
        items.append({'label': label, 'sub': sub, 'color': color, 'value': ratio})

    mx = max([i['value'] or 0 for i in items], default=0)
    for i in items:
        # 横向柱状图满刻度为 100%：条形长度 = 比例本身（77.5% 的柱子不会拉满）
        i['pct'] = round(i['value'] or 0, 1)
    return {'title': 'NRE 比例对比', 'note': 'Station DRI（五部+六部） vs Camera（七部+八部）',
            'source': table.get('name') if table else '', 'unit': '%',
            'bars': items, 'max': mx}


def _sheet_dept_counts(keyword):
    """收集表格：按部门列统计各部的行数（信息数量）；部门写法归一化（HWTE5 → 五部）"""
    counts = {d: 0 for d in DEPT_SHORT_NAMES}
    sheet = find_collector_sheet_by_name(keyword)
    if sheet:
        for r in sheet.get('rows', []) or []:
            dept = normalize_dept(_row_value(r, '部门', r.get('department', '')))
            if dept in counts:
                counts[dept] += 1
    return counts, (sheet.get('name') or '' if sheet else '')


def _reward_punish_counts():
    """员工档案 · 奖惩信息：按部门统计奖励 / 惩罚条数"""
    reward = {d: 0 for d in DEPT_SHORT_NAMES}
    punish = {d: 0 for d in DEPT_SHORT_NAMES}
    for dept in DEPT_SHORT_NAMES:
        for f in get_personnel_files_by_dept(dept):
            rw, pu = classify_reward_punishment(f.get('reward_punishment'))
            reward[dept] += len(rw)
            punish[dept] += len(pu)
    return punish, reward


def _count_section(title, note, source, counts, anchor):
    """把各部数量整理为图表所需结构（pct 为相对本组最大值的条形宽度百分比）；
    anchor 为部门分析页面中对应表格板块的锚点（点击柱条跳转用）。"""
    mx = max(counts.values()) if counts else 0
    items = []
    for d in DEPT_SHORT_NAMES:
        n = counts.get(d, 0)
        items.append({'label': d, 'value': n, 'color': KPI_DEPT_COLORS[d], 'anchor': anchor,
                      'pct': round(n * 100.0 / mx, 1) if mx else 0})
    return {'title': title, 'note': note, 'source': source, 'unit': '条',
            'bars': items, 'max': mx, 'total': sum(counts.values())}


@app.route('/kpi')
@login_required
def kpi_manage():
    """KPI 管理页面：横向对比四部（NRE 比例 / 激励专案 / 专利 / 研发立项 / 惩罚 / 奖励）
    需部门信息编辑权限（can_edit_department），与历史记录一致。"""
    user = get_current_user()
    if not user.get('can_edit_department', False):
        return redirect(url_for('index'))

    nre = _nre_section()

    inc_counts, inc_source = _sheet_dept_counts('激励专案')
    patent_counts, patent_source = _sheet_dept_counts('专利')
    rd_counts, rd_source = _sheet_dept_counts('研发立项')
    skills_counts, skills_source = _sheet_dept_counts('Skills')
    punish_counts, reward_counts = _reward_punish_counts()

    sections = [
        _count_section('激励专案数量对比', '四部激励专案数量差异', inc_source, inc_counts, 'incentive'),
        _count_section('专利数量对比', '四部专利数量差异', patent_source, patent_counts, 'patent'),
        _count_section('研发立项数量对比', '四部研发立项数量差异', rd_source, rd_counts, 'rd'),
        _count_section('Skill 开发数量对比', '四部 Skill 开发数量差异', skills_source, skills_counts, 'skills'),
        _count_section('惩罚信息数量对比', '四部员工惩罚信息条数差异',
                       '员工档案 · 奖惩信息', punish_counts, 'punish'),
        _count_section('奖励信息数量对比', '四部员工奖励信息条数差异',
                       '员工档案 · 奖惩信息', reward_counts, 'reward'),
    ]
    return render_template('kpi.html', nre=nre, sections=sections)



@app.route('/api/department/summary')
@api_login_required
def api_department_summary():
    """获取部门人员汇总（无月份参数）"""
    summary = get_department_summary()
    return jsonify(summary)


@app.route('/api/department/detail')
@api_login_required
def api_department_detail():
    """获取部门人员详细
    Query params:
        department: 部门名称（五部/六部/七部/八部）
    """
    dept = request.args.get('department', '')
    if dept not in DEPT_SHORT_NAMES:
        return jsonify({'success': False, 'message': f'未知部门: {dept}'}), 400
    data = get_department_detail(dept)
    return jsonify(data)


@app.route('/api/department/all')
@api_login_required
def api_department_all():
    """获取所有部门人员汇总"""
    data = get_department_all()
    return jsonify(data)


@app.route('/api/department/members')
@api_login_required
def api_department_members():
    """获取指定部门的所有成员
    Query params:
        department: 部门名称（全体/五部/六部/七部/八部）
    """
    dept = request.args.get('department', '')
    members = get_department_staff(dept if dept else None)
    return jsonify({'members': members})


@app.route('/api/department/add-member', methods=['POST'])
def api_department_add_member():
    """入职：把人员加入指定部门，并写入入职记录"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    data = request.json
    dept = data.get('department', '')
    member = {
        'employee_id': data.get('employee_id', ''),
        'name': data.get('name', ''),
        'level': data.get('level', ''),
        'phone': data.get('phone', ''),
        'email': data.get('email', '')
    }
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    
    if dept not in DEPT_SHORT_NAMES:
        return jsonify({'success': False, 'message': f'未知部门: {dept}'}), 400
    
    if not member['employee_id'] or not member['name']:
        return jsonify({'success': False, 'message': '工号和姓名不能为空'}), 400
    
    ip_address = get_client_ip()
    employee_id = user.get('employee_id', '')
    success = add_staff_to_department(dept, member, operator, employee_id, ip_address)
    if not success:
        return jsonify({'success': False, 'message': '该员工已在此部门在职（工号重复）'}), 400
    
    join_date = (data.get('date') or '').strip() or datetime.now().strftime('%Y-%m-%d')
    add_joined_record({
        'department': dept,
        'name': member['name'],
        'reason': (data.get('reason') or '').strip(),
        'date': join_date
    }, operator, employee_id, ip_address)
    
    return jsonify({'success': True})


@app.route('/api/department/update-member', methods=['POST'])
def api_department_update_member():
    """编辑当前在职人员的信息（姓名/级别/电话/邮箱）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    data = request.json
    dept = data.get('department', '')
    employee_id = data.get('employee_id', '')
    fields = {
        'name': data.get('name', ''),
        'level': data.get('level', ''),
        'phone': data.get('phone', ''),
        'email': data.get('email', '')
    }
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    ok = update_staff_member(dept, employee_id, fields, operator, op_employee_id, ip_address)
    if not ok:
        return jsonify({'success': False, 'message': '未找到该在职人员'}), 400
    return jsonify({'success': True})


@app.route('/api/department/record/update', methods=['POST'])
def api_department_record_update():
    """编辑某条入职/离职记录（type: joined/left，字段: name/date/reason）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403

    data = request.json or {}
    rec_type = data.get('type', '')
    try:
        rec_id = int(data.get('id', 0))
    except (TypeError, ValueError):
        rec_id = 0
    if rec_type not in ('joined', 'left'):
        return jsonify({'success': False, 'message': '记录类型不正确'}), 400
    if rec_id <= 0:
        return jsonify({'success': False, 'message': '缺少记录ID'}), 400

    ok = update_department_record(rec_type, rec_id, {
        'name': data.get('name', ''),
        'date': data.get('date', ''),
        'reason': data.get('reason', '')
    })
    if not ok:
        return jsonify({'success': False, 'message': '未找到该记录或未做修改'}), 400
    return jsonify({'success': True})


@app.route('/api/department/record/delete', methods=['POST'])
def api_department_record_delete():
    """删除某条入职/离职记录（type: joined/left）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403

    data = request.json or {}
    rec_type = data.get('type', '')
    try:
        rec_id = int(data.get('id', 0))
    except (TypeError, ValueError):
        rec_id = 0
    if rec_type not in ('joined', 'left'):
        return jsonify({'success': False, 'message': '记录类型不正确'}), 400
    if rec_id <= 0:
        return jsonify({'success': False, 'message': '缺少记录ID'}), 400

    ok = delete_department_record(rec_type, rec_id)
    if not ok:
        return jsonify({'success': False, 'message': '记录不存在或已删除'}), 400
    return jsonify({'success': True})


@app.route('/api/department/remove-member', methods=['POST'])
def api_department_remove_member():
    """从指定部门移除人员"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    data = request.json
    dept = data.get('department', '')
    employee_id = data.get('employee_id', '')
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    
    if dept not in DEPT_SHORT_NAMES:
        return jsonify({'success': False, 'message': f'未知部门: {dept}'}), 400
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    success = remove_staff_from_department(dept, employee_id, operator, op_employee_id, ip_address)
    if not success:
        return jsonify({'success': False, 'message': '未找到该员工'}), 400
    
    return jsonify({'success': True})


@app.route('/api/department/update-members', methods=['POST'])
def api_department_update_members():
    """更新部门成员列表（批量替换）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    data = request.json
    dept = data.get('department', '')
    members = data.get('members', [])
    
    if dept not in DEPT_SHORT_NAMES:
        return jsonify({'success': False, 'message': f'未知部门: {dept}'}), 400
    
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    ip_address = get_client_ip()
    employee_id = user.get('employee_id', '')
    update_department_members(dept, members, operator, employee_id, ip_address)
    
    return jsonify({'success': True})


@app.route('/api/department/add-left', methods=['POST'])
def api_department_add_left():
    """离职：写入离职记录，并同步把该人员从在职列表移除"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    data = request.json
    dept = data.get('department', '')
    name = data.get('name', '')
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    
    if dept not in DEPT_SHORT_NAMES:
        return jsonify({'success': False, 'message': f'未知部门: {dept}'}), 400
    if not name:
        return jsonify({'success': False, 'message': '姓名不能为空'}), 400
    
    record = {
        'name': name,
        'department': dept,
        'reason': data.get('reason', ''),
        'date': data.get('date', '')
    }
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    # 从在职列表移除：优先按工号，其次按该部门内唯一姓名匹配
    employee_id = (data.get('employee_id') or '').strip()
    emp_to_remove = employee_id or find_staff_id_by_name(dept, name)
    removed = False
    if emp_to_remove:
        removed = remove_staff_from_department(dept, emp_to_remove, operator, op_employee_id, ip_address)
    
    add_left_record(record, operator, op_employee_id, ip_address)
    
    message = ''
    if not removed:
        message = '已记录离职。但未能在在职列表中找到匹配人员，未自动移除（如工号留空且存在同名人员，请填写工号）'
    
    return jsonify({'success': True, 'message': message, 'removed': removed})


@app.route('/api/department/export')
@api_login_required
def api_department_export():
    """导出人员信息为 Excel（需部门编辑权限）"""
    user = get_current_user()
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限导出部门信息，请联系主管开通权限'}), 403
    dept = request.args.get('department', '全体')
    
    try:
        excel_data = export_staff_to_excel(dept if dept else None)
        
        from urllib.parse import quote
        dept_label = "全体" if dept in ['', '全体', None] else dept
        filename = f"人员信息-HWTE_{dept_label}.xlsx"
        encoded_filename = quote(filename)
        
        response = Response(
            excel_data,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
        return response
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/api/department/import', methods=['POST'])
def api_department_import():
    """从 Excel 导入人员信息"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '没有上传文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '没有选择文件'}), 400
    
    # 可选：指定导入到哪个部门
    dept = request.form.get('department', '')
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    try:
        file_content = file.read()
        result = import_staff_from_excel(file_content, dept if dept else None, operator, op_employee_id, ip_address)
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


# ===== 员工档案（人事档案）=====

@app.route('/personnel-file/<employee_id>')
@login_required
def personnel_file(employee_id):
    """员工档案信息页面（需 can_edit_personnel_file 对应部门权限）"""
    user = get_current_user()
    record = get_personnel_file(employee_id)
    if not record:
        return "未找到该员工档案", 404
    if not can_access_personnel_file(user, record.get('department', '')):
        return redirect(url_for('department'))
    return render_template('personnel_file.html', record=record, can_edit=True)


@app.route('/api/personnel-file/<employee_id>', methods=['POST'])
def api_personnel_file_update(employee_id):
    """编辑员工档案"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    user = session['user']
    record = get_personnel_file(employee_id)
    if not record:
        return jsonify({'success': False, 'message': '未找到该员工档案'}), 404
    if not can_access_personnel_file(user, record.get('department', '')):
        return jsonify({'success': False, 'message': '您没有权限编辑该员工档案'}), 403

    data = request.json or {}
    update_personnel_file(employee_id, {
        'join_date': data.get('join_date', ''),
        'title': data.get('title', ''),
        'level': data.get('level', ''),
        'salary': data.get('salary', ''),
        'equity': data.get('equity', ''),
        'promotion': data.get('promotion', ''),
        'reward_punishment': data.get('reward_punishment', '')
    })
    add_history(f"更新员工档案: {record.get('name', employee_id)}({employee_id})",
                user.get('name', user.get('employee_id', 'Unknown')),
                user.get('employee_id', ''), get_client_ip())
    return jsonify({'success': True})


# ===== Action Items =====

@app.route('/action-items')
@login_required
def action_items():
    """Action Items 页面"""
    user = get_current_user()
    return render_template('action_items.html', can_edit=user.get('can_edit_action_items', False))


@app.route('/api/action-items')
@api_login_required
def api_action_items():
    """获取所有 Action Items 及列配置"""
    items = get_all_action_items()
    return jsonify({'items': items, 'columns': get_action_columns()})


@app.route('/api/action-items/columns', methods=['POST'])
def api_action_items_columns():
    """修改 Action Items 的列（表头改名 / 增加列 / 删除自定义列）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    user = session['user']
    if not user.get('can_edit_action_items', False):
        return jsonify({'success': False, 'message': '您没有权限修改Action Items，请联系主管开通权限'}), 403
    data = request.json or {}
    columns = data.get('columns', [])
    if not set_action_columns(columns):
        return jsonify({'success': False, 'message': '列配置无效（内置列必须保留）'}), 400
    add_history('修改 Action Items 表头', user.get('name', 'Unknown'),
                user.get('employee_id', ''), get_client_ip())
    return jsonify({'success': True})


@app.route('/api/action-items', methods=['POST'])
def api_action_items_add():
    """添加 Action Item"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_action_items', False):
        return jsonify({'success': False, 'message': '您没有权限修改Action Items，请联系主管开通权限'}), 403
    
    data = request.json
    ip_address = get_client_ip()
    add_action_item({
        'title': data['title'],
        'dri': data.get('dri', ''),
        'eta': data.get('eta', ''),
        'progress': data.get('progress', ''),
        'status': '进行中',
        'extra': data.get('extra', {}),
        'operator': user.get('name', user.get('employee_id', 'Unknown'))
    }, ip_address, user.get('employee_id', ''))
    return jsonify({'success': True})


@app.route('/api/action-items/<int:item_id>', methods=['PUT'])
def api_action_items_update(item_id):
    """更新 Action Item"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_action_items', False):
        return jsonify({'success': False, 'message': '您没有权限修改Action Items，请联系主管开通权限'}), 403
    
    data = request.json
    data['operator'] = user.get('name', user.get('employee_id', 'Unknown'))
    ip_address = get_client_ip()
    update_action_item(item_id, data, ip_address, user.get('employee_id', ''))
    return jsonify({'success': True})


@app.route('/api/action-items/<int:item_id>', methods=['DELETE'])
def api_action_items_delete(item_id):
    """删除 Action Item"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_action_items', False):
        return jsonify({'success': False, 'message': '您没有权限修改Action Items，请联系主管开通权限'}), 403
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    delete_action_item(item_id, user.get('name', user.get('employee_id', 'Unknown')), op_employee_id, ip_address)
    return jsonify({'success': True})


# ===== 信息列表 =====

@app.route('/info-list')
@login_required
def info_list():
    """信息列表页面"""
    user = get_current_user()
    return render_template('info_list.html', can_edit=user.get('can_edit_info_list', False))


@app.route('/api/info-list')
@api_login_required
def api_info_list():
    """获取所有信息表"""
    tables = get_all_info_list()
    return jsonify({'tables': tables})


@app.route('/api/info-list', methods=['POST'])
def api_info_list_add():
    """创建信息表或添加数据"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_info_list', False):
        return jsonify({'success': False, 'message': '您没有权限修改信息列表，请联系主管开通权限'}), 403
    
    data = request.json
    action = data.get('action', '')
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    if action == 'create_table':
        name = data.get('name', '').strip()
        headers = data.get('headers', [])
        if not name:
            return jsonify({'success': False, 'message': '请输入信息表名称'}), 400
        operator = user.get('name', user.get('employee_id', 'Unknown'))
        create_info_table(name, headers, operator, op_employee_id, ip_address)
        return jsonify({'success': True})
    
    elif action == 'add_row':
        table_id = data.get('table_id')
        row = data.get('row', {})
        if not table_id:
            return jsonify({'success': False, 'message': '缺少表ID'}), 400
        operator = user.get('name', user.get('employee_id', 'Unknown'))
        add_info_row(table_id, row, operator, op_employee_id, ip_address)
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': '未知操作'}), 400


@app.route('/api/info-list/<int:table_id>', methods=['PUT'])
def api_info_list_update(table_id):
    """更新信息表数据"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_info_list', False):
        return jsonify({'success': False, 'message': '您没有权限修改信息列表，请联系主管开通权限'}), 403
    
    data = request.json
    action = data.get('action', '')
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    if action == 'update_row':
        row_index = data.get('row_index')
        row = data.get('row', {})
        if row_index is None:
            return jsonify({'success': False, 'message': '缺少行索引'}), 400
        operator = user.get('name', user.get('employee_id', 'Unknown'))
        update_info_row(table_id, row_index, row, operator, op_employee_id, ip_address)
        return jsonify({'success': True})

    elif action == 'update_headers':
        headers = data.get('headers', [])
        if not headers:
            return jsonify({'success': False, 'message': '表头不能为空'}), 400
        operator = user.get('name', user.get('employee_id', 'Unknown'))
        ok = update_info_table_headers(table_id, headers, operator, op_employee_id, ip_address)
        if not ok:
            return jsonify({'success': False, 'message': '保存表头失败'}), 400
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': '未知操作'}), 400


@app.route('/api/info-list/<int:table_id>', methods=['DELETE'])
def api_info_list_delete(table_id):
    """删除信息表或数据"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_info_list', False):
        return jsonify({'success': False, 'message': '您没有权限修改信息列表，请联系主管开通权限'}), 403
    
    data = request.json or {}
    delete_type = data.get('type', 'table')
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    if delete_type == 'row':
        row_index = data.get('row_index')
        if row_index is None:
            return jsonify({'success': False, 'message': '缺少行索引'}), 400
        operator = user.get('name', user.get('employee_id', 'Unknown'))
        delete_info_row(table_id, row_index, operator, op_employee_id, ip_address)
        return jsonify({'success': True})
    else:
        operator = user.get('name', user.get('employee_id', 'Unknown'))
        delete_info_table(table_id, operator, op_employee_id, ip_address)
        return jsonify({'success': True})


# ===== 数据收集表格 =====

@app.route('/collector')
@login_required
def collector():
    """数据收集页面"""
    sheets = get_collector_sheets()
    user = get_current_user()
    # can_lock：是否可操作“锁定”图标（与部门信息编辑权限绑定）
    return render_template('collector.html', sheets=sheets, can_edit=True,
                           can_lock=user.get('can_edit_department', False))


@app.route('/collector/<int:sheet_id>')
@login_required
def collector_sheet(sheet_id):
    """单个收集表格页面"""
    sheet = get_collector_sheet(sheet_id)
    if not sheet:
        return "Sheet not found", 404
    return render_template('collector_sheet.html', sheet=sheet, can_edit=True)


@app.route('/api/collector', methods=['GET'])
@api_login_required
def api_collector_list():
    """获取所有收集表格"""
    sheets = get_collector_sheets()
    return jsonify(sheets)


@app.route('/api/collector', methods=['POST'])
def api_collector_create():
    """创建收集表格（需要登录）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    data = request.json
    user = session['user']
    ip_address = get_client_ip()
    create_collector_sheet({
        'name': data['name'],
        'headers': data.get('headers', []),
        'rows': [],
        'operator': user.get('name', user.get('employee_id', 'Unknown'))
    }, ip_address, user.get('employee_id', ''))
    return jsonify({'success': True})


@app.route('/api/collector/<int:sheet_id>/row', methods=['POST'])
def api_collector_add_row(sheet_id):
    """添加行"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    data = request.json
    user = session['user']
    data['operator'] = user.get('name', user.get('employee_id', 'Unknown'))
    ip_address = get_client_ip()
    add_collector_row(sheet_id, data, ip_address, user.get('employee_id', ''))
    return jsonify({'success': True})


@app.route('/api/collector/<int:sheet_id>/row/<int:row_index>', methods=['PUT'])
def api_collector_update_row(sheet_id, row_index):
    """更新行"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    data = request.json
    user = session['user']
    data['operator'] = user.get('name', user.get('employee_id', 'Unknown'))
    ip_address = get_client_ip()
    update_collector_row(sheet_id, row_index, data, ip_address, user.get('employee_id', ''))
    return jsonify({'success': True})


@app.route('/api/collector/<int:sheet_id>/row/<int:row_index>', methods=['DELETE'])
def api_collector_delete_row(sheet_id, row_index):
    """删除行（只允许本人删除自己的数据）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    current_user_name = user.get('name', user.get('employee_id', 'Unknown'))
    
    # 权限验证：获取该行的原始 operator，检查是否匹配当前用户
    sheet = get_collector_sheet(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '表格不存在'}), 404
    
    rows = sheet.get('rows', [])
    if row_index < 0 or row_index >= len(rows):
        return jsonify({'success': False, 'message': '行不存在'}), 404
    
    row_operator = rows[row_index].get('operator', '')
    if row_operator and row_operator != current_user_name:
        return jsonify({'success': False, 'message': '只能删除自己的数据'}), 403
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    delete_collector_row(sheet_id, row_index, current_user_name, op_employee_id, ip_address)
    return jsonify({'success': True})


@app.route('/api/collector/<int:sheet_id>/batch-delete', methods=['POST'])
def api_collector_batch_delete(sheet_id):
    """批量删除行（所有用户都有权限）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    current_user_name = user.get('name', user.get('employee_id', 'Unknown'))
    
    data = request.json
    indices = data.get('indices', [])
    
    if not indices:
        return jsonify({'success': False, 'message': '请选择要删除的数据'}), 400
    
    sheet = get_collector_sheet(sheet_id)
    if not sheet:
        return jsonify({'success': False, 'message': '表格不存在'}), 404
    
    rows = sheet.get('rows', [])
    
    # 验证所有行存在
    for idx in indices:
        if idx < 0 or idx >= len(rows):
            return jsonify({'success': False, 'message': f'行不存在'}), 404
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    # 从大到小排序删除，确保索引不会错位
    for idx in sorted(indices, reverse=True):
        delete_collector_row(sheet_id, idx, current_user_name, op_employee_id, ip_address)
    
    return jsonify({'success': True, 'deleted_count': len(indices)})


@app.route('/api/collector/<int:sheet_id>', methods=['DELETE'])
def api_collector_delete_sheet(sheet_id):
    """删除表格（已锁定的表格不允许删除）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    if is_collector_sheet_locked(sheet_id):
        return jsonify({'success': False, 'message': '该表格已锁定，无法删除（请先解锁）'}), 403
    delete_collector_sheet(sheet_id, user.get('name', user.get('employee_id', 'Unknown')), op_employee_id, ip_address)
    return jsonify({'success': True})


@app.route('/api/collector/<int:sheet_id>/lock', methods=['POST'])
def api_collector_toggle_lock(sheet_id):
    """锁定/解锁收集表格（需要部门信息编辑权限）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限操作表格锁定，请联系主管开通权限'}), 403
    data = request.json or {}
    locked = bool(data.get('locked', False))
    ok = set_collector_sheet_locked(sheet_id, locked,
                                    user.get('name', user.get('employee_id', 'Unknown')),
                                    user.get('employee_id', ''), get_client_ip())
    if not ok:
        return jsonify({'success': False, 'message': '表格不存在'}), 404
    return jsonify({'success': True, 'locked': locked})


@app.route('/api/collector/<int:sheet_id>/headers', methods=['POST'])
def api_collector_update_headers(sheet_id):
    """修改收集表格的表头（重命名/新增/删除列）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    user = session['user']
    data = request.json or {}
    headers = data.get('headers', [])
    if not headers:
        return jsonify({'success': False, 'message': '表头不能为空'}), 400
    ok = update_collector_sheet_headers(
        sheet_id, headers,
        user.get('name', user.get('employee_id', 'Unknown')),
        user.get('employee_id', ''), get_client_ip())
    if not ok:
        return jsonify({'success': False, 'message': '保存表头失败'}), 400
    return jsonify({'success': True})


@app.route('/api/collector/<int:sheet_id>/export')
@api_login_required
def api_collector_export(sheet_id):
    """导出 CSV"""
    sheet = get_collector_sheet(sheet_id)
    if not sheet:
        return "Sheet not found", 404
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # 写入表头
    headers = sheet.get('headers', [])
    writer.writerow(['序号'] + headers)
    
    # 写入数据行
    for idx, row in enumerate(sheet.get('rows', []), start=1):
        row_data = [str(idx)] + [row.get(h.lower(), '') for h in headers]
        writer.writerow(row_data)
    
    output.seek(0)
    
    # 生成安全的文件名（URL 编码处理中文）
    from urllib.parse import quote
    filename = sheet['name'] + '.csv'
    encoded_filename = quote(filename)
    
    response = Response(
        output.getvalue(),
        mimetype='text/csv',
        content_type='text/csv; charset=utf-8'
    )
    response.headers['Content-Disposition'] = f'attachment; filename*=UTF-8\'\'{encoded_filename}'
    return response


@app.route('/api/collector/<int:sheet_id>/import', methods=['POST'])
def api_collector_import(sheet_id):
    """导入 CSV / Excel（.xlsx/.xls）"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    # 检查是否有文件
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '请选择要上传的文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '请选择要上传的文件'}), 400
    
    # 检查文件类型：CSV 或 Excel
    fname = file.filename.lower()
    if not fname.endswith(('.csv', '.xlsx', '.xls', '.xlsm')):
        return jsonify({'success': False, 'message': '只支持 CSV 或 Excel（.xlsx/.xls）格式文件'}), 400
    
    # 读取并解析文件（CSV/Excel 统一处理）
    try:
        file_content = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)
        rows = read_tabular_rows(file.filename, file_content)
        
        if len(rows) < 2:
            return jsonify({'success': False, 'message': '文件内容为空或格式错误（至少需要表头+1行数据）'}), 400
        
        # 获取文件表头
        file_headers = [(h or '').strip() for h in rows[0]]
        
        # 获取表格的表头
        sheet = get_collector_sheet(sheet_id)
        if not sheet:
            return jsonify({'success': False, 'message': '表格不存在'}), 404
        
        expected_headers = sheet.get('headers', [])
        
        # 建立 文件表头 -> 索引 的映射
        file_header_map = {}
        for idx, h in enumerate(file_headers):
            if h:
                file_header_map[h] = idx
        
        # 检查是否有匹配的列
        matched_headers = [h for h in expected_headers if h in file_header_map]
        if not matched_headers:
            return jsonify({'success': False, 'message': '文件中没有与表格匹配的列，无法导入。请确认文件表头与表格表头一致'}), 400
        
        # 导入数据行
        user = session['user']
        ip_address = get_client_ip()
        imported_count = 0
        skipped_count = 0
        
        for row in rows[1:]:  # 跳过表头
            has_data = False
            row_data = {}
            
            for header in matched_headers:
                idx = file_header_map[header]
                value = row[idx].strip() if idx < len(row) and row[idx] is not None else ''
                row_data[header.lower()] = value
                if value:
                    has_data = True
            
            # 跳过空行或所有匹配列都为空的行
            if not has_data:
                skipped_count += 1
                continue
            
            row_data['operator'] = user.get('name', user.get('employee_id', 'Unknown'))
            add_collector_row(sheet_id, row_data, ip_address)
            imported_count += 1
        
        return jsonify({
            'success': True, 
            'message': f'成功导入 {imported_count} 条数据' + (f'，跳过 {skipped_count} 条空行' if skipped_count > 0 else ''),
            'imported_count': imported_count,
            'skipped_count': skipped_count
        })
        
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'}), 500


# ===== 历史记录 =====

@app.route('/history')
@login_required
def history():
    """历史记录页面（需部门编辑权限）"""
    user = get_current_user()
    if not user.get('can_edit_department', False):
        return redirect(url_for('index'))
    return render_template('history.html')


@app.route('/api/history')
@api_login_required
def api_history():
    """获取历史记录（需部门编辑权限）"""
    user = get_current_user()
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限查看历史记录，请联系主管开通权限'}), 403
    limit = request.args.get('limit', 100, type=int)
    records = get_history(limit)
    return jsonify(records)


# ===== 初始化 =====

init_all_data()

if __name__ == '__main__':
    print("=" * 50)
    print("Station & Camera DRI Management")
    print("部门信息管理与数据收集平台")
    print("=" * 50)
    print("访问地址: http://localhost:5001")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=APP_DEBUG, threaded=True)