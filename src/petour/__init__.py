"""
Example of a payload:

payload = [0x1, 0x2, 0x3]
with open('.../...', 'wb') as fp:
    fp.write(bytearray(payload))
"""

import copy
import sys
import types
import weakref


# (dot-path, symbol) : (petour-obj, contextManager)
__petours = dict()
__mapping = dict()
__globals = dict()


class NullContextManager(object):

    def parse_args(self, *args, **kargs):
        return self

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class Petour(object):

    def __init__(self, owner, func_obj, name_orig, name_backup):
        self._owner = owner
        self._func_obj = weakref.ref(func_obj)
        self.name_orig = name_orig
        self.name_backup = name_backup

    def owner(self):
        return self._owner

    def func_obj(self):
        return self._func_obj()


def get_callable(codeObj):
    return __mapping[codeObj]


def copy_func(f, name=None):
    """

    Args:
        f (types.FunctionType):
        name (str):

    Returns:
        types.FunctionType:
    """
    return types.FunctionType(
        f.func_code,
        f.func_globals,
        name or f.func_name,
        f.func_defaults,
        f.func_closure
    )


def _patch_free_func(module_obj, free_function_name):
    uniqueId = str(hash((module_obj, free_function_name)))

    name_backup = '{}__orig__'.format(free_function_name)
    callable_orig = getattr(module_obj, free_function_name, None)
    if not isinstance(callable_orig, types.FunctionType):
        return

    if hasattr(module_obj, name_backup):
        return

    callable_backup = copy_func(callable_orig)
    setattr(module_obj, name_backup, callable_backup)

    def wrapper(*args, **kwargs):
        import sys
        import inspect
        fr = inspect.currentframe()
        pt, ctx = sys.modules['petour'].get_callable(fr.f_code.co_name)
        f = pt.func_obj()
        ctx.parse_args(*args, **kwargs)
        with ctx:
            return f(*args, **kwargs)

    payload = wrapper.__code__
    code_patched = types.CodeType(
        payload.co_argcount,
        payload.co_nlocals,
        payload.co_stacksize,
        payload.co_flags,
        payload.co_code,
        payload.co_consts,
        payload.co_names,
        payload.co_varnames,
        payload.co_filename,
        uniqueId,
        payload.co_firstlineno,
        payload.co_lnotab,
        callable_orig.__code__.co_freevars,
        payload.co_cellvars
    )
    callable_orig.__code__ = code_patched

    pt = Petour(module_obj, callable_backup, free_function_name, name_backup)
    ctx = NullContextManager()
    record = [pt, ctx]

    __mapping[uniqueId] = record
    return record


def _patch_method(module_obj, class_dot_method):
    uniqueId = str(hash((module_obj, class_dot_method)))

    class_name, method_name = class_dot_method.split('.')
    name_backup = '{}__orig__'.format(method_name)
    class_obj = getattr(module_obj, class_name, None)
    method_obj = getattr(class_obj, method_name, None)
    if not isinstance(method_obj, types.UnboundMethodType):
        return

    callable_orig = method_obj.im_func

    if hasattr(class_obj, name_backup):
        return

    __ = types.FunctionType(
        copy.deepcopy(callable_orig.__code__),
        callable_orig.__globals__,
        callable_orig.__name__,
        callable_orig.__defaults__,
        callable_orig.__closure__
    )
    setattr(class_obj, name_backup, __)

    def wrapper(*args, **kwargs):
        import sys
        import inspect
        fr = inspect.currentframe()
        pt, ctx = sys.modules['petour'].get_callable(fr.f_code.co_name)
        f = pt.func_obj()
        ctx.parse_args(*args, **kwargs)
        with ctx:
            return f(*args, **kwargs)

    payload = wrapper.__code__
    code_patched = types.CodeType(
        payload.co_argcount,
        payload.co_nlocals,
        payload.co_stacksize,
        payload.co_flags,
        payload.co_code,
        payload.co_consts,
        payload.co_names,
        payload.co_varnames,
        payload.co_filename,
        uniqueId,
        payload.co_firstlineno,
        payload.co_lnotab,
        __.__code__.co_freevars,
        payload.co_cellvars
    )
    callable_orig.__code__ = code_patched

    pt = Petour(class_obj, __, method_name, name_backup)
    ctx = NullContextManager()
    record = [pt, ctx]
    __mapping[uniqueId] = record
    return record


def _get_imported_module(module_dot_path):
    if module_dot_path in ('__builtins__', '__builtin__'):
        module_dot_path = '__builtin__'
    module_obj = sys.modules.get(module_dot_path)
    return module_obj


def patch(module_dot_path, free_func_names=None, class_dot_methods=None, ctx=None):
    """
    Use this function to monkey-patch a free-function or method, adding
    a profiler hook to it.

    The free functions and methods are passed in by names,

    moduleDotPath examples:
    'corelib.publish'

    free function examples:
    ['exists', 'send_all', 'publish']

    method examples (using class.method format):
    ['Factory.create', 'Graph.addNode']

    Args:
        module_dot_path (str):
        free_func_names (list):
        class_dot_methods (list):
        ctx: (optional) a context manager; if not provided, a NullContextManager is created

    Returns:
        bool: indicating success or failure
    """

    module_obj = _get_imported_module(module_dot_path)
    if module_obj is None:
        try:
            module_obj = __import__(module_dot_path, fromlist=[''])
        except ImportError, e:
            return False
    if free_func_names:
        counter = 0
        for free_func_name in free_func_names:
            r = _patch_free_func(module_obj, free_func_name)
            if r:
                __petours[(module_dot_path, free_func_name)] = r
                if ctx is not None:
                    r[1] = ctx
                counter += 1
        return bool(counter)
    if class_dot_methods:
        counter = 0
        for class_dot_method in class_dot_methods:
            r = _patch_method(module_obj, class_dot_method)
            if r:
                __petours[(module_dot_path, class_dot_method)] = r
                if ctx is not None:
                    r[1] = ctx
                counter += 1
        return bool(counter)


def _unpatch(pt):
    """

    Args:
        pt (Petour):

    """
    owner_obj = pt.owner()
    if owner_obj is None:
        return
    func_obj = pt.func_obj()  # __
    if func_obj is None:
        return
    f = getattr(owner_obj, pt.name_orig)
    if isinstance(f, types.UnboundMethodType):
        f.im_func.__code__ = func_obj.__code__
    else:
        f.__code__ = func_obj.__code__
    delattr(owner_obj, pt.name_backup)


def unpatch_all():
    """
    Completely restores the patched free functions and methods, leaving no traces
    """
    for k in __petours:
        pt, _ = __petours[k]
        _unpatch(pt)
    __petours.clear()
    __mapping.clear()


def petours():
    return __petours


def petour(dot_path, symbol):
    return __petours.get((dot_path, symbol))


def context_manager(dot_path, symbol):
    return __petours.get((dot_path, symbol), (None, None))[1]


def set_context_manager(dot_path, symbol, ctx):
    r = __petours.get((dot_path, symbol))
    if r is not None:
        r[1] = ctx
