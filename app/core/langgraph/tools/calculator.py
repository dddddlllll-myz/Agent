"""LangGraph 计算器工具.
 
提供一个安全的数学表达式求值工具：不使用 eval，而是用 ast 解析 + 白名单，
只允许四则运算、幂、取模、整除、一元正负号以及少量常用数学函数，
从根本上杜绝代码注入（如 __import__、os.system 等）。
"""
 
import ast
import math
import operator
from typing import Any
 
from langchain_core.tools import tool
 
# 允许的二元运算符
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
 
# 允许的一元运算符
_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
 
# 白名单：常用数学函数与常量
_ALLOWED_NAMES: dict[str, Any] = {
    "pi": math.pi,
    "e": math.e,
    "sqrt": math.sqrt,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "pow": math.pow,
    "factorial": math.factorial,
}
 
 
def _eval_node(node: ast.AST) -> Any:
    """递归求值一个被白名单约束的 AST 节点."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):  # 数字字面量
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("只支持数字常量")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.Name):  # 常量名，如 pi、e
        if node.id in _ALLOWED_NAMES and not callable(_ALLOWED_NAMES[node.id]):
            return _ALLOWED_NAMES[node.id]
        raise ValueError(f"不支持的名称: {node.id}")
    if isinstance(node, ast.Call):  # 函数调用，如 sqrt(2)
        if not isinstance(node.func, ast.Name):
            raise ValueError("不支持的函数调用形式")
        fn = _ALLOWED_NAMES.get(node.func.id)
        if fn is None or not callable(fn):
            raise ValueError(f"不支持的函数: {getattr(node.func, 'id', '?')}")
        args = [_eval_node(a) for a in node.args]
        return fn(*args)
    raise ValueError("表达式中包含不支持的语法")
 
 
@tool
def calculator(expression: str) -> str:
    """计算一个数学表达式并返回结果.
 
    支持 + - * / // % ** 运算、括号、以及 sqrt/sin/cos/log/abs/round 等常用函数，
    和 pi、e 常量。例如 "2 * (3 + 4)"、"sqrt(2) + log10(1000)"。
 
    参数：
        expression: 要计算的数学表达式字符串。
 
    返回：
        str: 计算结果；表达式非法或出错时返回以 "错误：" 开头的说明。
    """
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree)
        return str(result)
    except Exception as e:  # 工具出错不应中断 Agent，返回可读的错误说明
        return f"错误：无法计算表达式 '{expression}' —— {e}"