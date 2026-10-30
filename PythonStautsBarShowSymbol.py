# -*- coding: utf-8 -*-
"""
PythonStautsBarShowSymbol
=========================

在 Sublime Text 状态栏常驻显示光标所处的 Python 作用域路径（面包屑）。

设计要点
--------
1) 常驻状态项，而不是瞬态消息
   ``sublime.status_message()`` 会整条顶掉状态栏（编码、匹配数、其它插件的
   消息全被覆盖），几秒后还会自动消失。``view.set_status()`` 是一个独立的
   状态槽位，与编辑器原生状态并列显示、互不干扰、可以单独清除。

2) 层级从源码行推导，而不是从符号名
   ST3/ST4 的 ``view.get_symbols()`` 返回的是**符号名**（例如 ``"testFunc"``），
   而不是源码行。旧实现拿符号名算缩进，缩进恒为 0，嵌套层级在 ST3 之后
   其实已经失效了（永远只显示最内层一个符号）。
   现在只用符号 API 取**位置**，缩进与 ``class``/``def`` 类型都回到符号所在
   的源码行现算。

3) 只用 Python 3.3 就有的语法
   包根目录的 ``.python-version`` 声明走现代宿主，但代码本身保持 3.3 兼容，
   在任何宿主下都不会因为语法问题加载失败。

命令
----
* ``nav_back`` / ``nav_forward`` —— 跳转历史前进后退
* ``python_symbol_mark``        —— 把当前位置标记为跳转点
* ``python_symbol_copy``        —— 复制当前作用域路径
* ``python_symbol_toggle``      —— 开关状态栏显示
"""

import os
import re
import time

import sublime
import sublime_plugin


SETTINGS_FILE = "PythonStautsBarShowSymbol.sublime-settings"
STATUS_KEY = "symbol_path"

RE_CLASS = re.compile(r"^([ \t]*)class[ \t]+([A-Za-z_]\w*)")
RE_DEF = re.compile(r"^([ \t]*)(async[ \t]+)?def[ \t]+([A-Za-z_]\w*)")
PY_EXTENSIONS = (".py", ".pyw", ".pyi")

# view_id -> (change_count, symbols)
_SYMBOL_CACHE = {}
# view_id -> (point, chain_key)：用于判断作用域是否发生跳变
_LAST_CONTEXT = {}
# 已经排定刷新任务的 view
_REFRESH_PENDING = set()
# 插件自身触发的跳转不计入跳转历史。
# 存的是抑制截止时间：定位成功立即清零，定位卡住时靠超时兜底。
# 不用固定窗口是因为 _place_cursor 会重试——文件加载慢时定位可能晚于
# 固定窗口，跳转反而被当成用户跳变故记进历史，nav_back 就原地打转了。
_suppress_until = 0.0
SUPPRESS_TIMEOUT = 5.0
# 定位重试上限（约 3 秒），文件死活加载不完时别把定时器拖成僵尸
PLACE_RETRIES = 50


class Settings(object):
    """读取 ``*.sublime-settings`` 并做类型收敛，避免脏配置把插件打挂。"""

    DEFAULTS = {
        "enabled": True,
        "format": "breadcrumb",
        "separator": u"›",
        "wrapper": "pipe",
        "show_file": False,
        "show_kinds": True,
        "show_signature": False,
        "max_depth": 0,
        "syntaxes": ["python"],
        "history_size": 50,
    }

    FORMATS = ("breadcrumb", "dotted", "plain")

    # 状态栏外框，用来和编码、语法等原生状态项区分开
    # 括号类（bracket / angle）贴紧内容，分隔类（pipe / both）内侧留空格
    WRAPPERS = {
        "none": ("", ""),
        "bracket": ("[", "]"),
        "angle": ("<", ">"),
        "pipe": ("| ", " |"),
        "both": ("| [", "] |"),
    }

    def __init__(self):
        self._settings = None
        self.values = dict(self.DEFAULTS)

    def load(self):
        if self._settings is None:
            self._settings = sublime.load_settings(SETTINGS_FILE)
            self._settings.add_on_change(
                "python_stauts_bar_show_symbol", self._on_change)
        self._on_change()

    def unload(self):
        if self._settings is not None:
            self._settings.clear_on_change("python_stauts_bar_show_symbol")

    def _on_change(self):
        s = self._settings
        v = dict(self.DEFAULTS)

        v["enabled"] = bool(s.get("enabled", True))

        fmt = s.get("format", "breadcrumb")
        v["format"] = fmt if fmt in self.FORMATS else "breadcrumb"

        separator = s.get("separator", self.DEFAULTS["separator"])
        v["separator"] = (separator if isinstance(separator, str)
                          else self.DEFAULTS["separator"])

        wrapper = s.get("wrapper", self.DEFAULTS["wrapper"])
        v["wrapper"] = (wrapper if wrapper in self.WRAPPERS
                        else self.DEFAULTS["wrapper"])

        for key in ("show_file", "show_kinds", "show_signature"):
            v[key] = bool(s.get(key, self.DEFAULTS[key]))

        v["max_depth"] = _as_int(s.get("max_depth", 0), 0, minimum=0)

        syntaxes = s.get("syntaxes", self.DEFAULTS["syntaxes"])
        if isinstance(syntaxes, str):
            syntaxes = [syntaxes]
        if isinstance(syntaxes, list):
            cleaned = [x.lower() for x in syntaxes if isinstance(x, str) and x]
            v["syntaxes"] = cleaned
        else:
            v["syntaxes"] = list(self.DEFAULTS["syntaxes"])

        v["history_size"] = _as_int(s.get("history_size", 50), 50, minimum=1)

        self.values = v
        for window in sublime.windows():
            for view in window.views():
                refresh_view(view)


def _as_int(value, fallback, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return value if value >= minimum else fallback


_settings = Settings()


class NavHistory(object):
    """跳转历史：back 栈 + forward 栈。"""

    def __init__(self):
        self.back = []
        self.forward = []

    def push(self, entry, limit):
        self.back.append(entry)
        while len(self.back) > limit:
            self.back.pop(0)
        self.forward = []

    def clear(self):
        self.back = []
        self.forward = []


_history = NavHistory()


def _tab_size(view):
    try:
        size = view.settings().get("tab_size", 4)
    except Exception:
        size = 4
    return size if isinstance(size, int) and size > 0 else 4


def _indent_width(text, tab_size):
    """前导空白的显示宽度（tab 按 tab_size 对齐）。"""
    width = 0
    for ch in text:
        if ch == " ":
            width += 1
        elif ch == "\t":
            width += tab_size - (width % tab_size)
        else:
            break
    return width


def _raw_symbols(view):
    """取 (point, name) 列表；优先使用 ST4 的 ``symbol_regions``。"""
    getter = getattr(view, "symbol_regions", None)
    if getter is not None:
        try:
            return [(item.region.a, item.name) for item in getter()]
        except Exception:
            pass
    try:
        return [(region.a, name) for region, name in view.get_symbols()]
    except Exception:
        return []


def _extract_signature(text):
    """提取单行 def 的参数列表，多行签名不处理。"""
    open_at = text.find("(")
    if open_at < 0:
        return ""
    close_at = text.find(")", open_at)
    if close_at < 0:
        return ""
    return text[open_at + 1:close_at].strip()


def _analyze_symbols(view):
    """把符号位置还原成 (point, name, kind, indent, signature)。"""
    tab_size = _tab_size(view)
    result = []
    for point, name in _raw_symbols(view):
        try:
            text = view.substr(view.line(point))
        except Exception:
            continue

        class_match = RE_CLASS.match(text)
        if class_match:
            kind = "class"
            indent = _indent_width(class_match.group(1), tab_size)
            symbol_name = class_match.group(2) or name
            signature = ""
        else:
            def_match = RE_DEF.match(text)
            if not def_match:
                # 语法包认出来的符号，但源码行对不上（装饰器、单行语句等）
                result.append((point, name, "", _indent_width(text, tab_size), ""))
                continue
            kind = "async def" if def_match.group(2) else "def"
            indent = _indent_width(def_match.group(1), tab_size)
            symbol_name = def_match.group(3) or name
            signature = _extract_signature(text)

        result.append((point, symbol_name, kind, indent, signature))

    result.sort(key=lambda item: item[0])
    return result


def _cache_key(view):
    """符号表缓存键。

    只用 change_count 不够：缓冲区**加载完成**不会改变 change_count，
    on_load 时缓存下的空符号表会一直命中，嵌套层级永远出不来。
    所以还要带上 size（内容长度）和 syntax（语法可能被重新指定）。
    """
    try:
        return (view.change_count(), view.size(), view.settings().get("syntax"))
    except Exception:
        return None


def _symbols(view):
    """带缓存的符号表，缓冲区没变就不重新解析。"""
    try:
        vid = view.id()
    except Exception:
        return []
    key = _cache_key(view)
    if key is None:
        return []
    cached = _SYMBOL_CACHE.get(vid)
    if cached is not None and cached[0] == key:
        return cached[1]
    symbols = _analyze_symbols(view)
    _SYMBOL_CACHE[vid] = (key, symbols)
    return symbols


def _next_code_indent(view, start, tab_size):
    """从 start 之后找第一个有效代码行，返回其缩进宽度。"""
    try:
        size = view.size()
    except Exception:
        return None
    point = start
    while point < size:
        try:
            line = view.line(point)
            text = view.substr(line)
        except Exception:
            return None
        stripped = text.strip()
        if stripped and not stripped.startswith("#"):
            return _indent_width(text, tab_size)
        nxt = line.end() + 1
        if nxt <= point:
            return None
        point = nxt
    return None


def _scope_chain(view, symbols, point):
    """推导光标所处的符号链，由外到内排列。"""
    tab_size = _tab_size(view)
    try:
        line = view.line(point)
        text = view.substr(line)
    except Exception:
        return []

    stripped = text.strip()
    indent = _indent_width(text, tab_size)
    if not stripped or stripped.startswith("#"):
        # 空行 / 注释行：作用域跟随后面的代码行
        following = _next_code_indent(view, line.end() + 1, tab_size)
        if following is not None:
            indent = following

    chain = []
    limit = indent
    for symbol in reversed(symbols):
        if symbol[0] > point:
            continue
        if symbol[3] < limit:
            chain.append(symbol)
            limit = symbol[3]
            if limit <= 0:
                break
    chain.reverse()
    return chain


def _display_path(view):
    """文件名（相对项目根目录，解析不出来时退化为文件名）。"""
    name = view.file_name()
    if not name:
        return ""
    window = view.window()
    if window is not None:
        try:
            folders = (window.project_data() or {}).get("folders") or []
        except Exception:
            folders = []
        for folder in folders:
            root = folder.get("path")
            if not root:
                continue
            try:
                relative = os.path.relpath(name, root)
            except Exception:
                continue
            if not relative.startswith(".."):
                return relative.replace("\\", "/")
    return os.path.basename(name)


def _current_chain(view):
    """光标当前所处的符号链。"""
    sel = view.sel()
    if not sel:
        return []
    return _scope_chain(view, _symbols(view), sel[0].b)


def _status_text(view, settings, chain=None):
    """生成状态栏文本；空字符串表示不显示。"""
    if chain is None:
        chain = _current_chain(view)

    depth = settings["max_depth"]
    if depth > 0 and len(chain) > depth:
        chain = chain[-depth:]

    fmt = settings["format"]
    separator = settings["separator"]
    joiner = " " + separator + " "

    if fmt in ("dotted", "plain"):
        parts = [symbol[1] for symbol in chain]
        body = ".".join(parts) if fmt == "dotted" else " ".join(parts)
    else:
        parts = []
        for symbol in chain:
            name = symbol[1]
            if settings["show_kinds"] and symbol[2]:
                name = symbol[2] + " " + name
            if settings["show_signature"] and symbol[4]:
                name = name + "(" + symbol[4] + ")"
            parts.append(name)
        body = joiner.join(parts)

    file_part = _display_path(view) if settings["show_file"] else ""
    if body and file_part:
        text = file_part + joiner + body
    else:
        text = body or file_part
    if not text:
        return ""

    # 外面套一层框，和编码、语法等原生状态项区分开
    prefix, suffix = Settings.WRAPPERS.get(settings["wrapper"], ("", ""))
    return prefix + text + suffix


def _is_enabled_for_view(view, settings):
    """只对配置里指定的语法（默认 Python）生效。"""
    try:
        syntax = view.settings().get("syntax")
    except Exception:
        syntax = None
    if syntax:
        low = syntax.lower()
        for token in settings["syntaxes"]:
            if token and token in low:
                return True
    name = view.file_name() or ""
    return name.lower().endswith(PY_EXTENSIONS)


def refresh_view(view):
    """刷新某个 view 的状态栏符号项，返回当前作用域链。"""
    if view is None:
        return []
    chain = []
    try:
        settings = _settings.values
        if not settings["enabled"] or not _is_enabled_for_view(view, settings):
            view.erase_status(STATUS_KEY)
            return chain
        chain = _current_chain(view)
        text = _status_text(view, settings, chain)
    except Exception:
        text = ""
    try:
        if text:
            view.set_status(STATUS_KEY, text)
        else:
            view.erase_status(STATUS_KEY)
    except Exception:
        pass
    return chain


def _schedule_refresh(view, delay=250):
    """延迟刷新；文件还在加载时自动续约，直到内容就绪。"""
    try:
        vid = view.id()
    except Exception:
        return
    if vid in _REFRESH_PENDING:
        return
    _REFRESH_PENDING.add(vid)

    def run():
        _REFRESH_PENDING.discard(vid)
        try:
            if view.window() is None:
                return
            refresh_view(view)
            if view.is_loading():
                _schedule_refresh(view, 200)
        except Exception:
            pass

    sublime.set_timeout(run, delay)


def _record_context(view, chain=None):
    """作用域发生跳变时，把离开的位置记入跳转历史。"""
    if _suppressing():
        return
    try:
        vid = view.id()
        sel = view.sel()
        if not sel:
            return
        point = sel[0].b
        if chain is None:
            chain = _current_chain(view)
        key = tuple(symbol[1] for symbol in chain)
        previous = _LAST_CONTEXT.get(vid)
        _LAST_CONTEXT[vid] = (point, key)
        if previous is None:
            return
        prev_point, prev_key = previous
        if prev_key == key or prev_point == point:
            return
        row, col = view.rowcol(prev_point)
        _history.push((view.file_name(), row, col, vid),
                      _settings.values["history_size"])
    except Exception:
        pass


class PythonStautsBarShowSymbolListener(sublime_plugin.EventListener):
    """事件监听：负责刷新状态栏与记录跳转历史。"""

    def on_load(self, view):
        # 刚 load 完时缓冲区可能还没填满，符号表要等内容就绪后才准
        refresh_view(view)
        _schedule_refresh(view, 200)

    def on_activated_async(self, view):
        refresh_view(view)

    def on_selection_modified_async(self, view):
        chain = refresh_view(view)
        _record_context(view, chain)

    def on_modified_async(self, view):
        _schedule_refresh(view)

    def on_close(self, view):
        try:
            vid = view.id()
        except Exception:
            return
        _SYMBOL_CACHE.pop(vid, None)
        _LAST_CONTEXT.pop(vid, None)
        _REFRESH_PENDING.discard(vid)


def _encoded_path(path, row, col):
    """open_file 认得的 :row:col 后缀（配合 sublime.ENCODED_POSITION）。"""
    return "%s:%d:%d" % (path, row + 1, col + 1)


def _place_cursor(view, row, col):
    """把光标落到指定位置；文件还没加载完就稍后重试。

    程序化写 ``view.sel()`` 不会派发 ``on_selection_modified``（走命令管线的
    ``move`` 才会），所以状态栏刷新和当前位置记录都得在这里自己补。
    """
    if view is None:
        _release_suppress()
        return

    def place():
        # 返回 True 表示这条重试链可以结束（定位成功或放弃）
        if view.window() is None:
            return True
        try:
            if view.is_loading():
                return False
            point = view.text_point(row, col)
            sel = view.sel()
            sel.clear()
            sel.add(sublime.Region(point, point))
            view.show_at_center(point)
            # 补刷状态栏：这条路径没有事件可等
            chain = refresh_view(view)
            # 同步“当前位置”，否则下次真实移动会把跳转前的位置再记一遍历史
            _LAST_CONTEXT[view.id()] = (point, tuple(s[1] for s in chain))
            _release_suppress()
            return True
        except Exception:
            return True

    def attempt(retries):
        if place():
            return
        if retries <= 0:
            _release_suppress()
            return
        sublime.set_timeout(lambda: attempt(retries - 1), 60)

    attempt(PLACE_RETRIES)


def _goto_entry(window, entry):
    """跳到历史记录里的位置。"""
    global _suppress_until

    path, row, col, vid = entry
    target = None
    if path:
        target = window.open_file(_encoded_path(path, row, col),
                                  sublime.ENCODED_POSITION)
    else:
        # 未保存的文件没有路径，只能按 view id 找回来
        for view in window.views():
            if view.id() == vid:
                target = view
                window.focus_view(view)
                break

    _suppress_until = time.time() + SUPPRESS_TIMEOUT
    _place_cursor(target, row, col)


def _suppressing():
    return _suppress_until > 0 and time.time() < _suppress_until


def _release_suppress():
    global _suppress_until
    _suppress_until = 0.0


def _navigate(window, direction):
    if direction == "back":
        if not _history.back:
            sublime.status_message("没有可回退的位置")
            return
        entry = _history.back.pop()
        _history.forward.append(entry)
    else:
        if not _history.forward:
            sublime.status_message("没有可前进的位置")
            return
        entry = _history.forward.pop()
        _history.back.append(entry)
    _goto_entry(window, entry)


class NavBackCommand(sublime_plugin.WindowCommand):
    """回退到上一个位置。"""

    def run(self):
        _navigate(self.window, "back")


class NavForwardCommand(sublime_plugin.WindowCommand):
    """前进到下一个位置。"""

    def run(self):
        _navigate(self.window, "forward")


class NavPosCommand(sublime_plugin.WindowCommand):
    """兼容旧版 nav_pos 命令（otype = prev / next）。"""

    def run(self, otype="prev"):
        _navigate(self.window, "back" if otype == "prev" else "forward")


class PythonSymbolMarkCommand(sublime_plugin.WindowCommand):
    """把当前位置标记为跳转点。"""

    def run(self):
        view = self.window.active_view()
        if view is None:
            return
        sel = view.sel()
        point = sel[0].b if sel else 0
        row, col = view.rowcol(point)
        _history.push((view.file_name(), row, col, view.id()),
                      _settings.values["history_size"])
        sublime.status_message("已标记跳转点")


class PythonSymbolCopyCommand(sublime_plugin.WindowCommand):
    """复制当前作用域路径到剪贴板。"""

    def run(self):
        view = self.window.active_view()
        if view is None:
            return
        text = _status_text(view, _settings.values)
        if not text:
            sublime.status_message("当前没有可复制的符号路径")
            return
        sublime.set_clipboard(text)
        sublime.status_message("已复制符号路径：" + text)


class PythonSymbolRefreshCommand(sublime_plugin.WindowCommand):
    """手动刷新状态栏符号显示。"""

    def run(self):
        view = self.window.active_view()
        if view is None:
            return
        refresh_view(view)


class PythonSymbolToggleCommand(sublime_plugin.WindowCommand):
    """开关状态栏符号显示。"""

    def run(self):
        settings = sublime.load_settings(SETTINGS_FILE)
        current = bool(settings.get("enabled", True))
        settings.set("enabled", not current)
        sublime.status_message("状态栏符号显示：" + ("开启" if not current else "关闭"))


def plugin_loaded():
    """插件加载完成后再碰 API（启动期 API 处于休眠状态）。"""
    _settings.load()


def plugin_unloaded():
    """卸载时清理状态栏残留。"""
    _settings.unload()
    for window in sublime.windows():
        for view in window.views():
            try:
                view.erase_status(STATUS_KEY)
            except Exception:
                pass
