## knowledge-base-document-preprocessor

**Author:** k-ishigaki
**Version:** 0.0.1
**Type:** tool

### Description



### `_split_and_prefix` Flow

```mermaid
flowchart TD
    A[Start] --> B{Next line?}
    B -->|No| C{Buffer empty?}
    C -->|Yes| Z[End]
    C -->|No| D[emit_chunk(buffer, no delimiter)] --> Z
    B -->|Yes| E{Heading ≤ split level and buffer has data?}
    E -->|Yes| F[emit_chunk(buffer, with delimiter)]
    F --> G[Reset buffer state]
    E -->|No| G
    G --> H{Buffer empty?}
    H -->|Yes| I[Snapshot headings & compute data-path]
    H -->|No| I
    I --> J[Append line to buffer]
    J --> K{Line blank?}
    K -->|Yes| L[Remember last blank]
    K -->|No| M{Line is heading (non-first)?}
    M -->|Yes| N[Record last heading idx]
    M -->|No| O{Line starts without leading space?}
    O -->|Yes| P[Record last non-indent idx]
    O -->|No| Q[Leave indices]
    L --> R
    N --> R
    P --> R
    Q --> R
    R{Chunk length ≥ max?} -->|No| S[Advance to next line]
    R -->|Yes| T[Pick split idx]
    T -->|Heading idx>0| U[cut ← heading-1]
    T -->|No heading| V{Blank idx ≥0?}
    V -->|Yes| W[cut ← blank idx]
    V -->|No| X{Non-indent idx>0?}
    X -->|Yes| Y[cut ← non-indent-1]
    X -->|No| AA[cut ← end]
    U --> AB
    W --> AB
    Y --> AB
    AA --> AB
    AB[emit_chunk(left slice, delimiter if needed)] --> AC[Rebuild buffer + metadata]
    AC --> R
    S --> B
```
