"""Initial deterministic tools; no shell, browser, cloud or financial actions."""
import ast
import math
import operator
import json


def calculate(payload):
    expression = payload.get('expression') if isinstance(payload, dict) else None
    if not isinstance(expression, str) or not 1 <= len(expression) <= 200:
        raise ValueError('Provide an arithmetic expression of at most 200 characters')
    tree = ast.parse(expression, mode='eval')
    if sum(1 for _ in ast.walk(tree)) > 60:
        raise ValueError('Expression is too complex')
    operators = {ast.Add:operator.add, ast.Sub:operator.sub, ast.Mult:operator.mul, ast.Div:operator.truediv}
    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int,float):
            value = node.value
        elif isinstance(node, ast.BinOp) and type(node.op) in operators:
            value = operators[type(node.op)](visit(node.left), visit(node.right))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op,ast.USub) else 1)
        else:
            raise ValueError('Only numbers, parentheses and + - * / are supported')
        if not math.isfinite(value) or abs(value)>1e12:
            raise ValueError('Number exceeds the calculator limit')
        return value
    return {'expression':expression,'answer':visit(tree.body),'method':'deterministic calculator'}


TOOLS = {'calculate':calculate}


def run_one(queue):
    job = queue.claim()
    if job is None:
        return None
    try:
        tool = TOOLS.get(job['tool'])
        if tool is None:
            raise ValueError('Tool is not registered')
        result = tool(json.loads(job['payload']))
    except Exception as exc:
        queue.finish(job['id'],job['lease'],error=str(exc))
    else:
        queue.finish(job['id'],job['lease'],result=result)
    return job['id']
