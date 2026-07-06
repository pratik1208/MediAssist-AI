You are acting as a Product Manager.

I will provide a project specification in Markdown.

Your job is to convert it into a clear, concise Product Requirements Document (PRD).

The PRD should:
- Capture all requirements from the specification (MediassistAAI.md).
- Not invent major features that are not mentioned.
- Clearly mark any assumptions.
- Keep the document concise and implementation-agnostic.
- Be suitable for a solo developer building the backend and an AI coding assistant building the frontend.

Structure the PRD as follows:

# Product Overview

# Problem Statement

# Goals

# Target Users

# Core Features
For each feature include:
- Purpose
- User Value
- Priority (Must Have / Should Have / Nice to Have)

# User Journey

# Screens / Pages

# Functional Requirements

# Non-Functional Requirements

# Edge Cases

# Assumptions

# Future Enhancements

If the specification is missing information, list it under "Assumptions" instead of making up functionality.

Do not include:
- Database schema
- API design
- Backend architecture
- Folder structure
- Code examples
- Technology stack recommendations

The PRD should serve as the single source of truth for the product.

Also I want feature matrix
| Agent   | Purpose  | Inputs     | Outputs          | Dependencies | Status  |
| ------- | -------- | ---------- | ---------------- | ------------ | ------- |
| Agent 1 | Research | User query | Research summary | None         | MVP     |
| Agent 2 | Planning | Research   | Execution plan   | Agent 1      | MVP     |
| Agent 3 | ...      | ...        | ...              | ...          | Phase 2 |
