# The Council Language — living specification

_Designed by anonymous Borda consensus of five distinct-architecture models:_
_anthropic/claude-sonnet-4, openai/gpt-4o, deepseek/deepseek-r1, qwen/qwen-2.5-72b-instruct, mistralai/mistral-large._

## Governing axioms
```
1. MACHINE-INTERPRETABILITY FIRST. Prefer forms a machine parses and reasons about
   unambiguously over forms that merely read nicely to humans.
2. REUSE, DON'T REINVENT. Adopt the simplest construct that already works; do not
   add a second way to do the same thing.
3. DON'T BREAK WHAT WORKS. A change is adopted only if it is strictly better than
   the status quo under these axioms; when in doubt, keep what stands.
4. EVERYTHING IS TESTABLE. Every construct must have a clear, checkable meaning —
   a program's behavior must be decidable from its text.
5. MINIMAL CORE. Fewer primitives, composed; not many features, special-cased.
```

## meta-axiom
_adopted from qwen3:8b · consensus margin 9_

**PROPOSED NEW META-AXIOM:**  
**ALL FEATURES MUST BE PRIMITIVE OR COMPOSED FROM CORE PRIMITIVES, WITH SYNTACTIC SUGAR THAT ADDS NO SEMANTIC COMPLEXITY AND IS MECHANICALLY REDUCIBLE TO CORE MECHANISMS VIA A WELL-DEFINED TRANSFORMATION.**  

This version strengthens the requirement by explicitly demanding that syntactic sugar is *mechanically reducible* to core primitives via a defined transformation, ensuring no hidden rules or ambiguity. It aligns with Axiom 1 (machine-interpretable) by enforcing explicit reduction rules, Axiom 2 (reuse) by mandating composition, and Axiom 4 (testability) by requiring deterministic core-based evaluation. The phrasing avoids reliance on vague terms like "testable via core mechanisms," instead framing it as a formal transformation, which better aligns with the axioms' emphasis on unambiguous, decidable behavior.

## design-goals
_adopted from deepseek-r1:8b · consensus margin 9_

1. **MACHINE-INTERPRETABILITY:** All constructs are defined via explicit, unambiguous reduction rules executable by a machine, prioritizing formal semantics over human readability.  
2. **DERIVABLE FROM CORE PRIMITIVES:** Every feature emerges from closures, environments, and list evaluation, ensuring no redundant primitives exist.  
3. **STABILITY THROUGH STRICT IMPROVEMENT:** Modifications are adopted only if they strictly enhance operational semantics without breaking existing behavior, preserving determinism.  
4. **DECIDABILITY & AUDITABILITY:** All constructs are deterministic, with behaviors fully decidable via finite reduction steps, ensuring transparency and debuggability.  
5. **MINIMAL CORE & COMPOSITIONALITY:** The language’s primitives are the absolute minimum required for computation, with complexity arising solely from their structured composition.  

Rationale: These goals strictly enforce the axioms by emphasizing machine-executable rules, derivability, stability, decidable semantics, and minimality, with no need for refinement.

## notation
_adopted from gemma4:latest · consensus margin 7_

Prefix notation (S-expressions) is optimal and should be maintained.

It is the only notation that maps syntactic structure directly and unambiguously onto the fundamental computational model of function application: $\text{Call}(O, A_1, A_2, \ldots)$, where $O$ is the operator and $A_i$ are the arguments.

1.  **Machine Interpretability:** Prefix notation mandates a simple recursive descent parser that only needs to consume tokens and recursively evaluate arguments, directly satisfying (A1). It avoids the complex state tracking (operator stack, precedence tables) required by Postfix or the multi-pass parsing required by Infix.
2.  **Minimal Core:** The syntax requires only one grouping primitive (parentheses) and the ability to delimit atomic tokens. Any attempt to introduce alternative notations adds non-essential complexity.
3.  **Functional Alignment:** It perfectly models functional application, which is the core mechanism implied by the inclusion of `lambda` and the overall design.

No alternative notation is strictly better because the structural simplicity and direct mapping to function application provided by S-expressions provide the maximal syntactic sugar for adherence to the **Machine-Interpretability First** axiom.

## lexical-grammar
_adopted from gemma4:latest · consensus margin 11_

Tokens:
- **Parentheses**: `(` and `)`
- **Keyword (Boolean)**: `true` or `false`
- **Identifier**: `[a-zA-Z_][a-zA-Z0-9_]*` (This pattern must be checked *after* keywords to handle reserved words)
- **Literal**:
  - Number: `[0-9]+`
  - String: `"[^"]*"` (Literal content matching this pattern)
- **Comment**: `;[^\\n]*` (Non-greedy match until newline, or end of file)

Whitespace is ignored. Lexing order: (1) Comment $\rightarrow$ (2) String $\rightarrow$ (3) Keyword/Boolean $\rightarrow$ (4) Number $\rightarrow$ (5) Parentheses $\rightarrow$ (6) Identifier.

*Rationale for Strict Improvement:* The current definition is optimal for machine interpretability, but the sequence of matching must explicitly prioritize reserved keywords (`true`, `false`) over the general `Identifier` pattern to guarantee correct tokenization. The comment regex is tightened to explicitly exclude line terminators from the match, ensuring predictable parsing state upon hitting a newline. This structural clarification improves testability without adding complexity.

## core-grammar
_adopted from deepseek-r1:8b · consensus margin 8_

Based on the provided design goals, the core grammar for the language is defined using Extended Backus-Naur Form (EBNF) to ensure it is simple, recursive, and adheres to the principles of minimal core and machine-interpretability. The grammar consists of four non-terminal symbols and is structured to parse expressions and lists recursively. Here's the EBNF grammar:

**EBNF Grammar:**

```
<program> = <expression>* ;
<expression> = <atom> | <list> ;
<atom> = <identifier> | <number> | <string> | <boolean> ;
<list> = '(' <expression>* ')' ;
<identifier> = [a-zA-Z_][a-zA-Z0-9_]* ;
<number> = [0-9]+ ;
<string> = '"' [^"]* '"' ;
<boolean> = 'true' | 'false' ;
```

### Explanation of the Grammar:
1. **`<program>`**: Represents the entire program, which is a sequence of one or more `<expression>`s. This allows the program to consist of multiple statements or expressions.
2. **`<expression>`**: The core of the language, which can be either an `<atom>` or a `<list>`. This ensures that both simple and complex expressions can be evaluated.
3. **`<atom>`**: Represents a basic value in the language, such as a number, string, boolean, or identifier (for variables or functions). This includes:
   - **`<identifier>`**: A sequence of letters, digits, and underscores (e.g., `x`, `myVar`).
   - **`<number>`**: A sequence of digits (e.g., `42`, `-7`).
   - **`<string>`**: A sequence of characters enclosed in double quotes (e.g., `"hello"`).
   - **`<boolean>`**: The literals `true` or `false`.
4. **`<list>`**: Represents a collection of expressions enclosed in parentheses. The grammar allows for any number of `<expression>`s, including zero (empty list). The empty list (`()`) is a valid expression.

### Key Features:
- **Recursive Structure**: The grammar allows for nested expressions (e.g., `(a (b))`), which is essential for representing complex computations.
- **Simple Parsing**: The recursive definition of `<expression>` and `<list>` ensures that the grammar can be parsed using a straightforward recursive descent parser, aligning with the goal of machine-interpretability.
- **Minimal Core**: The grammar includes only the necessary components (`<atom>` and `<list>`), adhering to the minimal core requirement. Higher-level constructs (like function definitions or loops) are not part of this core grammar, emphasizing simplicity and reusability.
- **Lexical Flexibility**: The `<identifier>` and `<string>` rules allow for flexibility in naming variables and strings, while the `<number>` and `<boolean>` rules are fixed for simplicity.

### Example Program:
Here's a simple example of a program that adheres to this grammar:

```
(5 "hello" true (x (y) 42))
```

This program consists of:
- An `<atom>` (number `5`).
- An `<atom>` (string `"hello"`).
- An `<atom>` (boolean `true`).
- A `<list>` containing an `<atom>` (identifier `x`), an empty list (`()`), and an `<atom>` (number `42`).

### Notes:
- The grammar does not include special forms for function definitions or control flow (e.g., `if`, loops), as these are outside the minimal core scope. Function definitions would require additional grammar rules and a runtime environment, but they are not part of this core design to keep the grammar simple and reusable.
- The empty list (`()`) is allowed as a valid `<list>`, which can represent nil or a placeholder in higher-level constructs. This ensures the grammar remains flexible for extensions.

This grammar provides a solid foundation for building a language that prioritizes simplicity, reusability, and machine-interpretability while adhering to the specified design goals.

## paradigm-and-types
_adopted from qwen3:8b · consensus margin 10_

**Functional programming with structural static typing**  
This decision prioritizes machine interpretability by embedding type constraints directly into data structures, eliminating the need for separate type annotations. Structural typing ensures type safety through the shape of values (e.g., lists of numbers, pairs of strings) rather than explicit keywords, aligning with minimal core and reuse.  

1. **MACHINE-INTERPRETABILITY FIRST**: Type contracts are enforced via data structure patterns (e.g., `car`/`cdr` for tuples), making the language unambiguous and parsable without runtime checks.  
2. **REUSE, DON’T REINVENT**: Leverages existing primitives (`cons`, `car`, `cdr`, `eq?`) to define type shapes, avoiding redundant constructs.  
3. **DON’T BREAK WHAT WORKS**: Retains functional purity, immutability, and the original S-expression syntax. Structural typing is a minimal, additive enhancement.  
4. **EVERYTHING IS TESTABLE**: Type correctness is decidable at parse time via structural patterns (e.g., a list’s type is inferred by its elements’ types), ensuring predictable behavior.  
5. **MINIMAL CORE**: The type system is entirely composed of primitives, with no specialized syntax. Type safety emerges from data structure composition, not separate annotations.  

This approach is optimal under the axioms. No further changes are needed.

## semantics
_adopted from gemma4:latest · consensus margin 12_

The current argument is technically insufficient regarding Axiom 1 (MACHINE-INTERPRETABILITY FIRST). While the dual role is extremely efficient (Axiom 2, Axiom 5), semantic ambiguity, even if resolved by convention (like Lisp's implicit function call), represents a failure point for *guaranteed* machine parsing and decidability (Axiom 4).

**Proposed Revision to Semantics:**

The core semantic rule governing `(E₁ E₂ … Eₙ)` must be refined to explicitly distinguish the intended role (Application vs. Construction) at the semantic layer, even if the syntax remains identical.

1.  **Data Structure Construction:** If the context dictates construction (e.g., initialization or list literal), the evaluation of $(E_1, \dots, E_n)$ results in a data structure $\text{DataList}(E_1, \dots, E_n)$. This mechanism is preserved for maximum reuse.

2.  **Function Application:** The evaluation of $(E_1, E_2, \dots, E_n)$ *must* first pass a type/semantics check on $E_1$. If $E_1$ does not evaluate to a procedure (or if the parsing context is not calling a procedure), the evaluation *must* fall through to the Data Structure Construction rule. **Crucially, when $E_1$ is a procedure, the rule must explicitly check that the sequence $(E_1, E_2, \dots, E_n)$ is parsed/interpreted as a function call *before* attempting construction.**

**Justification:**
This refinement does not introduce a new primitive or specialized syntax, thereby adhering to Axiom 5 (Minimal Core) and Axiom 2 (Reuse). However, by explicitly binding the interpretation path to the procedure nature of $E_1$, we eliminate the ambiguity that compromises Axiom 1 and Axiom 4. The machine must first confirm the intent (Procedure vs. Data). If the machine can prove the intended operation path deterministically, the semantics are perfected while retaining maximal structural compression.

The original statement was optimal only under the assumption of perfect compiler/interpreter context-awareness; this revision makes that required context-awareness explicit within the semantics themselves, making the system strictly better and more robust against misinterpretation.

## builtins
_adopted from gemma4:latest · consensus margin 7_

The current semantic rule is optimal. It successfully resolves the fundamental ambiguity of prefix notation (Application vs. Construction) using only type introspection on $E_1$, which adheres strictly to the constraints.

**Optimal Status:** The semantic rule must remain:
1.  Evaluate $E_1$.
2.  If $E_1$ evaluates to a procedure, execute the Application rule: $\text{Result} = E_1(E_2, \dots, E_n)$.
3.  Otherwise, execute the Construction rule: $\text{Result} = \text{DataList}(E_1, \dots, E_n)$.

This structure is minimal, fully testable, and machine-interpretable. Any attempt to alter the branching logic (e.g., introducing scope markers or dedicated keywords) would violate Axiom 2 (Reuse) or Axiom 5 (Minimal Core).

## example-factorial
_adopted from gemma4:latest · consensus margin 8_

```scheme
(define (factorial n)
  (if (zero? n)
      1
      (* n (factorial (- n 1)))))

(factorial 5) ; evaluates to 120
```

## example-data
_adopted from gemma4:latest · consensus margin 10_

The current implementation is already optimal. It flawlessly adheres to Axiom 1 (Machine-Interpretability) by relying exclusively on the core list evaluation rule (B.2) for all data structure construction, thereby avoiding the introduction of specialized primitives like `pair` or `make-record` that would violate the Minimal Core principle (Axiom 5).

The provided code block is finalized as is, as any structural change risks either adding a non-essential primitive (violating Axiom 5) or creating a logical ambiguity between list processing and data structure construction (violating Axiom 4).

```scheme
;; Define a Pair/Record data structure using core list primitives (Key Value).
;; Access via car/cdr (structural access), update via direct list construction (immutable).

;; Test Setup:
;; (define user-record '("user_id" 101)) evaluates via Rule B.2 (DataList)
(define user-record '("user_id" 101)) 

(display "--- Initial Record ---") (display user-record) 
newline

;; Accessors Test:
(display "Key: ") (display (car user-record)) 
newline
(display "Value: ") (display (cdr user-record)) 
newline

;; Update Test (Demonstrates Immutability/Reusability):
;; A new record is created by using the core list evaluation syntax (E₁ E₂) = DataList(E₁, E₂).
(define updated-record '("user_id" 202))
(display "Updated Record: ") (display updated-record) 
newline

;; Immutability Check:
(display "Original Record (Must be unchanged): ") (display user-record) 
newline
```

**Justification for Optimality:**
The mechanism $\text{ℰ}⟦(E_1 E_2 \dots E_n)⟧$ handling both function application and immutable data construction is the maximal reuse of primitives (Axiom 2) and maintains the purest form of machine interpretability (Axiom 1). Relying solely on this core semantic rule ensures that the language's fundamental data model is simple, non-special-cased, and fully deterministic (Axiom 4).

## example-showcase
_adopted from deepseek-r1:8b · consensus margin 6_

Proposed refactored version of "example-showcase":

```scheme
;; Example 3: Functional Mapping (Demonstrating Higher-Order Functions and Recursion)
;; Using built-in map

;; Example Transformation Functions:
(define (double x) (* x 2))
(define (str x) (string-append "Value: " (number->string x)))

;; Demonstration:
(display "--- Demonstrating Map ---")
(newline)

;; Test Case 1: Mapping 'double' over a list of numbers
(define numbers (list 1 2 3 4 5))
(display "Original Numbers: ")
(display numbers) ; (1 2 3 4 5)
(newline)

(display "Mapped (Doubled): ")
(display (map double numbers)) ; Expected output: (2 4 6 8 10)
(newline)

;; Test Case 2: Mapping a string conversion function
(define scores (list 10 20 30))
(display "Original Scores: ")
(display scores)
(newline)

(display "Mapped (Stringified): ")
(display (map str scores))
(newline)

;; Test Case 3: Mapping the identity function (for completeness)
(define sample-list (list 'a 'b 'c))
(display "Mapped (Identity): ")
(display (map identity sample-list))
(newline)
```

The proposal improves the code by adhering to Axiom 2: **Reuse, Don't Reinvent** by using the built-in `map` function and defining the `identity` function only if necessary for demonstration. By simplifying the test cases, the code is more concise and testable, aligning with Minimal Core (Axiom 5) and ensuring everything remains machine-interpretable.
