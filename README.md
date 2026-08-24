# PredLab

A personal football prediction tracking system, built to test one honest question: **is my gut instinct about football actually worth anything, or does it just feel that way?**

## What it does

Every match gets two independent guesses, logged before kickoff and never editable afterward:

- **A model's guess** — Elo ratings for who wins, a Poisson goal model for over/under and both-teams-to-score
- **My own guess** — a gut call, logged only when I feel strongly about a match, at a fixed confidence level (95%, 75%, or 50%)

Once the match is played, both guesses are graded the same way — using **Brier score**, a standard way of scoring not just whether you were right, but whether your confidence was justified. A confident wrong call costs far more than an uncertain wrong call.

## Why insert-only matters

Predictions and gut calls can never be edited or deleted once logged. This is enforced at the code level, not just a rule I follow. A track record only means something if it can't be quietly cleaned up after the fact — so the system doesn't allow it, even for me.

## Current scope

- English Premier League, 2026/27 season
- Multiple markets: match result (1X2), over/under 2.5 goals, both teams to score
- A pluggable model registry — currently running one model (`elo_poisson_v1`), designed so additional models can be added and compared side by side without changing the rest of the system

## Stack

Flask + SQLite backend, React frontend, running locally.

## Status

Early season. Track record is being built in public, starting now — nothing has been cleaned up or adjusted after the fact.
