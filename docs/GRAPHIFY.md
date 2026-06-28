# Knowledge Graph (Graphify)

The Knowledge Graph page visualizes the Neo4j incident memory as an interactive force-directed graph.

## Accessing it

Navigate to **http://localhost:3000/graph** or click **Knowledge Graph** in the sidebar.

## What it shows

Every incident Aeon processes gets stored in Neo4j as a graph of relationships. The visualization shows:

| Node color | Type | Meaning |
|---|---|---|
| Orange | **Incident** | A CI/CD failure event (e.g. `inc_seed_003`) |
| Blue | **Pipeline** | The pipeline where it occurred (e.g. `pipe_android_88`) |
| Yellow | **ErrorType** | The category of error (e.g. `dependency_conflict`) |
| Green | **Fix** | The resolution applied (e.g. `Force androidx.core:1.15.0`) |

Edge types:
- `CAUSED_BY` — incident → pipeline
- `HAS_ERROR` — incident → error type
- `RESOLVED_BY` — incident → fix
- `FIXED_BY` — error type → fix (with reuse count)

## How to use it

- **Drag** nodes to rearrange the layout
- **Scroll** to zoom in/out
- **Click a node** to zoom in and see its details in the panel (top right)
- **Hover** over an edge to see the relationship type
- Click **Refresh** to reload data from Neo4j
- Labels appear automatically when zoomed in enough

## What to look for in the demo

The two Android incidents (`inc_seed_003` and `inc_seed_004`) both connect to the same `dependency_conflict` error type and the same `Fix` node — visually showing that Aeon recognized a recurring pattern and reused the same resolution. This is the "incident memory" differentiator.

## Backend API

The graph data is served by:
```
GET /api/memory/graph
```

Returns:
```json
{
  "nodes": [
    { "id": "inc_seed_003", "label": "Incident" },
    { "id": "dependency_conflict", "label": "ErrorType" }
  ],
  "edges": [
    { "source": "inc_seed_003", "target": "dependency_conflict", "type": "HAS_ERROR" }
  ]
}
```

Falls back to mock data if Neo4j is not connected, so the graph always renders.

## Seeding data

If the graph is empty, seed it first:
```powershell
Invoke-RestMethod -Uri http://localhost:8000/api/memory/seed -Method Post
```

Then click **Refresh** on the graph page.
