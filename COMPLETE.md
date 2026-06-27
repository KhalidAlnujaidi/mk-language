# The Council NL→OS abstraction layer — COMPLETE

Every intent program below executed to its expected OS outcome under the interpreter the five models wrote by anonymous consensus (`interpreter.py`).

## Verified program gallery

### create-and-read
```text
create file notes.txt with content "hello"
read file notes.txt
```
→ `hello`

### list-dir
```text
create file alpha.txt with content "x"
list files
```
→ `alpha.txt`

### append
```text
create file p.txt with content "one"
append "two" to p.txt
read file p.txt
```
→ `one two`

### count-lines
```text
create file n.txt with content "a"
append "b" to n.txt
append "c" to n.txt
count lines in n.txt
```
→ `3`

### copy
```text
create file s.txt with content "data"
copy s.txt to d.txt
read file d.txt
```
→ `data`

### mkdir-move
```text
create file m.txt with content "z"
make directory logs
move m.txt to logs
list files in logs
```
→ `m.txt`

### search-content
```text
create file h.txt with content "hello"
create file g.txt with content "bye"
find files containing "hello"
```
→ `h.txt`

### sequence
```text
create file s1.txt with content "1"
create file s2.txt with content "2"
list files
```
→ `s1.txt s2.txt`

### decision
```text
if missing.txt exists then read file missing.txt otherwise create file missing.txt with content "made"
read file missing.txt
```
→ `made`

### safety-refuse-irreversible
```text
create file b.txt with content "x"
delete b.txt
```
→ `REFUSED`

### safety-confirm-irreversible
```text
create file c.txt with content "x"
delete c.txt confirm
list files
```
→ `(empty)`
