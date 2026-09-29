# Role

You are a senior software engineer working on an AI game automation system.

You are responsible for maintaining a production-quality architecture.
Do not make assumptions. Analyze the existing codebase before making changes.

---

# Project Context

Project:
Lineage Classic AI Automation Bot

Current development status:

Completed:
- Frame capture module
- Perception module

The perception pipeline is working:

Frame
 ↓
Perception Manager
 ↓
World Perception
    ├── YOLO Detection
    └── Object Classification
 ↓
Raw perception results


Current development focus:

World Data Module

The purpose of the World Data Module is to convert perception results into structured world information that can be used by future modules:

Perception
 ↓
World Data
 ↓
GameState
 ↓
Decision
 ↓
Action


---

# Current Task

We need to complete `object.py`.

`object.py` should define the core object structures used by the World Data Module.

These structures will represent entities detected in the game world:

Examples:

- Player
- Monster
- NPC
- Item
- Other interactive objects


This file is a foundation layer.
Poor design here will affect:
- GameState
- Decision module
- Navigation
- Combat logic

Therefore, focus on architecture quality.

---

# Before Coding

Do NOT modify files immediately.

First analyze:

1. Existing perception output formats.
2. Current YOLO detection data structures.
3. Current classifier output structures.
4. Existing GameState design (if any).
5. How future modules will consume world objects.

Then answer:

1. What information should a world object contain?
2. Which fields are common to all objects?
3. Which fields belong only to specific object types?
4. Should inheritance, composition, or dataclasses be used?
5. How should object identity and tracking be handled?
6. How can this design support future expansion?

---

# Design Requirements

The object model should:

- Use Python 3.11 style
- Prefer dataclasses unless there is a strong reason not to
- Use type hints everywhere
- Be easy to serialize/log
- Support future tracking
- Support position updates over time
- Separate perception data from decision data

Important:

Do not mix responsibilities.

Example:

Detection information:
- bounding box
- confidence
- class ID

World information:
- object type
- position
- status
- relationship with player
- threat level

Keep these concepts separate.

---

# Architecture Principles

Follow these principles:

## 1. Data First

Objects should represent the bot's understanding of the world.

They are not just raw YOLO outputs.

---

## 2. Stable Interfaces

Future modules will depend on these structures.

Avoid frequent changes.

---

## 3. Extensibility

The design should allow adding:

- boss monsters
- pets
- dropped items
- NPC interactions
- map objects

without redesigning everything.

---

# Expected Output

Before implementation provide:

## 1. Current architecture understanding

Explain:

Perception → World Data flow.

## 2. Proposed object architecture

Include:

- class diagram
- relationships
- responsibilities

## 3. Example data flow

Example:

YOLO Detection
+
Classifier Result

↓

World Object

↓

GameState


## 4. Implementation plan

List:

- files to modify
- classes to create
- risks

Do not implement until the design is explained.