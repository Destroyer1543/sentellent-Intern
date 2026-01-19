# Sentellent – Contextual Agentic AI Assistant

Sentellent is a production-oriented, stateful agentic AI system built to safely perform real-world actions such as reading emails, scheduling calendar events, and managing user preferences. The system combines deterministic logic with LLM-based reasoning to ensure correctness, debuggability, and user control.

This project is intentionally designed to avoid common agent failures such as hallucinated actions, silent side effects, infinite loops, and loss of conversational state.

---

<img width="1919" height="925" alt="Screenshot from 2026-01-19 12-47-23" src="https://github.com/user-attachments/assets/14e8b222-a77f-43ab-95be-2463041fdd3b" />

<img width="1919" height="922" alt="trhh" src="https://github.com/user-attachments/assets/83263031-5e3f-436f-89d7-de864d703bdd" />


## System Goals

- Support real-world actions (email, calendar) safely
- Persist context across turns and sessions
- Handle incomplete requests via multi-turn resolution
- Require explicit confirmation for all write operations
- Be deterministic where possible and probabilistic only where necessary
- Be deployable and observable in production

---

## High-Level Architecture

User  
→ Frontend (Next.js)  
→ Backend API (FastAPI)  
→ Agent Runtime (LangGraph)  
→ External Services (Google APIs)

---

## Backend Architecture

### Core Stack
- FastAPI for API layer
- LangGraph for agent control flow
- SQLite (running inside ECS) for persistence
- Google OAuth for authentication
- Deterministic parsers + LLM planner hybrid

---

## Agent Runtime (LangGraph)

The agent runs inside a bounded LangGraph loop with explicit state transitions.

### Nodes

1. Planner  
2. Executor  
3. Checker  
4. Responder  

The graph enforces:
- Maximum iteration count
- Explicit termination conditions
- Fallback routing on repeated failure or empty plans

---

## Planner Implementation Details

The planner is **priority-ordered and deterministic-first**.

Execution order:

1. Pending Action Gate  
   - If a pending action exists, the planner does not generate new plans
   - Only confirmation or cancellation is accepted

2. Pending Intent Resolution  
   - If an intent is incomplete, the planner merges:
     - ORIGINAL_REQUEST
     - USER_FOLLOWUP
   - Missing slots are detected deterministically

3. Deterministic Routing  
   - Known intents (gmail send, calendar create, preferences) are parsed using regex / structured extraction
   - Prevents LLM hallucinations for critical actions

4. LLM Planning Fallback  
   - Used only when deterministic parsing fails or for complex reasoning
   - Produces a structured plan, not direct execution

The planner may set:
- `pending_intent`
- `pending_action`
- `needs_more` flags

---

## Pending Intent (Multi-turn Slot Filling)

Pending intents enable multi-turn task completion.

### Example
User: “Schedule a meeting”  
→ Missing fields detected (time, duration, title)

The system:
- Stores a PendingIntent record in the database
- Waits for follow-up messages
- Merges follow-ups with the original request
- Re-runs parsing until all required slots are filled

Pending intents are cleared automatically once resolved or explicitly cancelled.

---

## Pending Action (Confirmation Gate)

All write operations are staged as pending actions.

### Write actions include:
- Sending email
- Creating calendar events
- Updating preferences
- Any irreversible external mutation

Flow:
1. Planner prepares action payload
2. Action is stored as `pending_action`
3. Frontend displays confirmation card
4. User must explicitly confirm or cancel
5. Only on confirm does execution occur

No write action can bypass this gate.

---

## Executor Implementation

The executor:
- Runs only approved tool calls
- Receives structured payloads from the planner
- Returns tool results without side effects unless confirmed

Supported tools:
- gmail_list_important (supports pagination and “show all”)
- calendar_prepare_event
- calendar_list_events

All tool outputs are normalized before returning to the agent state.

---

## Checker Node

The checker enforces safety and termination:

- Detects repeated failures
- Detects empty or non-progressing plans
- Enforces a hard iteration cap (5)
- Routes to fallback execution lane when necessary

This prevents:
- Infinite loops
- LLM indecision
- Repeated tool misuse

---

## Fallback Lane

If planning fails repeatedly:
- The agent enters a controlled fallback path:
  - codegen
  - security_check
  - sandbox_run

Constraints:
- Max 5 retries
- Only allowlisted wrappers (Gmail/Calendar)
- No filesystem or network escape
- Read-only unless explicitly confirmed

---

## Memory System

### Memory Types

1. Long-term Memory  
   - Preferences (timezone, defaults)
   - Stable user facts

2. Short-term State  
   - Pending intents
   - Pending actions

Memory is:
- Stored in the database
- Hydrated into agent state at request start
- Updated only via explicit writebacks

---

## Frontend Implementation

### Stack
- Next.js (App Router)
- Google OAuth-only authentication
- Chat-based UI

### UI Guarantees
- Input is locked when a pending action exists
- Pending cards clear immediately on confirm/cancel
- Single global pending_action source of truth:
  - `sentellent_pending_action_global` (localStorage)
- Prevents stale rehydration or double execution

---

## Authentication Flow

- Google OAuth with Gmail and Calendar scopes
- Encoded OAuth state includes user_id
- Callback validates and stores tokens in DB
- Backend uses stored tokens for tool execution
- Tokens are never exposed to the frontend

---

## Timezone Handling

- Default timezone is Asia/Kolkata (IST)
- No timezone clarification prompts unless user explicitly asks
- All calendar operations normalize to this timezone

---

## Infrastructure and Deployment

### CI/CD

Frontend:
- Auto-deployed via Vercel on git push

Backend:
- GitHub Actions with AWS OIDC
- Docker image built and pushed to ECR
- ECS Fargate service updated with immutable image tags

### Infrastructure as Code

Terraform manages:
- VPC
- ALB
- ECS cluster and services
- ECR repositories
- CloudWatch logs

Secrets are injected at runtime via ECS task definitions.

SQLite is used as the runtime database inside ECS.

---

## Why This Architecture

Most agent systems fail because they:
- Are stateless
- Allow LLMs to directly execute actions
- Lack confirmation or recovery mechanisms

Sentellent is intentionally:
- Deterministic where correctness matters
- Stateful across turns and sessions
- Explicit about side effects
- Safe to resume, debug, and extend

This makes the system suitable for real workflows rather than demos.

---

## Current Status

- End-to-end deployed and verified
- OAuth, memory, pending intents, and confirmation gates working
- Gmail and Calendar tools functional
- UI and pagination refinements in progress

---

## License

MIT


