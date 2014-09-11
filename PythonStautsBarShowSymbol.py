#-*- coding:utf-8 -*-
import sublime, sublime_plugin
import re
import functools
import os

posHistory = []        #
prevHistory = []
lastLine = None        #
_selList = []
ON_LOAD = sublime_plugin.all_callbacks['on_load']



def select(view, region):
    sel_set = view.sel()
    sel_set.clear()
    sel_set.add(region)
    sublime.set_timeout(functools.partial(view.show_at_center, region), 1)
def on_load(path=None, window=None, encoded_row_col=True, begin_edit=False):
    """Decorator to open or switch to a file.

    Opens and calls the "decorated function" for the file specified by path,
    or the current file if no path is specified. In the case of the former, if
    the file is open in another tab that tab will gain focus, otherwise the
    file will be opened in a new tab with a requisite delay to allow the file
    to open. In the latter case, the "decorated function" will be called on
    the currently open file.

    :param path: path to a file
    :param window: the window to open the file in
    :param encoded_row_col: the ``sublime.ENCODED_POSITION`` flag for
        ``sublime.Window.open_file``
    :param begin_edit: if editing the file being opened

    :returns: None
    """
    window = window or sublime.active_window()
    def wrapper(f):
        # if no path, tag is in current open file, return that
        if not path:
            return f(window.active_view())
        # else, open the relevant file
        view = window.open_file(os.path.normpath(path), encoded_row_col)
        def wrapped():
            f(view)
            # if editing the open file
            # if begin_edit:
            #     with Edit(view):
            #         f(view)
            # else:
            #     f(view)
        # if buffer is still loading, wait for it to complete then proceed
        if view.is_loading():
            class set_on_load():
                callbacks = ON_LOAD
                def __init__(self):
                    # append self to callbacks
                    self.callbacks.append(self)
                def remove(self):
                    # remove self from callbacks, hence disconnecting it
                    self.callbacks.remove(self)
                def on_load(self, view):
                    # on file loading
                    try:
                        wrapped()
                    finally:
                        # disconnect callback
                        self.remove()
            set_on_load()
        # else just proceed (file was likely open already in another tab)
        else:
            wrapped()
    return wrapper

class navPos(sublime_plugin.TextCommand):
    def run(self, edit,otype):
        global posHistory,prevHistory
        if otype == "prev":
            if len(posHistory)<=1:return
            prevHistory.append(posHistory.pop())
        elif otype == "next":
            if len(prevHistory)==0:return
            posHistory.append(prevHistory.pop())
        file_name,sel = posHistory[-1]
        view = self.view.window().open_file(file_name)
        self.jump(file_name, sel)
    def jump(self, fn, sel):
        @on_load(fn, begin_edit=True)
        def and_then(view):
            select(view, sel)
class BackgroundShowPythonIndentName(sublime_plugin.EventListener):
    """ Process Sublime Text events """
    def on_selection_modified(self, view):
        global posHistory, lastLine,prevHistory
        syntax = view.settings().get('syntax')
        if syntax.lower().find('python') == -1: #
            return
        s = view.sel()
        if s[0].a != s[0].b :return    #  
        cursorX = s[0].b
        cline = view.line(cursorX)
        if lastLine and (cline.a==lastLine.a or cline.b == lastLine.b): #
            return
        lastLine = cline
        fn = view.file_name()
        if s[0] not in _selList:
            prevHistory = []
            if len(posHistory)>20:
                posHistory.pop(0)
                _selList.pop(0)
            posHistory.append((fn,s[0]))
            _selList.append(s[0])
        symList = []
        symbols = view.get_symbols()
        lastIndex = len(symbols)-1
        for i, symbol in enumerate(symbols):
            rng, line = symbol
            if rng.a > cursorX:
                lastIndex = i-1
                break
        indent = -1
        for i in range(lastIndex,-1,-1):
            rng, line = symbols[i]
            if indent == -1:
                indent = self._getIndent(line)
            else:
                c = self._getIndent(line)
                if indent <= c:
                    continue
                indent = c
            symList.append(line)
            if indent == 0:
                break
        symList.reverse()
        rs = None
        if(sublime.version()[0]=='3'):
            rs = re.compile(r'\s*(\w*)')
        else:
            rs = re.compile(r'\s*(def|class)\s+(\w*)')
        strs = ["---------------------"]
        for s in symList:
            m = rs.match(s)
            if m:
                strs.append(m.group(0).strip())
        if len(strs)>1:
            sublime.status_message('->'.join(strs))
    def _getIndent(self,line):
        c = 0
        for s in line:
            if s in (" ","\t"):
                c+=1
            else:
                break
        return c
