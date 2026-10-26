PythonStautsBarShowSymbol
=========================

A persistent breadcrumb in the Sublime Text status bar that tells you which
Python class or function the cursor is currently in.

```
| class HttpClient › def request |
```

**English** · [简体中文](README_zh.md)

<br/>

## Why the pipes

Sublime appends the value of a `set_status()` key *inside* the native status
group:

```
[UTF-8 (CRLF) | class HttpClient › def request |], 3 matches
```

Without a visible boundary the scope path blends into the encoding and match
count next to it. `| … |` is the default frame; `[ … ]`, `| [ … ] |` and no frame
at all are also available.

The old version of this plugin printed `--------------------->class test-->def testFunc`
as a transient message: it replaced the whole status bar, disappeared after a
few seconds, and, since ST3, the nesting chain had silently broken — only the
innermost symbol was ever shown. This version rebuilds the display, the
algorithm and the navigation.

<br/>

## Features

* **Persistent status item.** Uses `view.set_status()` instead of
  `sublime.status_message()`, so it sits alongside the encoding and syntax items
  instead of overwriting them, and never fades away.
* **Full nesting chain.** `class`, `def` and `async def` are all recognised. The
  chain is derived from the indentation of the source lines, so blank lines and
  comment lines still resolve to the correct scope.
* **Type prefixes.** `class HttpClient › def request`, `async def fetch`.
* **Configurable frame and separator**, four frame styles.
* **Three layouts.** Breadcrumb, dotted and plain.
* **Jump history.** Records where you left when the scope changes, with
  back/forward navigation.
* **Python only.** Other languages are left alone.

<br/>

## Installation

Copy this directory into your Sublime Text `Packages` folder:

```
Data/Packages/PythonStautsBarShowSymbol/
```

No Package Control needed. Restart Sublime Text afterwards.

<br/>

## Settings

`Preferences > Settings - User > PythonStautsBarShowSymbol.sublime-settings`

| Key | Default | Description |
|---|---|---|
| `enabled` | `true` | Master switch |
| `format` | `"breadcrumb"` | `breadcrumb` / `dotted` / `plain` |
| `separator` | `"›"` | Level separator; spaces are added on both sides |
| `wrapper` | `"pipe"` | `pipe` \| … \| / `bracket` [ … ] / `angle` < … > / `both` \| [ … ] \| / `none` |
| `show_file` | `false` | Prefix the chain with the file name (project-relative) |
| `show_kinds` | `true` | Prefix each level with `class` / `def` / `async def` |
| `show_signature` | `false` | Append the parameter list to functions |
| `max_depth` | `0` | Maximum number of levels to show; `0` means unlimited |
| `syntaxes` | `["python"]` | Syntaxes the plugin applies to (matched by name, case-insensitive) |
| `history_size` | `50` | Maximum number of jump history entries |

<br/>

## Output examples

Default (no file name, with type prefixes, pipe frame):

```
| class HttpClient › def request |
```

With `show_file` enabled:

```
| utils/http.py › class HttpClient › def request |
```

Layouts:

| `format` | Output |
|---|---|
| `breadcrumb` (default) | `\| class HttpClient › def request \|` |
| `dotted` | `\| HttpClient.request \|` |
| `plain` | `\| class HttpClient def request \|` |

Frames:

| `wrapper` | Output |
|---|---|
| `pipe` (default) | `\| class HttpClient › def request \|` |
| `bracket` | `[class HttpClient › def request]` |
| `angle` | `<class HttpClient › def request>` |
| `both` | `\| [class HttpClient › def request] \|` |
| `none` | `class HttpClient › def request` |

Bracket-style frames (`bracket`, `angle`) sit tight against the content;
separator-style frames (`pipe`, `both`) keep a space inside.

When the cursor is at module level there is no enclosing symbol, so the status
item is removed entirely (nothing to show).

<br/>

## Commands

All commands are available from the Command Palette.

| Command | Key binding | Description |
|---|---|---|
| `nav_back` | `Ctrl+Alt+U` | Jump back to the previous scope position |
| `nav_forward` | `Ctrl+Alt+I` | Jump forward to the next scope position |
| `python_symbol_mark` | — | Record the current position as a jump point |
| `python_symbol_copy` | — | Copy the current breadcrumb to the clipboard |
| `python_symbol_refresh` | — | Force a refresh (useful right after changing settings) |
| `python_symbol_toggle` | — | Toggle the status item on or off |

A context menu entry (`Python Symbol Path`) offers the same actions.

<br/>

## How it works

* **Positions come from the API, kind and indentation from the source line.**
  `view.get_symbols()` returns the *symbol name* (`"testFunc"`), not the source
  line. Computing indentation from it always yields 0, which is why the nesting
  chain silently broke after ST3. This version uses the symbol API only for
  positions (`symbol_regions()`, falling back to `get_symbols()`) and reads the
  kind and indentation from the symbol's own source line.
* **The symbol table is cached** under `(change_count, size, syntax)`.
  `change_count` alone is not enough: finishing a file load does not bump it, so
  an empty symbol table cached on `on_load` would never be invalidated.
  (Sublime also does not fire `on_selection_modified` for programmatic selection
  changes, so refreshes are also scheduled after load.)
* **Navigation uses the official API.** `open_file(path + ":row:col",
  sublime.ENCODED_POSITION)` opens and positions in one call, with no need to
  hook `on_load` callbacks.
* **The package ships a `.python-version` file**, so the plugin runs on the
  modern Python host (3.14 on current builds) while the code itself stays
  compatible with Python 3.3 syntax.

<br/>

## Compatibility

Sublime Text 3 and 4. Developed and verified on Sublime Text build 4215 (Windows).

<br/>

## Support

<https://scriptkitz.github.io/PythonStautsBarShowSymbol/donate.html>
