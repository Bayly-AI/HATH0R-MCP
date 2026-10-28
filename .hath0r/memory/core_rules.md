# Core Hath0r Rules
1. CLI-First (CR-CLI-ENTRY-001): Always start with the CLI capabilities before improvising.
2. Memory Compounding (CR-MEMORY-COMPOUND-001): Every task must compound knowledge into .hath0r/memory/graph.json prior to announcing complete.
3. Bots not Daemons: Background tasks are bots/factories.
4. Hyper-Context: Always traverse the defined context paths (playbooks, procedures).
5. Promotion Path: local -> development -> testing -> staging -> master.
6. Automatic Task Evaluation & Scorecard Summary (CR-TASK-EVAL-001): Every task must execute and pass the 4-tier automatic task evaluation gate (hath0r evals run / hath0r evals verify, R_task >= 0.80) and always return a structured summary of the Eval Scorecard in the completion response to the user.
