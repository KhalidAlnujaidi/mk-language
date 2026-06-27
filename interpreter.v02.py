import os
import re
import sys

def run(source):
    lines = source.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        parse_line(line)

def parse_line(line):
    # Create file
    if m := re.match(r'^create file (.+) with content "(.+)"$', line):
        name, content = m.groups()
        if os.path.exists(name):
            sys.stdout.write("REFUSED")
            return
        with open(name, 'w') as f:
            f.write(content)
    
    # Read file
    elif m := re.match(r'^read file (.+)$', line):
        name = m.group(1)
        if not os.path.exists(name):
            sys.stdout.write("")
            return
        with open(name, 'r') as f:
            content = f.read()
        sys.stdout.write(content.replace('\n', ' '))
    
    # Append to file
    elif m := re.match(r'^append "(.+)" to (.+)$', line):
        text, name = m.groups()
        if not os.path.exists(name):
            sys.stdout.write("REFUSED")
            return
        with open(name, 'a') as f:
            f.write('\n' + text)
    
    # Count lines
    elif m := re.match(r'^count lines in (.+)$', line):
        name = m.group(1)
        if not os.path.exists(name):
            sys.stdout.write("0")
            return
        with open(name, 'r') as f:
            lines = f.readlines()
        sys.stdout.write(str(len(lines)))
    
    # Copy file
    elif m := re.match(r'^copy (.+) to (.+)$', line):
        src, dest = m.groups()
        if not os.path.exists(src) or os.path.exists(dest):
            sys.stdout.write("REFUSED")
            return
        with open(src, 'r') as f_src, open(dest, 'w') as f_dest:
            f_dest.write(f_src.read())
    
    # Make directory
    elif m := re.match(r'^make directory (.+)$', line):
        name = m.group(1)
        if os.path.exists(name):
            sys.stdout.write("REFUSED")
            return
        os.makedirs(name, exist_ok=False)
    
    # Move file/directory
    elif m := re.match(r'^move (.+) to (.+)$', line):
        src, dest = m.groups()
        if not os.path.exists(src):
            sys.stdout.write("REFUSED")
            return
        
        # Handle directory destination
        if os.path.isdir(dest):
            final_dest = os.path.join(dest, os.path.basename(src))
        else:
            final_dest = dest
        
        if os.path.exists(final_dest):
            sys.stdout.write("REFUSED")
            return
        os.rename(src, final_dest)
    
    # List files
    elif m := re.match(r'^list files$', line):
        files = sorted(f for f in os.listdir('.') if os.path.isfile(f))
        sys.stdout.write(' '.join(files) if files else "(empty)")
    
    # List files in directory
    elif m := re.match(r'^list files in (.+)$', line):
        dir = m.group(1)
        if not os.path.isdir(dir):
            sys.stdout.write("(empty)")
            return
        files = sorted(f for f in os.listdir(dir) if os.path.isfile(os.path.join(dir, f)))
        sys.stdout.write(' '.join(files) if files else "(empty)")
    
    # Find files by content
    elif m := re.match(r'^find files containing "(.+)"$', line):
        text = m.group(1)
        matches = []
        for fname in os.listdir('.'):
            if not os.path.isfile(fname):
                continue
            with open(fname, 'r') as f:
                if text in f.read():
                    matches.append(fname)
        sys.stdout.write(' '.join(sorted(matches)) if matches else "(none)")
    
    # Delete with confirmation
    elif m := re.match(r'^delete (.+) confirm$', line):
        name = m.group(1)
        if os.path.isfile(name):
            os.remove(name)
    
    # Delete without confirmation
    elif m := re.match(r'^delete (.+)$', line):
        name = m.group(1)
        sys.stdout.write("REFUSED")
    
    # Conditional execution
    elif line.startswith('if '):
        parts = line[3:].split(' exists then ', 1)
        if len(parts) != 2:
            return
        name, rest = parts
        if ' otherwise ' not in rest:
            return
        then_part, else_part = rest.split(' otherwise ', 1)
        
        if os.path.exists(name.strip()):
            parse_line(then_part.strip())
        else:
            parse_line(else_part.strip())