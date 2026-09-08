"""
Station & Camera DRI Management Web Server
部门信息管理与数据收集平台
"""
import csv
import io
import json
import os
import secrets
import time
import threading
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, Response, session, redirect, url_for

from data_manager import (
    init_all_data,
    DEPT_SHORT_NAMES,
    get_all_staff, get_department_summary, get_department_detail, get_department_all, get_department_staff,
    add_staff_to_department, remove_staff_from_department, update_department_members, add_left_record,
    get_all_action_items, add_action_item, update_action_item, delete_action_item,
    get_all_info_list, create_info_table, add_info_row, update_info_row, delete_info_table, delete_info_row,
    get_collector_sheets, get_collector_sheet, create_collector_sheet,
    add_collector_row, update_collector_row, delete_collector_row, delete_collector_sheet,
    get_history, add_history,
    export_staff_to_excel, import_staff_from_excel
)

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
    """读取环境变量 SECRET_KEY；否则从项目根目录的 .secret_key 读取；
    都没有则生成一个随机值并落盘保存（避免重启后会话全部失效）。"""
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    key_file = os.path.join(PROJECT_DIR, '.secret_key')
    if os.path.exists(key_file):
        try:
            with open(key_file, 'r', encoding='utf-8') as f:
                k = f.read().strip()
            if k:
                return k
        except OSError:
            pass
    k = secrets.token_hex(32)
    try:
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

DEPARTMENTS = ['五部', '六部', '七部', '八部']


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
    """检查工号是否在 users.json 白名单中"""
    users_file = os.path.join(DATA_DIR, 'users.json')
    
    if not os.path.exists(users_file):
        return False, None
    
    with open(users_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for user in data.get('users', []):
            if user['employee_id'] == employee_id:
                return True, user
    return False, None


def get_user_permissions(employee_id, name):
    """根据工号获取用户权限配置，未配置的工号使用默认权限"""
    users_file = os.path.join(DATA_DIR, 'users.json')
    
    # 默认权限：所有人都可以编辑数据收集，其他需要匹配 users.json
    default_user = {
        'employee_id': employee_id,
        'name': name,
        'can_edit_department': False,
        'can_edit_action_items': False,
        'can_edit_info_list': False,
        'can_edit_collector': True  # 数据收集默认开启
    }
    
    if os.path.exists(users_file):
        with open(users_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for user in data.get('users', []):
                if user['employee_id'] == employee_id:
                    # 合并配置：默认权限 + users.json 中的额外权限
                    result = default_user.copy()
                    result['name'] = name  # 使用登录时输入的姓名
                    result['can_edit_department'] = user.get('can_edit_department', False)
                    result['can_edit_action_items'] = user.get('can_edit_action_items', False)
                    result['can_edit_info_list'] = user.get('can_edit_info_list', False)
                    result['can_edit_collector'] = True  # 数据收集始终可编辑
                    return result
    
    return default_user


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
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
        return redirect('/')
    return render_template('login.html')


@app.route('/api/login', methods=['POST'])
def api_login():
    """登录验证 - 只允许 users.json 中的成员访问（含暴力破解限流）"""
    ip = get_client_ip()
    data = request.json or {}
    employee_id = str(data.get('employee_id', '')).strip()
    name = str(data.get('name', '')).strip()

    if not employee_id or not name:
        return jsonify({'success': False, 'message': '请填写工号和姓名'})

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


# ===== 首页 =====

@app.route('/')
@login_required
def index():
    """首页 - 导航"""
    return render_template('index.html')


# ===== 部门人员信息 =====

@app.route('/department')
@login_required
def department():
    """部门人员信息页面"""
    user = get_current_user()
    return render_template('dashboard.html', departments=DEPARTMENTS, can_edit=user.get('can_edit_department', False))


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
    """添加人员到指定部门"""
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
        return jsonify({'success': False, 'message': '该员工已存在（工号重复）'}), 400
    
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
    """添加离职记录"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    if not user.get('can_edit_department', False):
        return jsonify({'success': False, 'message': '您没有权限修改部门信息，请联系主管开通权限'}), 403
    
    data = request.json
    dept = data.get('department', '')
    name = data.get('name', '')
    operator = user.get('name', user.get('employee_id', 'Unknown'))
    
    record = {
        'name': name,
        'department': dept,
        'reason': data.get('reason', ''),
        'date': data.get('date', '')
    }
    
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    
    # 如果提供了 employee_id，同时从部门移除该人员
    employee_id = data.get('employee_id', '')
    if employee_id and dept in DEPT_SHORT_NAMES:
        remove_staff_from_department(dept, employee_id, operator, op_employee_id, ip_address)
    
    add_left_record(record, operator, op_employee_id, ip_address)
    return jsonify({'success': True})


@app.route('/api/department/export')
@api_login_required
def api_department_export():
    """导出人员信息为 Excel"""
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
    """获取所有 Action Items"""
    items = get_all_action_items()
    return jsonify(items)


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
        'operator': user.get('name', user.get('employee_id', 'Unknown'))
    }, ip_address)
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
    update_action_item(item_id, data, ip_address)
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
    return render_template('collector.html', sheets=sheets, can_edit=True)


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
    }, ip_address)
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
    add_collector_row(sheet_id, data, ip_address)
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
    update_collector_row(sheet_id, row_index, data, ip_address)
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
    """删除表格"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    user = session['user']
    ip_address = get_client_ip()
    op_employee_id = user.get('employee_id', '')
    delete_collector_sheet(sheet_id, user.get('name', user.get('employee_id', 'Unknown')), op_employee_id, ip_address)
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
    """导入 CSV"""
    if 'user' not in session:
        return jsonify({'success': False, 'message': '请先登录'}), 401
    
    # 检查是否有文件
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': '请选择要上传的 CSV 文件'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': '请选择要上传的 CSV 文件'}), 400
    
    # 检查文件类型
    if not file.filename.lower().endswith('.csv'):
        return jsonify({'success': False, 'message': '只支持 CSV 格式文件'}), 400
    
    # 读取并解析 CSV
    try:
        # 读取文件内容（兼容处理 SpooledTemporaryFile）
        file_content = file.read()
        
        # 如果文件已写入 spooled，seek 回开头
        if hasattr(file, 'seek'):
            file.seek(0)
        
        # 尝试用 utf-8-sig 解码（处理 BOM），如果失败则用 utf-8
        try:
            content_str = file_content.decode('utf-8-sig')
        except UnicodeDecodeError:
            content_str = file_content.decode('utf-8')
        
        # 使用 StringIO 解析 CSV
        reader = csv.reader(io.StringIO(content_str))
        rows = list(reader)
        
        if len(rows) < 2:
            return jsonify({'success': False, 'message': 'CSV 文件内容为空或格式错误'}), 400
        
        # 获取 CSV 表头
        csv_headers = [h.strip() for h in rows[0]]
        
        # 获取表格的表头
        sheet = get_collector_sheet(sheet_id)
        if not sheet:
            return jsonify({'success': False, 'message': '表格不存在'}), 404
        
        expected_headers = sheet.get('headers', [])
        
        # 建立 CSV 表头到索引的映射
        csv_header_map = {}
        for idx, csv_header in enumerate(csv_headers):
            csv_header_map[csv_header] = idx
        
        # 检查是否有匹配的列，如果没有匹配的则返回失败
        matched_headers = [h for h in expected_headers if h in csv_header_map]
        if not matched_headers:
            return jsonify({'success': False, 'message': 'CSV 文件中没有匹配的列，无法导入'}), 400
        
        # 导入数据行
        user = session['user']
        ip_address = get_client_ip()
        imported_count = 0
        skipped_count = 0
        
        for row in rows[1:]:  # 跳过表头
            # 检查是否所有匹配列都为空，如果是则跳过该行
            has_data = False
            row_data = {}
            
            for header in matched_headers:
                csv_idx = csv_header_map[header]
                value = row[csv_idx].strip() if csv_idx < len(row) else ''
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
        
    except csv.Error as e:
        return jsonify({'success': False, 'message': f'CSV 解析错误: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'导入失败: {str(e)}'}), 500


# ===== 历史记录 =====

@app.route('/history')
@login_required
def history():
    """历史记录页面"""
    return render_template('history.html')


@app.route('/api/history')
@api_login_required
def api_history():
    """获取历史记录"""
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