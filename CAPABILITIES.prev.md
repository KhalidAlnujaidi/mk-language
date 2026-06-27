# The Council Language — capability ladder (executed, not voted)

**0/11 capabilities pass** under the council's own reference interpreter (`interpreter.py`).

- ⬜ **arithmetic** — `(display (+ 2 (* 3 4)))` → `14`
- ⬜ **store-variable** — `(define x 10) (display x)` → `10`
- ⬜ **recall-variable** — `(define x 10) (display (+ x 5))` → `15`
- ⬜ **print-string** — `(display "hello")` → `hello`
- ⬜ **conditional** — `(define x 10) (display (if (< x 100) "small" "big"))` → `small`
- ⬜ **function** — `(define (square n) (* n n)) (display (square 7))` → `49`
- ⬜ **closure** — `(define (adder n) (lambda (m) (+ n m))) (define add5 (adder 5)) (display (add5 3))` → `8`
- ⬜ **recursion** — `(define (fact n) (if (< n 2) 1 (* n (fact (- n 1))))) (display (fact 5))` → `120`
- ⬜ **local-binding** — `(display (let ((a 2) (b 3)) (+ a b)))` → `5`
- ⬜ **higher-order-list** — `(define (square n) (* n n)) (display (map square (list 1 2 3)))` → `(1 4 9)`
- ⬜ **string-append** — `(display (string-append "a" "b"))` → `ab`
