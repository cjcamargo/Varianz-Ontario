# ADR-001: Modular monolith

Status: Accepted | Date: 2026-07-11

## Context and decision

A two-person company needs strong domain boundaries without microservice operations. Build one FastAPI deployable plus worker, organized by modules with explicit application interfaces and exclusive write ownership.

## Consequences and reversal trigger

Shared deployment and transactions reduce cost; module tests and import rules prevent accidental coupling. Extract a service only when measured scaling, isolation or independent release needs cannot be solved within the monolith.

