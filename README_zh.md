PythonStatusBarShowSymbol
=========================

在 Sublime Text 状态栏**常驻**显示光标所处的 Python 类 / 函数路径（面包屑）。

```
| class HttpClient › def request |
```

[English](README.md) · **简体中文**

<br/>

## 为什么要加竖线

Sublime 会把 `set_status()` 的值塞进原生状态组的**内部**：

```
[UTF-8 (CRLF) | class HttpClient › def request |], 3 matches
```

不加边界的话，作用域路径会和旁边的编码信息、匹配数糊在一起。默认用 `| … |`，
也可以换成 `[ … ]`、`| [ … ] |`，或者干脆不加。

旧版显示的是 `--------------------->class test-->def testFunc`：一条瞬态消息，
顶掉整条状态栏、几秒后消失，而且从 ST3 起**嵌套层级其实已经失效**——只剩最内层
一个符号。这一版把显示、算法、导航全部重做了。

<br/>

## 特性

* **常驻状态项。** 用 `view.set_status()` 而不是 `sublime.status_message()`：
  与编辑器自带的编码、语法状态并列显示，互不覆盖，也不会几秒后消失。
* **完整嵌套层级。** `class`、`def`、`async def` 全部识别；层级由源码行的缩进
  实时推导，空行和注释行也能归到正确的层级。
* **类型前缀。** `class HttpClient › def request`、`async def fetch`。
* **外框与分隔符可配**，四种外框风格。
* **三种排布。** 面包屑、点号路径、空格分隔。
* **跳转历史。** 作用域发生跳变时记下你离开的位置，可前进后退。
* **只对 Python 生效**，不打扰其他语言的编辑。

<br/>

## 安装

把整个目录放进 Sublime Text 的 `Packages` 目录：

```
Data/Packages/PythonStautsBarShowSymbol/
```

无需 Package Control，放好后重启 Sublime Text 即可。

> 目录名沿用了早期的拼写（`Stauts`）。改它会连带设置文件名、用户配置覆盖
> 和已发布地址一起变，所以保留现状——安装时以实际目录名为准。

<br/>

## 配置

`Preferences > Settings - User > PythonStautsBarShowSymbol.sublime-settings`

| 键 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关 |
| `format` | `"breadcrumb"` | `breadcrumb` / `dotted` / `plain` |
| `separator` | `"›"` | 层级分隔符，两侧会自动补空格 |
| `wrapper` | `"pipe"` | `pipe` \| … \| / `bracket` [ … ] / `angle` < … > / `both` \| [ … ] \| / `none` |
| `show_file` | `false` | 是否在最外层显示文件名（相对项目根目录） |
| `show_kinds` | `true` | 是否给每层加 `class` / `def` / `async def` 前缀 |
| `show_signature` | `false` | 是否在函数名后追加参数列表 |
| `max_depth` | `0` | 最多显示几层，`0` 表示不限 |
| `syntaxes` | `["python"]` | 生效的语法（按语法名关键字匹配，大小写不敏感） |
| `history_size` | `50` | 跳转历史条数上限 |

<br/>

## 效果示例

默认（不显示文件名、带类型前缀、竖线外框）：

```
| class HttpClient › def request |
```

打开 `show_file` 之后：

```
| utils/http.py › class HttpClient › def request |
```

三种排布：

| `format` | 效果 |
|---|---|
| `breadcrumb`（默认） | `\| class HttpClient › def request \|` |
| `dotted` | `\| HttpClient.request \|` |
| `plain` | `\| class HttpClient def request \|` |

四种外框：

| `wrapper` | 效果 |
|---|---|
| `pipe`（默认） | `\| class HttpClient › def request \|` |
| `bracket` | `[class HttpClient › def request]` |
| `angle` | `<class HttpClient › def request>` |
| `both` | `\| [class HttpClient › def request] \|` |
| `none` | `class HttpClient › def request` |

括号类（`bracket`、`angle`）贴紧内容，分隔类（`pipe`、`both`）内侧留空格。

光标停在模块顶层（不属于任何 class / def）时没有可显示的内容，状态项会整项移除。

<br/>

## 命令

所有命令都可以在命令面板（`Ctrl+Shift+P`）里找到。

| 命令 | 默认快捷键 | 说明 |
|---|---|---|
| `nav_back` | `Ctrl+Alt+U` | 回退到上一个作用域位置 |
| `nav_forward` | `Ctrl+Alt+I` | 前进到下一个作用域位置 |
| `python_symbol_mark` | — | 把当前位置标记为跳转点 |
| `python_symbol_copy` | — | 复制当前面包屑到剪贴板 |
| `python_symbol_refresh` | — | 手动刷新（改完设置想立刻看到效果时用） |
| `python_symbol_toggle` | — | 开关状态项 |

右键菜单里也有对应入口（「Python 符号路径」）。

<br/>

## 实现说明

* **位置取自 API，类型与缩进取自源码行。**
  `view.get_symbols()` 返回的是**符号名**（`"testFunc"`），不是源码行；拿它算
  缩进永远得到 0，这就是嵌套层级在 ST3 之后悄悄失效的原因。本版只用符号 API
  取位置（`symbol_regions()`，失败时回退 `get_symbols()`），kind 和缩进都回到
  符号所在的源码行现算。
* **符号表按 `(change_count, size, syntax)` 缓存。**
  只看 `change_count` 不够：**文件加载完成不会改变它**，`on_load` 时缓存下的空
  符号表会一直命中。  （另外 Sublime 对**程序化**的选区改动不触发
  `on_selection_modified`，所以加载完成会补一次延迟刷新，跳转定位后由
  `_place_cursor` 自己再刷一次并同步当前上下文。）
* **跳转走官方接口。**
  `open_file(path + ":row:col", sublime.ENCODED_POSITION)` 一步打开并定位，
  不需要自己挂 `on_load` 回调。
* **包内带 `.python-version`。** 声明走现代 Python 宿主（当前 build 是 3.14），
  代码本身保持 Python 3.3 语法兼容。

<br/>

## 兼容性

Sublime Text 3 / 4。开发与验证环境：Sublime Text build 4215（Windows）。

<br/>

## 捐助

<https://scriptkitz.github.io/PythonStautsBarShowSymbol/donate.html>
