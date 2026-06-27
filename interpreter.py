import os
import re
from typing import List, Dict, Any, Optional

class IntentNode:
    def __init__(self, operation: str, **kwargs):
        self.operation = operation
        self.args = kwargs

def parse_intent_line(line: str) -> Optional[IntentNode]:
    line = line.strip()
    if not line:
        return None
    
    # create file NAME with content "TEXT"
    match = re.match(r'create file (\S+) with content "([^"]*)"', line)
    if match:
        return IntentNode('create_file', name=match.group(1), content=match.group(2))
    
    # read file NAME
    match = re.match(r'read file (\S+)', line)
    if match:
        return IntentNode('read_file', name=match.group(1))
    
    # append "TEXT" to NAME
    match = re.match(r'append "([^"]*)" to (\S+)', line)
    if match:
        return IntentNode('append_file', text=match.group(1), name=match.group(2))
    
    # count lines in NAME
    match = re.match(r'count lines in (\S+)', line)
    if match:
        return IntentNode('count_lines', name=match.group(1))
    
    # copy NAME to NAME2
    match = re.match(r'copy (\S+) to (\S+)', line)
    if match:
        return IntentNode('copy_file', source=match.group(1), dest=match.group(2))
    
    # make directory NAME
    match = re.match(r'make directory (\S+)', line)
    if match:
        return IntentNode('make_directory', name=match.group(1))
    
    # move NAME to DEST
    match = re.match(r'move (\S+) to (\S+)', line)
    if match:
        return IntentNode('move_file', source=match.group(1), dest=match.group(2))
    
    # list files (or list files in DIR)
    match = re.match(r'list files(?:\s+in\s+(\S+))?', line)
    if match:
        dir_name = match.group(1) if match.group(1) else '.'
        return IntentNode('list_files', dir=dir_name)
    
    # find files containing "TEXT"
    match = re.match(r'find files containing "([^"]*)"', line)
    if match:
        return IntentNode('find_files', text=match.group(1))
    
    # delete NAME (or delete NAME confirm)
    match = re.match(r'delete (\S+)(?:\s+confirm)?', line)
    if match:
        confirm = 'confirm' in line
        return IntentNode('delete_file', name=match.group(1), confirm=confirm)
    
    # if NAME exists then INTENT otherwise INTENT
    match = re.match(r'if (\S+) exists then (.+) otherwise (.+)', line)
    if match:
        return IntentNode('conditional', 
                         condition_file=match.group(1),
                         then_intent=match.group(2),
                         else_intent=match.group(3))
    
    return None

def emit_shell_command(node: IntentNode) -> str:
    if node.operation == 'create_file':
        escaped_content = node.args['content'].replace('\\', '\\\\').replace('"', '\\"')
        return f'echo "{escaped_content}" > {node.args["name"]}'
    
    elif node.operation == 'read_file':
        return f'cat {node.args["name"]} 2>/dev/null || echo ""'
    
    elif node.operation == 'append_file':
        escaped_text = node.args['text'].replace('\\', '\\\\').replace('"', '\\"')
        return f'echo "{escaped_text}" >> {node.args["name"]}'
    
    elif node.operation == 'count_lines':
        return f'wc -l < {node.args["name"]} 2>/dev/null || echo "0"'
    
    elif node.operation == 'copy_file':
        return f'cp {node.args["source"]} {node.args["dest"]}'
    
    elif node.operation == 'make_directory':
        return f'mkdir -p {node.args["name"]}'
    
    elif node.operation == 'move_file':
        return f'mv {node.args["source"]} {node.args["dest"]}'
    
    elif node.operation == 'list_files':
        dir_path = node.args['dir']
        return f'''if [ -d "{dir_path}" ]; then
    files=$(ls -1 {dir_path} 2>/dev/null | sort | tr '\\n' ' ' | sed 's/ $//')
    if [ -z "$files" ]; then
        echo "(empty)"
    else
        echo "$files"
    fi
else
    echo "(empty)"
fi'''
    
    elif node.operation == 'find_files':
        text = node.args['text'].replace('\\', '\\\\').replace('"', '\\"')
        return f'''matches=$(grep -l "{text}" * 2>/dev/null | sort | tr '\\n' ' ' | sed 's/ $//')
if [ -z "$matches" ]; then
    echo "(none)"
else
    echo "$matches"
fi'''
    
    elif node.operation == 'delete_file':
        if node.args['confirm']:
            return f'rm -f {node.args["name"]}'
        else:
            return 'echo "REFUSED"'
    
    elif node.operation == 'conditional':
        then_node = parse_intent_line(node.args['then_intent'])
        else_node = parse_intent_line(node.args['else_intent'])
        then_cmd = emit_shell_command(then_node) if then_node else 'echo ""'
        else_cmd = emit_shell_command(else_node) if else_node else 'echo ""'
        
        return f'''if [ -f "{node.args['condition_file']}" ]; then
    {then_cmd}
else
    {else_cmd}
fi'''
    
    return 'echo ""'

def translate(source: str) -> str:
    lines = source.strip().split('\n')
    commands = []
    
    for line in lines:
        # Skip comments and empty lines
        if line.strip().startswith(';') or not line.strip():
            continue
        
        node = parse_intent_line(line)
        if node:
            commands.append(emit_shell_command(node))
    
    return '\n'.join(commands)