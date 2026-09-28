
# UIStyleGuide.md

# ICU Patient Tracker UI Style Guide

## Purpose

This document defines the visual and interaction principles for the ICU Patient Tracker. It focuses on consistency, efficiency, and clinical workflow rather than specific screenshots or mockups.

---

# Core Philosophy

The interface exists to maximize clinician efficiency.

Every design decision should support:

- Faster workflow
- Lower cognitive load
- Greater reliability
- High information density
- Predictable interaction

Visual aesthetics are secondary to usability.

---

# Design Priorities

1. Clinical workflow
2. Information density
3. Keyboard efficiency
4. Readability
5. Consistency
6. Reliability
7. Visual polish

---

# Overall Style

The application should resemble professional desktop software rather than consumer applications.

Inspired by:

- Visual Studio
- JetBrains IDEs
- Qt Creator
- Microsoft Excel
- Adobe Lightroom

Avoid excessive whitespace, oversized controls, decorative animations, and oversized rounded elements.

---

# Layout Principles

- Stable layouts; controls should not move unexpectedly.
- Keep related information visually grouped.
- Maximize useful information per screen.
- Minimize unnecessary dialogs.
- Favor docking, split views, and expandable panels.

---

# Progressive Disclosure

Present only the information needed for the current task while keeping additional detail one interaction away.

Typical workflow:

ICU → Patient → Hospital Day → Problem → Task

---

# Keyboard-First Design

Every common action should be available through the keyboard.

Whenever practical, provide:

- Keyboard shortcut
- Context menu
- Toolbar/menu action
- Mouse interaction

Focus should move predictably.

Tab order must be logical.

---

# Editing Philosophy

Prefer in-place editing over modal dialogs.

Example:

Double-click → Edit → Enter → Save

instead of

Dialog → Edit → OK → Close

---

# Typography

Hierarchy should communicate clinical importance.

Recommended scale:

- Patient name: largest
- Section headers
- Standard content
- Metadata
- Monospace only when alignment improves readability

---

# Color Philosophy

Colors communicate status—not decoration.

Recommended semantic roles:

- Primary background
- Secondary background
- Panel background
- Border
- Accent
- Selection
- Success
- Warning
- Critical
- Informational
- Disabled text

---

# Dark Theme

Design the interface for dark mode first.

The light theme should be derived from the dark theme while maintaining identical layout and interaction patterns.

---

# Icons

Icons should reinforce meaning.

They should never be decorative.

Use icons consistently for:

- Charts
- Tasks
- Treatments
- Examinations
- Warnings
- Completion
- Search
- Settings

---

# Tables

Tables are first-class interface elements.

They should support:

- Sorting
- Filtering
- Keyboard navigation
- Copy/paste
- Inline editing where appropriate
- Column resizing
- Persistent column widths when useful

---

# Markdown Support

Markdown is a core feature of the application.

The editor should preserve and render common markdown elements including:

- Headings
- Bold
- Italics
- Bullet lists
- Numbered lists
- Block quotes
- Code blocks
- Horizontal rules
- Tables

Markdown should remain portable so content can be copied directly into external systems when appropriate.

---

# Placeholder Tokens

The application shall support placeholder tokens using the existing workflow.

The token

    #INPUT#

is the standard placeholder.

Requirements:

- Recognized throughout the application.
- Survives saving and loading unchanged.
- Supports tab-to-next-placeholder navigation.
- Works inside markdown tables.
- Works inside lists.
- Works inside free text.
- May appear multiple times in the same document.

This placeholder syntax is considered part of the application's document language.

---

# Clinical Documents

Generated clinical documents should prioritize:

- Readability
- Consistent spacing
- Logical headings
- Predictable formatting
- Copy/paste compatibility

Formatting should remain stable across edits.

---

# Window Behavior

Every window is another view of the same application state.

Windows should:

- Update automatically
- Preserve user context
- Restore previous layout when appropriate
- Avoid unnecessary modal behavior

---

# Feedback

Provide immediate visual feedback after user actions.

Avoid excessive notifications.

Autosave should be quiet unless intervention is required.

---

# Animation

Animation should be minimal.

Use subtle transitions only when they improve comprehension.

Animations must never delay workflow.

---

# Error Messages

Errors should explain:

- What happened
- What data was protected
- What the user can do next

Avoid technical jargon whenever possible.

---

# Consistency Rules

- Similar actions should behave identically.
- Terminology should remain consistent.
- Keyboard shortcuts should remain stable.
- Colors should retain the same meaning everywhere.
- Context menus should follow a common structure.

---

# Definition of Success

A successful interface allows experienced users to work primarily from memory, with minimal mouse travel, minimal cognitive effort, and confidence that every action behaves predictably.
