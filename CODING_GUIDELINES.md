# AgentX Coding Guidelines

## Languages

Python 3.11
TypeScript

## Frameworks

FastAPI
SQLAlchemy
Next.js
Redis

## Architecture Principles

- Event-driven architecture
- Modular microservice style
- ACP-based communication
- No direct agent-to-agent calls

## Folder Responsibilities

platform/src/api
REST API routes

platform/src/services
Core platform logic

platform/src/ml
Machine learning modules

platform/src/models
Database models

agents/
Autonomous AI agents

frontend/
Next.js web interface

## Code Quality

All code should:

- Use type hints
- Include docstrings
- Be asynchronous where possible
- Include logging
