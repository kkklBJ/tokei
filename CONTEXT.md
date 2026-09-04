# Domain Glossary

## Tool Usage

- **Tool**: An AI coding application whose locally persisted model activity is reported separately by Tokei. Prime Agent and Pi Coding Agent are distinct tools even though they share a session format.
- **Session**: One persisted session JSONL file. A Prime Agent root session and each RLM child session are separate sessions.
- **Usage Event**: The usage attached to one persisted assistant message. It represents one provider response and is the unit Tokei adds to token and cost totals.
- **Attributed Child Usage**: A Prime Agent parent-session bookkeeping event that summarizes usage produced by a child session. It is not a usage event and is excluded when the child session's own usage events are available.
- **Project**: The working directory recorded by a session header. Usage from root and child sessions is assigned to that recorded directory.
- **Actual Cost**: Cost persisted with a usage event by the tool. Tokei uses the model price table only when actual cost is absent.
